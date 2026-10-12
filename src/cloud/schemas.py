from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class CowBase(BaseModel):
    cow_id: str
    farm_id: str
    collar_id: str
    status: str

class CowResponse(CowBase):
    class Config:
        from_attributes = True

class CowCreate(BaseModel):
    cow_id: str
    collar_id: str

class TelemetryEventResponse(BaseModel):
    id: int
    cow_id: str
    timestamp: datetime
    mobility_score: float
    ai_prediction: str
    farmer_feedback: Optional[str] = None

    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    username: str
    password: str

class UserRegister(BaseModel):
    username: str
    password: str
    farm_id: Optional[str] = None

class TicketResponse(BaseModel):
    id: int
    cow_id: str
    event_id: int
    status: str
    action_plan: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class TicketResolveRequest(BaseModel):
    true_positive: bool

class ConsultationMessageCreate(BaseModel):
    message: str
    image_base64: Optional[str] = None

class ConsultationMessageResponse(BaseModel):
    id: int
    cow_id: str
    role: str
    message: str
    timestamp: datetime

    class Config:
        from_attributes = True
