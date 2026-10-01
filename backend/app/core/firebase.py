"""Server-only Firebase configuration. Importing the app never needs secrets."""
import json
import os
from functools import lru_cache

import firebase_admin
from dotenv import load_dotenv
from fastapi import HTTPException
from firebase_admin import credentials, firestore
from google.auth.credentials import AnonymousCredentials

load_dotenv()


class ConfigurationError(Exception):
    pass


class EmulatorCredential(credentials.Base):
    def get_credential(self):
        return AnonymousCredentials()


def demo_mode():
    # Demo accounts are only shown after the operator deliberately enables them.
    return os.getenv("DEMO_MODE", "false").lower() == "true"


@lru_cache
def firebase_app():
    project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    auth_emulator = os.getenv("FIREBASE_AUTH_EMULATOR_HOST")
    db_emulator = os.getenv("FIRESTORE_EMULATOR_HOST")
    if not project_id:
        raise ConfigurationError("Set FIREBASE_PROJECT_ID and Firebase credentials. See FIREBASE_SETUP.md.")
    if auth_emulator or db_emulator:
        if os.getenv("VERCEL") or not (auth_emulator and db_emulator and project_id.startswith("demo-")):
            raise ConfigurationError("Emulators require both hosts and a demo- project ID, and cannot run on Vercel.")
        credential = EmulatorCredential()
    else:
        raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
        try:
            if raw:
                data = json.loads(raw)
                if data.get("project_id") != project_id:
                    raise ConfigurationError("Firebase credentials and FIREBASE_PROJECT_ID must use the same project.")
                credential = credentials.Certificate(data)
            elif os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
                credential = credentials.ApplicationDefault()
                if credential.project_id != project_id:
                    raise ConfigurationError("Firebase credentials and FIREBASE_PROJECT_ID must use the same project.")
            else:
                raise ConfigurationError("Add Firebase server credentials. See FIREBASE_SETUP.md.")
        except (ValueError, KeyError, OSError):
            raise ConfigurationError("Firebase server credentials are invalid. Check your environment settings.") from None
    return firebase_admin.initialize_app(credential, {"projectId": project_id}, name="uams")


@lru_cache
def firestore_store():
    from backend.app.services.firestore_store import FirestoreStore
    return FirestoreStore(firestore.client(app=firebase_app()))


@lru_cache
def firebase_identity():
    from backend.app.services.identity import FirebaseIdentity
    return FirebaseIdentity(firebase_app(), os.getenv("FIREBASE_WEB_API_KEY", ""))


def get_store():
    try:
        return firestore_store()
    except ConfigurationError as error:
        raise HTTPException(503, str(error)) from None


def get_identity():
    try:
        return firebase_identity()
    except ConfigurationError as error:
        raise HTTPException(503, str(error)) from None
