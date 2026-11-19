"""Pydantic request models."""
from datetime import date, datetime, timezone
from typing import Dict, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.config import get_settings

BRANCHES = ["ADS", "AIML", "BME", "CIVIL", "CSE", "CSD", "ECE", "EEE", "FT", "IT", "MCA", "MCT", "MECH"]


class StudentIn(BaseModel):
    """A participant added by staff (single add or roster upload). Only RegNo, Name and dob are required."""
    RegNo: int = Field(gt=0)
    Name: str = Field(min_length=1, max_length=100)
    dob: date
    email: Optional[EmailStr] = None
    MobNo: Optional[str] = Field(default=None, pattern=r"^[0-9]{10}$")
    year: Optional[int] = Field(default=None, ge=1, le=4)
    Branch: Optional[str] = Field(default=None, max_length=30)
    Sec: Optional[str] = Field(default=None, max_length=10)

    @field_validator("Name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name must not be blank")
        return v

    @field_validator("dob")
    @classmethod
    def dob_plausible(cls, v: date) -> date:
        if v.year < 1950 or v >= date.today():
            raise ValueError("Enter a valid date of birth")
        return v

    def to_doc(self) -> dict:
        """Fields to store; omitted optionals are left out so an update never blanks existing data."""
        doc = {k: v for k, v in self.model_dump().items() if v is not None}
        doc["dob"] = self.dob.isoformat()
        return doc


class StudentLogin(BaseModel):
    RegNo: int = Field(gt=0)
    dob: date


class StaffLogin(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class TestConfig(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(ge=1, le=600)
    opens_at: Optional[datetime] = None
    closes_at: Optional[datetime] = None
    published: bool = False
    eval_mode: Literal["manual", "immediate", "scheduled", "after_close"] = "manual"
    eval_at: Optional[datetime] = None
    eval_delay_minutes: int = Field(default=0, ge=0, le=7 * 24 * 60)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title must not be blank")
        return v

    @field_validator("opens_at", "closes_at", "eval_at")
    @classmethod
    def to_naive_utc(cls, v):
        if v is not None and v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v

    @model_validator(mode="after")
    def window_order(self):
        if self.opens_at and self.closes_at and self.closes_at <= self.opens_at:
            raise ValueError("Closing time must be after opening time")
        if self.eval_mode == "scheduled" and not self.eval_at:
            raise ValueError("Choose when evaluation should start")
        if self.eval_mode == "after_close" and not self.closes_at:
            raise ValueError("Set a closing time to start evaluation after the test closes")
        return self


class TestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(default=60, ge=1, le=600)
    copy_from: Optional[str] = Field(default=None, max_length=40)  # copy the questions of another test

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title must not be blank")
        return v


class QuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    max_score: int = Field(default=10, ge=1, le=100)

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Question text must not be blank")
        return v


class AnswersPayload(BaseModel):
    pseudoCodeAnswers: Dict[str, str]
    final: bool = False

    @field_validator("pseudoCodeAnswers")
    @classmethod
    def validate_lengths(cls, v: Dict[str, str]) -> Dict[str, str]:
        max_chars = get_settings().max_answer_chars
        for key, value in v.items():
            if len(value) > max_chars:
                raise ValueError(f"answer for question {key} exceeds {max_chars} characters")
        return v
