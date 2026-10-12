from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from .database import Base
import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    farm_id = Column(String, index=True)

class Cow(Base):
    __tablename__ = "cows"

    cow_id = Column(String, primary_key=True, index=True)
    farm_id = Column(String, index=True)
    collar_id = Column(String, unique=True, index=True)
    status = Column(String, default="Healthy")  # Healthy, SCM_Risk

class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id = Column(Integer, primary_key=True, index=True)
    cow_id = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    mobility_score = Column(Float)
    ai_prediction = Column(String)  # e.g., "SCM_DETECTED", "HEALTHY"
    farmer_feedback = Column(String, nullable=True)  # Null, Confirmed, False_Alarm

class MedicalTicket(Base):
    __tablename__ = "medical_tickets"

    id = Column(Integer, primary_key=True, index=True)
    cow_id = Column(String, index=True)
    event_id = Column(Integer, ForeignKey("telemetry_events.id"))
    status = Column(String, default="OPEN")  # OPEN, RESOLVED_TRUE, RESOLVED_FALSE
    action_plan = Column(String, nullable=True)  # Agent's suggested action plan
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class ConsultationMessage(Base):
    __tablename__ = "consultation_messages"

    id = Column(Integer, primary_key=True, index=True)
    cow_id = Column(String, index=True)
    role = Column(String)  # 'user' or 'agent'
    message = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
