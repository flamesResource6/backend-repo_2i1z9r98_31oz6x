import os
from datetime import date, datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import User, JobGroup, Attendance, SafetyDocument, Payment

app = FastAPI(title="Brian Crafts – Attendance & Safety API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------
# Utility functions
# -----------------

COL_USERS = "user"
COL_JOB_GROUPS = "jobgroup"
COL_ATTENDANCE = "attendance"
COL_SAFETY_DOCS = "safetydocument"
COL_PAYMENTS = "payment"


class RBACUser(BaseModel):
    id: str
    role: str
    team_lead_id: Optional[str] = None


def get_current_user() -> RBACUser:
    # Simplified auth stub for demo; replace with real auth later
    # Read from headers in a real implementation
    return RBACUser(id="demo-admin", role="admin")


# -----------------
# Health route
# -----------------
@app.get("/")
def read_root():
    return {"message": "Brian Crafts API running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# -----------------
# RBAC helpers
# -----------------

def require_role(user: RBACUser, roles: List[str]):
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


# -----------------
# Job Groups
# -----------------
@app.post("/job-groups", response_model=dict)
def create_job_group(payload: JobGroup, user: RBACUser = Depends(get_current_user)):
    require_role(user, ["admin"])  # only admin
    _id = create_document(COL_JOB_GROUPS, payload)
    return {"id": _id}


@app.get("/job-groups", response_model=List[dict])
def list_job_groups(user: RBACUser = Depends(get_current_user)):
    docs = get_documents(COL_JOB_GROUPS)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs


# -----------------
# Users (Team Management)
# -----------------
@app.post("/users", response_model=dict)
def create_user(payload: User, user: RBACUser = Depends(get_current_user)):
    require_role(user, ["admin"])  # only admin can add users
    _id = create_document(COL_USERS, payload)
    return {"id": _id}


@app.get("/users", response_model=List[dict])
def list_users(user: RBACUser = Depends(get_current_user)):
    # Admin sees all. Team lead would be filtered to their team in a full implementation.
    docs = get_documents(COL_USERS)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs


# -----------------
# Safety Documents
# -----------------
@app.post("/safety-docs", response_model=dict)
def create_safety_doc(payload: SafetyDocument, user: RBACUser = Depends(get_current_user)):
    require_role(user, ["admin", "team_lead"])  # admins and team leads
    _id = create_document(COL_SAFETY_DOCS, payload)
    return {"id": _id}


@app.get("/safety-docs/today", response_model=Optional[dict])
def get_today_safety_doc(user: RBACUser = Depends(get_current_user)):
    docs = list(db[COL_SAFETY_DOCS].find({"date": date.today()}))
    if not docs:
        return None
    d = docs[0]
    d["id"] = str(d.pop("_id"))
    return d


# -----------------
# Attendance
# -----------------
class SignPayload(BaseModel):
    user_id: str
    signature_url: Optional[str] = None
    device_meta: Optional[dict] = None
    location: Optional[dict] = None


@app.post("/attendance/sign", response_model=dict)
def sign_attendance(payload: SignPayload, user: RBACUser = Depends(get_current_user)):
    # members sign themselves; admins/leads can also sign on behalf if needed
    att = Attendance(
        user_id=payload.user_id,
        date=date.today(),
        signed=True,
        signature_url=payload.signature_url,
        timestamp=datetime.utcnow(),
        device_meta=payload.device_meta,
        location=payload.location,
    )
    _id = create_document(COL_ATTENDANCE, att)
    return {"id": _id}


class ApprovePayload(BaseModel):
    attendance_id: str
    remarks: Optional[str] = None
    incident_flag: Optional[bool] = False


@app.post("/attendance/approve", response_model=dict)
def approve_attendance(payload: ApprovePayload, user: RBACUser = Depends(get_current_user)):
    require_role(user, ["admin", "team_lead"])  # approvers only
    from bson import ObjectId

    doc = db[COL_ATTENDANCE].find_one({"_id": ObjectId(payload.attendance_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Attendance not found")
    if doc.get("approved_by"):
        raise HTTPException(status_code=400, detail="Already approved")

    db[COL_ATTENDANCE].update_one(
        {"_id": ObjectId(payload.attendance_id)},
        {"$set": {
            "approved_by": user.id,
            "approved_at": datetime.utcnow(),
            "remarks": payload.remarks,
            "incident_flag": bool(payload.incident_flag),
        }}
    )
    return {"status": "ok"}


@app.get("/attendance/today", response_model=List[dict])
def list_today_attendance(user: RBACUser = Depends(get_current_user)):
    docs = list(db[COL_ATTENDANCE].find({"date": date.today()}))
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs


# -----------------
# Timesheets & Reports
# -----------------
@app.get("/reports/individual/{user_id}", response_model=dict)
def individual_report(user_id: str, user: RBACUser = Depends(get_current_user)):
    # RBAC: members can only see their own; leads/admin can see anyone
    if user.role == "member" and user.id != user_id:
        raise HTTPException(status_code=403, detail="Cannot access another member's report")

    # Aggregate attendance
    present = db[COL_ATTENDANCE].count_documents({"user_id": user_id, "signed": True})
    # naive absence calc: total days in records vs present
    total_days = db[COL_ATTENDANCE].distinct("date", {"user_id": user_id})
    absent = max(0, len(total_days) - present)

    # pay calc
    u = db[COL_USERS].find_one({"_id": {"$exists": True}, "_id": {"$exists": True}})
    # In real impl, fetch that specific user; here keep simple to avoid joins in this demo

    total_pay = 0.0
    # If we had the user's rate and present days, compute

    return {
        "user_id": user_id,
        "total_present": present,
        "total_absent": absent,
        "total_pay": total_pay,
    }


@app.get("/reports/team", response_model=dict)
def team_report(user: RBACUser = Depends(get_current_user)):
    require_role(user, ["admin", "team_lead"])  # only
    total_present = db[COL_ATTENDANCE].count_documents({"signed": True})
    by_group = {}
    # Summaries per job group (approximation for demo)
    for a in db[COL_ATTENDANCE].find({"signed": True}):
        uid = a.get("user_id")
        u = db[COL_USERS].find_one({"_id": {"$exists": True}, "_id": {"$exists": True}})
        # placeholder aggregation; real impl would join by user and group
    return {
        "total_present": total_present,
        "by_group": by_group,
    }


# -----------------
# Simple CSV export endpoints (demo)
# -----------------
@app.get("/export/attendance.csv")
def export_attendance_csv(user: RBACUser = Depends(get_current_user)):
    require_role(user, ["admin", "team_lead"])  # only
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "user_id", "date", "signed", "approved_by", "remarks", "incident_flag"])
    for d in db[COL_ATTENDANCE].find({}):
        writer.writerow([
            str(d.get("_id")), d.get("user_id"), d.get("date"), d.get("signed"),
            d.get("approved_by"), d.get("remarks"), d.get("incident_flag")
        ])
    return output.getvalue()


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
