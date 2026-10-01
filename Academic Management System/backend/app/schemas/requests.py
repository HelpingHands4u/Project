from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator
from backend.app.utils.dates import campus_today

Role = Literal["student", "faculty", "admin"]


class Input(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", allow_inf_nan=False)


class Login(Input):
    email: EmailStr
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=1, max_length=128)
    role: Role


class NewUser(Input):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=10, max_length=128)
    role: Role
    department: str = Field(min_length=2, max_length=100)


class UserStatus(Input):
    active: bool


class NewCourse(Input):
    code: str = Field(pattern=r"^[A-Za-z0-9-]{2,20}$")
    name: str = Field(min_length=2, max_length=100)
    department: str = Field(min_length=2, max_length=100)
    credits: int = Field(ge=1, le=10)
    semester: int = Field(ge=1, le=12)
    faculty_id: int = Field(gt=0)


class NewEnrollment(Input):
    student_id: int = Field(gt=0)
    course_id: int = Field(gt=0)


class AttendanceEntry(NewEnrollment):
    date: date
    status: Literal["present", "absent"]

    @model_validator(mode="after")
    def not_future(self):
        if self.date > campus_today():
            raise ValueError("Attendance cannot be recorded for a future date.")
        return self


class GradeEntry(NewEnrollment):
    assessment: str = Field(min_length=2, max_length=60)
    score: float = Field(ge=0, le=1000)
    maximum: float = Field(gt=0, le=1000)

    @model_validator(mode="after")
    def valid_score(self):
        if self.score > self.maximum:
            raise ValueError("Score cannot exceed maximum marks.")
        return self


class NewNotice(Input):
    title: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=5, max_length=2000)
    audience: Literal["all", "student", "faculty"]


class NewSlot(Input):
    course_id: int = Field(gt=0)
    day: int = Field(ge=0, le=5)
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    room: str = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def ordered_times(self):
        if self.end <= self.start:
            raise ValueError("End time must be after start time.")
        return self
