"""
Database Schemas for Brian Crafts – Attendance & Safety Adherence App

Each Pydantic model corresponds to a MongoDB collection.
Collection name is the lowercase of the class name.

Collections:
- user
- jobgroup
- attendance
- safetydocument
- payment
"""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, EmailStr
from datetime import date, datetime

# RBAC roles
Role = Literal["admin", "team_lead", "member"]

class JobGroup(BaseModel):
    title: str = Field(..., description="Job group title, e.g., Technician")
    daily_rate: float = Field(..., ge=0, description="Base daily pay rate in KES")
    allowance: float = Field(0, ge=0, description="Optional special allowance in KES")

class User(BaseModel):
    name: str
    phone: str = Field(..., description="Phone number in international format")
    email: EmailStr
    role: Role = Field("member")
    job_group_id: Optional[str] = Field(None, description="Ref: jobgroup _id as string")
    daily_rate: Optional[float] = Field(None, ge=0, description="Overrides job group daily rate")
    status: Literal["active", "inactive"] = Field("active")
    team_lead_id: Optional[str] = Field(None, description="If member, who is their team lead")

class SafetyDocument(BaseModel):
    date: date
    content: str = Field(..., description="Safety guidelines text for the day")
    file_url: Optional[str] = Field(None, description="Optional file link")

class Attendance(BaseModel):
    user_id: str
    date: date
    signed: bool = False
    signature_url: Optional[str] = Field(None, description="Data URL of signature or file URL")
    timestamp: Optional[datetime] = None
    device_meta: Optional[dict] = None
    location: Optional[dict] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    remarks: Optional[str] = None
    incident_flag: bool = False

class Payment(BaseModel):
    user_id: str
    start_date: date
    end_date: date
    total_days: int = 0
    total_pay: float = 0.0
