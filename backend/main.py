import csv
import io
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from jose import JWTError, jwt
from passlib.context import CryptContext

from database import create_document, db, get_documents, get_one, update_document
from schemas import (
    Attendance,
    JobGroup,
    LoginRequest,
    OTPRequest,
    SafetyDocument,
    Tokens,
    User,
)

logger = logging.getLogger("api")
logging.basicConfig(level=logging.INFO)

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 12

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="Attendance & Safety API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Simple OTP store (in-memory for demo). In production, use Redis or provider like Supabase/Authy.
OTP_STORE: Dict[str, str] = {}


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str | None = None) -> Dict[str, Any]:
    # token comes via Authorization header Bearer <token> when used with dependencies below
    from fastapi import Request

    def _extract_token(req: Request) -> Optional[str]:
        auth = req.headers.get("authorization") or req.headers.get("Authorization")
        if not auth:
            return None
        parts = auth.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        return None

    # Use request context to get header if not directly provided
    try:
        from starlette.requests import Request as StarletteRequest
        req: StarletteRequest = StarletteRequest(scope={})  # placeholder not used
    except Exception:
        pass

    try:
        from fastapi import Request
        request: Request = Depends()  # will be overridden by FastAPI
    except Exception:
        request = None  # type: ignore

    # FastAPI pattern: define inner dependency to read header
    from fastapi import Header

    async def _token_from_header(authorization: str | None = Header(default=None)):
        if not authorization:
            return None
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        return None

    # decode token
    if token is None:
        # try nothing; in FastAPI route we'll provide token via dependency injection
        pass

    # We'll actually handle token decoding in a separate dependency below for clarity
    raise HTTPException(status_code=401, detail="Unauthorized")


def decode_token_dependency(authorization: str | None = None) -> Dict[str, Any]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = parts[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_role(*roles: str):
    def _inner(payload: Dict[str, Any] = Depends(decode_token_dependency)):
        user_role = payload.get("role")
        if not user_role or user_role not in roles:
            raise HTTPException(status_code=403, detail="Forbidden: insufficient role")
        return payload

    return _inner


@app.get("/")
async def health():
    return {"ok": True, "service": "api", "time": datetime.utcnow().isoformat()}


@app.get("/test")
async def test_db():
    try:
        # quick roundtrip
        db.list_collection_names()
        return {"ok": True, "db": "connected"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


# OTP endpoints (email or phone). For demo, we generate a static 6-digit code and log it.
@app.post("/auth/otp")
async def request_otp(req: OTPRequest):
    if not req.email and not req.phone:
        raise HTTPException(400, "Provide email or phone")
    identifier = (req.email or req.phone).lower() if req.email else req.phone
    code = "123456"  # demo static
    OTP_STORE[identifier] = code
    logger.info("OTP for %s is %s", identifier, code)
    return {"sent": True}


@app.post("/auth/login", response_model=Tokens)
async def login(req: LoginRequest):
    identifier = (req.email or req.phone)
    if not identifier:
        raise HTTPException(400, "Missing identifier")
    expected = OTP_STORE.get(identifier.lower() if req.email else identifier)
    if not expected or req.otp != expected:
        raise HTTPException(401, "Invalid OTP")
    # find or create user by email/phone
    filter_q: Dict[str, Any] = {}
    if req.email:
        filter_q = {"email": req.email}
    else:
        filter_q = {"phone": req.phone}
    user = get_one("user", filter_q)
    if not user:
        # auto-provision minimal member
        user = create_document("user", {"full_name": identifier, **filter_q, "role": "member", "active": True})
    token = create_access_token({"sub": user.get("_id"), "role": user.get("role"), "name": user.get("full_name")})
    return Tokens(access_token=token)


# Job Groups
@app.post("/job-groups", dependencies=[Depends(require_role("admin"))])
async def create_job_group(payload: Dict[str, Any], _=Depends(decode_token_dependency)):
    job = JobGroup(**payload)
    doc = create_document("jobgroup", job.model_dump())
    return doc


@app.get("/job-groups", dependencies=[Depends(require_role("admin", "team_lead"))])
async def list_job_groups():
    return get_documents("jobgroup")


# Users
@app.post("/users", dependencies=[Depends(require_role("admin"))])
async def create_user(payload: Dict[str, Any]):
    user = User(**payload)
    doc = create_document("user", user.model_dump())
    return doc


@app.get("/users", dependencies=[Depends(require_role("admin", "team_lead"))])
async def list_users():
    return get_documents("user")


# Safety Documents
@app.post("/safety-docs", dependencies=[Depends(require_role("admin", "team_lead"))])
async def create_safety_doc(payload: Dict[str, Any]):
    doc = SafetyDocument(**payload)
    return create_document("safetydocument", doc.model_dump())


@app.get("/safety-docs/today")
async def get_today_doc():
    today = date.today().isoformat()
    docs = get_documents("safetydocument", {"date": date.today()}, limit=1, sort=[["created_at", -1]])
    return docs[0] if docs else None


# Attendance
@app.post("/attendance/sign", dependencies=[Depends(require_role("member", "team_lead", "admin"))])
async def sign_attendance(payload: Dict[str, Any], user=Depends(decode_token_dependency)):
    # enforce one per user per day
    uid = user.get("sub")
    today = date.today()
    existing = get_one("attendance", {"user_id": uid, "date": today})
    if existing:
        raise HTTPException(400, "Already signed today")
    att = Attendance(**{**payload, "user_id": uid, "date": today})
    return create_document("attendance", att.model_dump())


@app.post("/attendance/approve", dependencies=[Depends(require_role("team_lead", "admin"))])
async def approve_attendance(payload: Dict[str, Any], approver=Depends(decode_token_dependency)):
    att_id = payload.get("attendance_id")
    if not att_id:
        raise HTTPException(400, "attendance_id required")
    # mark approved by approver sub
    modified = update_document("attendance", {"_id": {"$eq": att_id}}, {"$set": {"approved": True, "approved_by": approver.get("sub")}})
    if not modified:
        raise HTTPException(404, "attendance not found")
    return {"approved": True}


@app.get("/attendance/today", dependencies=[Depends(require_role("team_lead", "admin"))])
async def list_today_attendance():
    today = date.today()
    return get_documents("attendance", {"date": today})


# Reports
@app.get("/reports/individual/{user_id}", dependencies=[Depends(require_role("team_lead", "admin"))])
async def report_individual(user_id: str, start: Optional[str] = None, end: Optional[str] = None):
    q: Dict[str, Any] = {"user_id": user_id}
    if start:
        q.setdefault("date", {})["$gte"] = date.fromisoformat(start)
    if end:
        q.setdefault("date", {})["$lte"] = date.fromisoformat(end)
    return get_documents("attendance", q)


@app.get("/reports/team", dependencies=[Depends(require_role("team_lead", "admin"))])
async def report_team(start: Optional[str] = None, end: Optional[str] = None):
    q: Dict[str, Any] = {}
    if start:
        q.setdefault("date", {})["$gte"] = date.fromisoformat(start)
    if end:
        q.setdefault("date", {})["$lte"] = date.fromisoformat(end)
    return get_documents("attendance", q)


@app.get("/export/attendance.csv", dependencies=[Depends(require_role("team_lead", "admin"))])
async def export_attendance_csv():
    rows = get_documents("attendance")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["_id", "user_id", "date", "approved", "approved_by"])
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "_id": r.get("_id"),
            "user_id": r.get("user_id"),
            "date": r.get("date").isoformat() if isinstance(r.get("date"), date) else r.get("date"),
            "approved": r.get("approved"),
            "approved_by": r.get("approved_by"),
        })
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=attendance.csv"})


# Advanced exports: Excel and PDF
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


@app.get("/export/attendance.xlsx", dependencies=[Depends(require_role("team_lead", "admin"))])
async def export_attendance_xlsx():
    rows = get_documents("attendance")
    # normalize date
    for r in rows:
        if isinstance(r.get("date"), date):
            r["date"] = r["date"].isoformat()
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Attendance")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=attendance.xlsx"})


@app.get("/export/attendance.pdf", dependencies=[Depends(require_role("team_lead", "admin"))])
async def export_attendance_pdf():
    rows = get_documents("attendance")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter
    y = height - 50
    c.setFont("Helvetica", 12)
    c.drawString(50, y, "Attendance Report")
    y -= 30
    for r in rows[:40]:
        line = f"{r.get('_id')} | {r.get('user_id')} | {r.get('date')} | approved={r.get('approved')}"
        c.drawString(50, y, line)
        y -= 18
        if y < 50:
            c.showPage()
            y = height - 50
    c.save()
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=attendance.pdf"})
