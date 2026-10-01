"""Explicit Firebase setup: python -m backend.app.seed [--demo]."""
import argparse
import os
from datetime import datetime, timedelta, timezone
from getpass import getpass

from pydantic import ValidationError

from backend.app.core.firebase import firestore_store, firebase_identity
from backend.app.schemas.requests import NewUser
from backend.app.services.academics import provision_user
from backend.app.utils.dates import campus_today

DEMO_PASSWORD = "Demo@2026!"


def seed_demo(store, identity):
    if store.snapshot().rows("users"):
        return False
    people = [
        ("Soyel Rana", "student@uams.edu", "student"),
        ("Ananya Sen", "ananya@uams.edu", "student"),
        ("Arjun Das", "arjun@uams.edu", "student"),
        ("Riya Sharma", "riya@uams.edu", "student"),
        ("Dr. Meera Bose", "faculty@uams.edu", "faculty"),
        ("Academic Administrator", "admin@uams.edu", "admin"),
    ]
    accounts = [provision_user(store, identity, {
        "name": name, "email": email, "password": DEMO_PASSWORD, "role": role,
        "department": "Administration" if role == "admin" else "Computer Science",
    }) for name, email, role in people]

    def academics(state):
        courses = [
            ("CS301", "Data Structures & Algorithms", 4), ("CS302", "Database Management Systems", 4),
            ("CS303", "Computer Organization", 3), ("CS304", "Discrete Mathematics", 3),
            ("CS305", "Object Oriented Programming", 4), ("CS306", "Web Technology Lab", 2),
        ]
        for i, (code, name, credits) in enumerate(courses):
            course = state.add("courses", {"code": code, "name": name, "credits": credits, "semester": 3, "department": "Computer Science", "faculty_id": accounts[4]["id"]})
            course_id = course["id"]
            state.add("timetable", {"course_id": course_id, "day": i, "start": "09:00", "end": "10:30", "room": f"Block A · {201 + i}"})
            for j, student in enumerate(accounts[:4]):
                state.add("enrollments", {"student_id": student["id"], "course_id": course_id})
                state.add("grades", {"student_id": student["id"], "course_id": course_id, "assessment": "Internal Assessment 1", "score": 23 - (i + j) % 7, "maximum": 25})
                for k in range(1, 9):
                    state.add("attendance", {"student_id": student["id"], "course_id": course_id, "date": str(campus_today() - timedelta(days=k)), "status": "absent" if (k + i + j) % 8 == 0 else "present"})
        for title, body, audience in [
            ("Welcome to your academic workspace", "Your courses, attendance, marks and weekly timetable are now in one place.", "all"),
            ("Semester III · internal assessments", "Open Marks & results for your published assessment scores. Contact your faculty if you need a review.", "student"),
            ("Keep academic records up to date", "Saved attendance and assessment marks appear in the corresponding student portal.", "faculty"),
        ]:
            state.add("notices", {"title": title, "body": body, "audience": audience, "author_id": accounts[5]["id"], "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat()})
    store.mutate(academics)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Create fictional presentation accounts in an empty Firebase project.")
    args = parser.parse_args()
    store, identity = firestore_store(), firebase_identity()
    if args.demo:
        print("Demo data created." if seed_demo(store, identity) else "Users already exist; no changes made.")
        return
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL") or input("Administrator email: ").strip()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or getpass("Administrator password (at least 12 characters): ")
    if len(password) < 12:
        raise SystemExit("Use at least 12 characters for the administrator password.")
    try:
        payload = NewUser(name="Academic Administrator", email=email, password=password, role="admin", department="Administration")
    except ValidationError:
        raise SystemExit("Enter a valid administrator email and password.") from None
    provision_user(store, identity, payload.model_dump())
    print("Firebase administrator created. You can now use the admin portal.")


if __name__ == "__main__":
    main()
