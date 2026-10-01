"""Same-origin UAMS frontend/API with Firebase Auth and Firestore."""
import hashlib
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from firebase_admin.exceptions import FirebaseError
from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import GoogleAuthError

from backend.app.core.firebase import demo_mode, get_identity, get_store
from backend.app.schemas.requests import AttendanceEntry, GradeEntry, Login, NewCourse, NewEnrollment, NewNotice, NewSlot, NewUser, UserStatus
from backend.app.services.academics import actor_in, create_record, provision_user
from backend.app.services.records import dashboard, user_data
from backend.app.utils.dates import campus_today

app = FastAPI(title="UAMS Firebase API", version="2.0.0", docs_url=None, openapi_url="/api/openapi.json", redoc_url=None)
COOKIE = "uams_session"


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@app.middleware("http")
async def request_security(request, call_next):
    if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("X-UAMS-Request") != "1" or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Request verification failed."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


async def provider_error(_request, _error):
    # Provider exceptions may contain service-account details. Never send them.
    return JSONResponse({"detail": "Firebase is unavailable. Check server credentials, Firestore setup and network access."}, status_code=503)


for exception in (FirebaseError, GoogleAPICallError, GoogleAuthError, httpx.HTTPError):
    app.add_exception_handler(exception, provider_error)


def current_user(request: Request, store=Depends(get_store), identity=Depends(get_identity)):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Please sign in to continue.")
    session = store.get_session(token_hash(token))
    if not session or session["expires_at"] <= datetime.now(timezone.utc):
        raise HTTPException(401, "Your session expired. Please sign in again.")
    user = store.get_user(session["user_id"])
    if not user or not user["active"] or user["session_version"] != session["version"]:
        raise HTTPException(401, "This session is no longer active.")
    firebase_user = identity.get_user(user["firebase_uid"])
    if not firebase_user or firebase_user["disabled"] or firebase_user["valid_after"] > session["issued_at"]:
        raise HTTPException(401, "This Firebase account is unavailable. Please sign in again.")
    return user


def admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access required.")
    return user


@app.get("/api/health")
def health(store=Depends(get_store)):
    store.health()
    return {"status": "ok", "storage": "firestore"}


@app.get("/api/config")
def config():
    return {"demo_mode": demo_mode(), "today": campus_today()}


@app.post("/api/auth/login")
def login(payload: Login, request: Request, response: Response, store=Depends(get_store), identity=Depends(get_identity)):
    uid = identity.sign_in(str(payload.email).lower(), payload.password)
    user = store.user_for_uid(uid)
    if not user or not user["active"] or user["role"] != payload.role:
        raise HTTPException(401, "Email, password or selected portal is incorrect.")
    token = secrets.token_urlsafe(48)
    store.save_session(token_hash(token), {
        "user_id": user["id"], "version": user["session_version"], "issued_at": time.time(),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=8),
    })
    previous = request.cookies.get(COOKIE)
    if previous:
        store.delete_session(token_hash(previous))
    response.set_cookie(COOKIE, token, httponly=True, secure=bool(os.getenv("VERCEL")) or request.url.scheme == "https", samesite="lax", max_age=28800, path="/")
    return user_data(user)


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, store=Depends(get_store)):
    store.delete_session(token_hash(request.cookies.get(COOKIE, "")))
    response.delete_cookie(COOKIE, path="/")


@app.get("/api/dashboard")
def get_dashboard(user=Depends(current_user), store=Depends(get_store)):
    return dashboard(store.snapshot(), user)


@app.post("/api/users", status_code=201)
def create_user(payload: NewUser, actor=Depends(admin), store=Depends(get_store), identity=Depends(get_identity)):
    return user_data(provision_user(store, identity, payload.model_dump(), actor))


@app.patch("/api/users/{user_id}")
def update_user(user_id: int, payload: UserStatus, actor=Depends(admin), store=Depends(get_store), identity=Depends(get_identity)):
    person = store.get_user(user_id)
    if not person:
        raise HTTPException(404, "User not found.")
    if person["role"] == "admin":
        raise HTTPException(422, "Administrator accounts cannot be disabled here.")

    def change(state):
        actor_in(state, actor, ("admin",))
        person = state.get("users", user_id)
        person["active"] = payload.active
        person["session_version"] += 1
        return person

    # Disable access in our database first; enable Firebase first. Any failure
    # leaves a denied account instead of exposing an unintentionally active one.
    if payload.active:
        identity.set_active(person["firebase_uid"], True)
    person = store.mutate(change)
    if not payload.active:
        identity.set_active(person["firebase_uid"], False)
    return user_data(person)


def save_record(store, actor, kind, payload):
    # Callbacks can be retried by Firestore; pass a fresh dict on each attempt.
    return store.mutate(lambda state: create_record(state, actor, kind, payload.model_dump(mode="json")))


@app.post("/api/courses", status_code=201)
def create_course(payload: NewCourse, actor=Depends(admin), store=Depends(get_store)):
    return {"id": save_record(store, actor, "course", payload)["id"]}


@app.post("/api/enrollments", status_code=201)
def enroll(payload: NewEnrollment, actor=Depends(admin), store=Depends(get_store)):
    save_record(store, actor, "enrollment", payload)
    return {"message": "Student enrolled."}


@app.put("/api/attendance")
def attendance(payload: AttendanceEntry, actor=Depends(current_user), store=Depends(get_store)):
    save_record(store, actor, "attendance", payload)
    return {"message": "Attendance saved."}


@app.put("/api/grades")
def grades(payload: GradeEntry, actor=Depends(current_user), store=Depends(get_store)):
    save_record(store, actor, "grade", payload)
    return {"message": "Marks saved."}


@app.post("/api/notices", status_code=201)
def create_notice(payload: NewNotice, actor=Depends(admin), store=Depends(get_store)):
    return {"id": save_record(store, actor, "notice", payload)["id"]}


def delete_record(store, actor, collection, record_id):
    def remove(state):
        actor_in(state, actor, ("admin",))
        if not state.remove(collection, record_id):
            raise HTTPException(404, "Record not found.")
    store.mutate(remove)


@app.delete("/api/notices/{notice_id}", status_code=204)
def delete_notice(notice_id: int, actor=Depends(admin), store=Depends(get_store)):
    delete_record(store, actor, "notices", notice_id)


@app.post("/api/timetable", status_code=201)
def create_slot(payload: NewSlot, actor=Depends(admin), store=Depends(get_store)):
    return {"id": save_record(store, actor, "slot", payload)["id"]}


@app.delete("/api/timetable/{slot_id}", status_code=204)
def delete_slot(slot_id: int, actor=Depends(admin), store=Depends(get_store)):
    delete_record(store, actor, "timetable", slot_id)


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[2] / "frontend", html=True), name="frontend")
