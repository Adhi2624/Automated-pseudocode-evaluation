"""Staff API: the student roster (shared by all tests; students cannot self-register)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pymongo.collection import Collection

from app.dependencies import current_staff, get_attempts, get_collection
from app.schemas import StudentIn
from app.services.roster import RosterError, parse_roster

router = APIRouter(prefix="/api/staff")

MAX_UPLOAD_BYTES = 2_000_000


def _upsert(collection: Collection, student: StudentIn) -> bool:
    """Insert or update by RegNo (attempts are kept). Returns True when newly created."""
    res = collection.update_one({"RegNo": student.RegNo}, {"$set": student.to_doc()}, upsert=True)
    return res.upserted_id is not None


@router.get("/students")
def list_students(_: str = Depends(current_staff), collection: Collection = Depends(get_collection)):
    fields = ("RegNo", "Name", "Branch", "year", "Sec", "email", "MobNo")
    return [{k: u.get(k) for k in fields} for u in collection.find({}, {k: 1 for k in fields}).sort("RegNo", 1)]


@router.post("/students/upload")
async def upload_students(
    request: Request,
    _: str = Depends(current_staff),
    collection: Collection = Depends(get_collection),
):
    """Raw file body (.csv / .xlsx) with the file name in the X-Filename header."""
    if int(request.headers.get("content-length") or 0) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (2 MB limit).")
    data = await request.body()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (2 MB limit).")
    try:
        students, errors = parse_roster(request.headers.get("x-filename", ""), data)
    except RosterError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    created = updated = 0
    for student in students:
        if _upsert(collection, student):
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated, "skipped": len(errors), "errors": errors[:50]}


@router.post("/students", status_code=201)
def add_student(body: StudentIn, _: str = Depends(current_staff), collection: Collection = Depends(get_collection)):
    return {"created": _upsert(collection, body), "RegNo": body.RegNo}


@router.delete("/students/{reg_no}")
def delete_student(
    reg_no: int,
    _: str = Depends(current_staff),
    collection: Collection = Depends(get_collection),
    attempts: Collection = Depends(get_attempts),
):
    if collection.delete_one({"RegNo": reg_no}).deleted_count == 0:
        raise HTTPException(status_code=404, detail="Student not found.")
    attempts.delete_many({"RegNo": reg_no})
    return {"message": "Deleted."}
