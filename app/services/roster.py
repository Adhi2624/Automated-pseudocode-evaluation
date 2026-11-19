"""Parse a staff-uploaded student roster (CSV or Excel) into validated StudentIn rows."""
import csv
import io
import re
from datetime import date, datetime

from pydantic import ValidationError

from app.schemas import StudentIn

MAX_ROWS = 5000

# Accepted header spellings (lower-cased, non-alphanumerics removed) -> field name.
ALIASES = {
    "regno": "RegNo", "registernumber": "RegNo", "registerno": "RegNo", "rollno": "RegNo",
    "rollnumber": "RegNo", "roll": "RegNo", "registrationnumber": "RegNo", "regnumber": "RegNo",
    "name": "Name", "studentname": "Name", "fullname": "Name",
    "dob": "dob", "dateofbirth": "dob", "birthdate": "dob", "birthday": "dob",
    "email": "email", "emailid": "email", "mail": "email",
    "mobno": "MobNo", "mobile": "MobNo", "mobileno": "MobNo", "mobilenumber": "MobNo", "phone": "MobNo",
    "year": "year", "branch": "Branch", "department": "Branch", "dept": "Branch",
    "sec": "Sec", "section": "Sec",
}
REQUIRED = ("RegNo", "Name", "dob")


class RosterError(ValueError):
    """The file as a whole cannot be read (wrong type, missing columns, too large)."""


def _key(header) -> str:
    return re.sub(r"[^a-z0-9]", "", str(header or "").lower())


def parse_date(value):
    """date | datetime | 'YYYY-MM-DD' | 'DD-MM-YYYY' | 'DD/MM/YYYY' | 'DD.MM.YYYY' -> date (day first when ambiguous)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r} (use YYYY-MM-DD or DD-MM-YYYY)")


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():  # Excel stores numbers as floats
        value = int(value)
    text = str(value).strip()
    return text or None


def _read_csv(data: bytes):
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


def _read_xlsx(data: bytes):
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise RosterError("Could not read the Excel file. Is it a valid .xlsx?")
    try:
        return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    finally:
        wb.close()


def parse_roster(filename: str, data: bytes):
    """Return (students, errors). `students` are StudentIn; `errors` are 'Row N: message' strings."""
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        rows = _read_xlsx(data)
    elif name.endswith((".csv", ".txt", ".tsv")):
        rows = _read_csv(data)
    else:
        raise RosterError("Upload a .csv or .xlsx file.")
    rows = [r for r in rows if any(c not in (None, "") for c in r)]
    if len(rows) < 2:
        raise RosterError("The file has no student rows.")
    if len(rows) - 1 > MAX_ROWS:
        raise RosterError(f"Too many rows (limit {MAX_ROWS}).")

    columns = {}
    for idx, header in enumerate(rows[0]):
        field = ALIASES.get(_key(header))
        if field and field not in columns.values():
            columns[idx] = field
    missing = [f for f in REQUIRED if f not in columns.values()]
    if missing:
        raise RosterError("Missing column(s): " + ", ".join(missing) + ". Expected headers: RegNo, Name, DOB (optional: Email, Mobile, Year, Branch, Section).")

    students, errors, seen = [], [], set()
    for line, row in enumerate(rows[1:], start=2):
        raw = {field: _clean(row[idx]) if idx < len(row) else None for idx, field in columns.items()}
        try:
            if raw.get("dob") is None:
                raise ValueError("dob: missing")
            raw["dob"] = parse_date(row[next(i for i, f in columns.items() if f == "dob")])
            student = StudentIn(**{k: v for k, v in raw.items() if v is not None})
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg'].replace('Value error, ', '')}" for e in exc.errors())
            errors.append(f"Row {line}: {msg}")
            continue
        except ValueError as exc:
            errors.append(f"Row {line}: {exc}")
            continue
        if student.RegNo in seen:
            errors.append(f"Row {line}: duplicate RegNo {student.RegNo} in the file (skipped)")
            continue
        seen.add(student.RegNo)
        students.append(student)
    return students, errors
