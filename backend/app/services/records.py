"""Role-filtered public responses. Internal Firebase UIDs stay on the server."""


def user_data(user):
    return {key: user[key] for key in ("id", "name", "email", "role", "department", "active")}


def dashboard(state, user):
    role, user_id = user["role"], user["id"]
    courses = state.rows("courses")
    own_ids = {e["course_id"] for e in state.rows("enrollments") if e["student_id"] == user_id}
    if role == "faculty":
        courses = [c for c in courses if c["faculty_id"] == user_id]
    elif role == "student":
        courses = [c for c in courses if c["id"] in own_ids]
    course_ids = {c["id"] for c in courses}
    enrollments = [e for e in state.rows("enrollments") if e["course_id"] in course_ids and (role != "student" or e["student_id"] == user_id)]
    visible_ids = {e["student_id"] for e in enrollments} | {c["faculty_id"] for c in courses} | {user_id}
    people = [u for u in state.rows("users") if role == "admin" or u["id"] in visible_ids]
    names = {p["id"]: p["name"] for p in people}
    attendance = [a for a in state.rows("attendance") if a["course_id"] in course_ids and (role != "student" or a["student_id"] == user_id)]
    grades = [g for g in state.rows("grades") if g["course_id"] in course_ids and (role != "student" or g["student_id"] == user_id)]
    notices = [n for n in state.rows("notices") if role == "admin" or n["audience"] in ("all", role)]
    return {
        "user": user_data(user),
        "people": [user_data(p) for p in sorted(people, key=lambda p: p["name"])],
        "courses": [
            {**c, "faculty": names.get(c["faculty_id"], "Faculty"),
             "students": sum(e["course_id"] == c["id"] for e in enrollments)}
            for c in sorted(courses, key=lambda c: c["code"])
        ],
        "enrollments": enrollments,
        "attendance": sorted(attendance, key=lambda a: (a["date"], a["id"]), reverse=True),
        "grades": sorted(grades, key=lambda g: g["id"], reverse=True),
        "notices": sorted(notices, key=lambda n: (n["created_at"], n["id"]), reverse=True),
        "timetable": sorted([s for s in state.rows("timetable") if s["course_id"] in course_ids], key=lambda s: (s["day"], s["start"])),
    }
