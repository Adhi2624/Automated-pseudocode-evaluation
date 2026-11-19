import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Literal, Optional

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402
from pydantic import BaseModel, EmailStr, Field, field_validator  # noqa: E402
from pymongo import ASCENDING  # noqa: E402
from pymongo.collection import Collection  # noqa: E402
from pymongo.errors import DuplicateKeyError, PyMongoError  # noqa: E402

from common.answers import flatten_answers  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.db import get_client  # noqa: E402
from common.questions import load_questions  # noqa: E402

settings = get_settings()
QUESTIONS = load_questions()

BRANCHES = ["ADS", "AIML", "BME", "CIVIL", "CSE", "CSD", "ECE", "EEE", "FT", "IT", "MCA", "MCT", "MECH"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = get_client(settings)
    app.state.client = client
    app.state.collection = client[settings.mongo_db][settings.mongo_collection]
    try:
        app.state.collection.create_index([("RegNo", ASCENDING)], unique=True)
    except PyMongoError:
        # DB down at startup: requests will return 503 until it is reachable.
        pass
    try:
        yield
    finally:
        client.close()


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)


def get_collection(request: Request) -> Collection:
    """Dependency providing the users collection (override in tests)."""
    return request.app.state.collection


@app.exception_handler(PyMongoError)
async def mongo_error_handler(request: Request, exc: PyMongoError):
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


class FormDetails(BaseModel):
    Name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    MobNo: str = Field(pattern=r"^[0-9]{10}$")
    RegNo: int = Field(gt=0)
    year: int = Field(ge=1, le=3)
    Branch: Literal[tuple(BRANCHES)]
    Sec: Literal["A", "B", "C", "D"]

    @field_validator("Name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name must not be blank")
        return v


class AnswersPayload(BaseModel):
    pseudoCodeAnswers: Dict[str, str]

    @field_validator("pseudoCodeAnswers")
    @classmethod
    def validate_answers(cls, v: Dict[str, str]) -> Dict[str, str]:
        for key, value in v.items():
            if not key.isdigit() or int(key) not in QUESTIONS:
                raise ValueError(f"invalid question id: {key}")
            if len(value) > settings.max_answer_chars:
                raise ValueError(
                    f"answer for question {key} exceeds {settings.max_answer_chars} characters"
                )
        return v


class UserResponse(BaseModel):
    id: str
    Name: str
    email: str
    MobNo: str
    RegNo: int
    year: int
    Branch: str
    Sec: str
    pseudoCodeAnswers: Optional[Dict[str, str]] = None


def serialize_user(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    if doc.get("pseudoCodeAnswers") is not None:
        doc["pseudoCodeAnswers"] = flatten_answers(doc["pseudoCodeAnswers"])
    return doc


@app.get("/")
async def welcome(request: Request):
    return templates.TemplateResponse("welcome.html", {"request": request})


@app.get("/continue")
async def continue_to_website():
    return RedirectResponse(url="/details", status_code=303)


@app.get("/details")
async def details(request: Request):
    return templates.TemplateResponse("details1.html", {"request": request})


@app.get("/continue1")
async def continue_to_pseudo():
    return RedirectResponse(url="/pseudo", status_code=303)


@app.get("/pseudo", response_class=HTMLResponse)
async def pseudo(request: Request):
    return templates.TemplateResponse("pseudo.html", {"request": request})


@app.get("/submit1")
async def continue_to_thank():
    return RedirectResponse(url="/thank", status_code=303)


@app.get("/thank", response_class=HTMLResponse)
async def thank(request: Request):
    return templates.TemplateResponse("thank.html", {"request": request})


@app.get("/api/questions")
def list_questions() -> List[dict]:
    return [{"id": q["id"], "text": q["text"]} for q in QUESTIONS.values()]


@app.post("/submit")
def submit_form(details: FormDetails, collection: Collection = Depends(get_collection)):
    try:
        result = collection.insert_one(details.model_dump())
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="Register number already exists.")
    return {"message": "Details stored successfully!", "id": str(result.inserted_id)}


@app.get("/get-user-details/{reg_no}", response_model=UserResponse)
def get_user_details(reg_no: int, collection: Collection = Depends(get_collection)):
    user = collection.find_one({"RegNo": reg_no})
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return serialize_user(user)


@app.put("/submit-answers/{reg_no}")
def submit_answers(
    reg_no: int,
    payload: AnswersPayload,
    collection: Collection = Depends(get_collection),
):
    result = collection.update_one(
        {"RegNo": reg_no},
        {"$set": {"pseudoCodeAnswers": payload.pseudoCodeAnswers}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"message": "Answers updated successfully!"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
