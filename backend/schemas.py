from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


# Each model corresponds to a Mongo collection named by the lowercase class name

class JobGroup(BaseModel):
    name: str
    description: Optional[str] = None
    daily_rate: Optional[float] = None
    active: bool = True


class User(BaseModel):
    full_name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: str = Field(default="member", description="member|team_lead|admin")
    job_group_id: Optional[str] = None
    active: bool = True


class SafetyDocument(BaseModel):
    date: date
    title: str
    items: List[str] = []
    published: bool = True


class Attendance(BaseModel):
    user_id: str
    date: date
    signature_data: Optional[str] = None  # base64 PNG
    device_info: Optional[str] = None
    gps: Optional[dict] = None
    approved: bool = False
    approved_by: Optional[str] = None
    remarks: Optional[str] = None


class Payment(BaseModel):
    user_id: str
    date: date
    hours: float = 8
    rate: Optional[float] = None
    total: Optional[float] = None


class Notification(BaseModel):
    user_id: Optional[str] = None
    title: str
    body: str
    sent_at: Optional[datetime] = None
    read: bool = False


class Tokens(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    otp: str


class OTPRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
