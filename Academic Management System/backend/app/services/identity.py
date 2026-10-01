"""Firebase Authentication is the only production password store."""
import os

import httpx
from fastapi import HTTPException
from firebase_admin import auth

from backend.app.core.firebase import ConfigurationError


class FirebaseIdentity:
    def __init__(self, app, api_key, transport=None):
        if not api_key:
            raise ConfigurationError("Set FIREBASE_WEB_API_KEY from your Firebase project settings.")
        self.app = app
        self.api_key = api_key
        self.transport = transport

    def sign_in(self, email, password):
        emulator = os.getenv("FIREBASE_AUTH_EMULATOR_HOST")
        origin = f"http://{emulator}/identitytoolkit.googleapis.com" if emulator else "https://identitytoolkit.googleapis.com"
        with httpx.Client(timeout=15, transport=self.transport) as client:
            response = client.post(f"{origin}/v1/accounts:signInWithPassword",
                                   params={"key": self.api_key},
                                   json={"email": email, "password": password, "returnSecureToken": True})
        try:
            result = response.json()
        except ValueError:
            raise HTTPException(503, "Firebase sign-in is temporarily unavailable.") from None
        if response.is_success:
            # The UID comes directly from Firebase over TLS, never from browser input.
            uid = result.get("localId")
            if not isinstance(uid, str) or not uid:
                raise HTTPException(503, "Firebase returned an invalid sign-in response.")
            return uid
        code = result.get("error", {}).get("message", "")
        if response.status_code == 429 or code.startswith("TOO_MANY_ATTEMPTS"):
            raise HTTPException(429, "Too many sign-in attempts. Please try again later.")
        if code in {"INVALID_LOGIN_CREDENTIALS", "EMAIL_NOT_FOUND", "INVALID_PASSWORD", "USER_DISABLED", "INVALID_EMAIL"}:
            raise HTTPException(401, "Email, password or selected portal is incorrect.")
        if code == "OPERATION_NOT_ALLOWED":
            raise HTTPException(503, "Enable Email/Password sign-in in Firebase Authentication.")
        raise HTTPException(503, "Firebase sign-in is unavailable. Check the project's Web API key and provider settings.")

    def create_user(self, email, password, name):
        try:
            return auth.create_user(email=email, password=password, display_name=name, app=self.app).uid
        except auth.EmailAlreadyExistsError:
            raise HTTPException(409, "An account with this email already exists.") from None

    def get_user(self, uid):
        try:
            record = auth.get_user(uid, app=self.app)
        except auth.UserNotFoundError:
            return None
        return {"uid": record.uid, "disabled": record.disabled,
                "valid_after": record.tokens_valid_after_timestamp / 1000}

    def set_active(self, uid, active):
        auth.update_user(uid, disabled=not active, app=self.app)

    def delete_user(self, uid):
        auth.delete_user(uid, app=self.app)
