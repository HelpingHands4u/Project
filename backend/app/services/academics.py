"""Authorization and academic invariants, reused in Firestore transactions."""
from datetime import datetime, timezone

from fastapi import HTTPException


def actor_in(state, actor, roles):
    user = state.get("users", actor["id"])
    if not user or not user["active"] or user["role"] not in roles:
        raise HTTPException(403, "You do not have permission for this action.")
    return user


def require_person(state, person_id, role):
    person = state.get("users", person_id)
    if not person or person["role"] != role or not person["active"]:
        raise HTTPException(422, f"Select an active {role} account.")
    return person


def require_course(state, actor, course_id):
    actor_in(state, actor, ("admin", "faculty"))
    course = state.get("courses", course_id)
    if not course:
        raise HTTPException(404, "Course not found.")
    if actor["role"] != "admin" and course["faculty_id"] != actor["id"]:
        raise HTTPException(403, "You cannot manage this course.")
    return course


def add_profile(state, values, uid):
    if any(u["email"] == values["email"].lower() for u in state.rows("users")):
        raise HTTPException(409, "An account with this email already exists.")
    return state.add("users", {
        "name": values["name"], "email": values["email"].lower(), "role": values["role"],
        "department": values["department"], "firebase_uid": uid, "active": True, "session_version": 0,
    })


def provision_user(store, identity, values, actor=None):
    if any(u["email"] == values["email"].lower() for u in store.snapshot().rows("users")):
        raise HTTPException(409, "An account with this email already exists.")
    uid = identity.create_user(values["email"].lower(), values["password"], values["name"])

    def create(state):
        if actor:
            actor_in(state, actor, ("admin",))
        return add_profile(state, values, uid)

    try:
        return store.mutate(create)
    except Exception:
        # A commit acknowledgment may have been lost. Keep a successfully
        # created profile before considering compensation.
        try:
            profile = store.user_for_uid(uid)
            if profile:
                return profile
            identity.delete_user(uid)
        except Exception:
            # A standalone Auth account has no academic role and cannot log in.
            # Never hide the original provider error with a cleanup error.
            pass
        raise


def overlap(a, b):
    return a["day"] == b["day"] and a["start"] < b["end"] and a["end"] > b["start"]


def create_record(state, actor, kind, values):
    actor_in(state, actor, ("admin",) if kind in ("course", "enrollment", "notice", "slot") else ("admin", "faculty"))
    if kind == "course":
        require_person(state, values["faculty_id"], "faculty")
        values["code"] = values["code"].upper()
        if any(c["code"] == values["code"] for c in state.rows("courses")):
            raise HTTPException(409, "This course code already exists.")
        return state.add("courses", values)
    if kind == "notice":
        return state.add("notices", {**values, "author_id": actor["id"], "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat()})
    course = require_course(state, actor, values["course_id"])
    if kind == "slot":
        students = {e["student_id"] for e in state.rows("enrollments") if e["course_id"] == course["id"]}
        for slot in state.rows("timetable"):
            other = state.get("courses", slot["course_id"])
            others = {e["student_id"] for e in state.rows("enrollments") if e["course_id"] == other["id"]}
            if overlap(slot, values) and (
                slot["room"].casefold() == values["room"].casefold()
                or course["faculty_id"] == other["faculty_id"]
                or students & others or course["id"] == other["id"]
            ):
                raise HTTPException(409, "This time overlaps a room, faculty or student schedule.")
        return state.add("timetable", values)
    require_person(state, values["student_id"], "student")
    enrolled = any(e["student_id"] == values["student_id"] and e["course_id"] == values["course_id"] for e in state.rows("enrollments"))
    if kind == "enrollment":
        if enrolled:
            raise HTTPException(409, "The student is already enrolled in this course.")
        existing = {e["course_id"] for e in state.rows("enrollments") if e["student_id"] == values["student_id"]}
        before = [s for s in state.rows("timetable") if s["course_id"] in existing]
        after = [s for s in state.rows("timetable") if s["course_id"] == course["id"]]
        if any(overlap(a, b) for a in before for b in after):
            raise HTTPException(409, "This course overlaps the student's existing timetable.")
        return state.add("enrollments", values)
    if not enrolled:
        raise HTTPException(422, "The student is not enrolled in this course.")
    collection, key = ("attendance", "date") if kind == "attendance" else ("grades", "assessment")
    if kind == "grade":
        values["assessment"] = values["assessment"].title()
    for record in state.rows(collection):
        if all(record[k] == values[k] for k in ("student_id", "course_id", key)):
            record.update(values)
            return record
    return state.add(collection, values)
