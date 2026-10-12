from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from . import models, schemas
from .database import engine, get_db

from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
import os
import uuid
from dotenv import load_dotenv
from google import genai
from google.genai import types
from typing import List
import json
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from passlib.context import CryptContext
import jwt

load_dotenv()

# Auto-create SQLite tables if they don't exist
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="LiveSense AI - Enterprise Cloud API")

# --- AUTHENTICATION SETUP ---
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super_secret_dev_key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week for demo

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

# --- WEBSOCKET MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict = {}

    async def connect(self, websocket: WebSocket, farm_id: str):
        await websocket.accept()
        if farm_id not in self.active_connections:
            self.active_connections[farm_id] = []
        self.active_connections[farm_id].append(websocket)

    def disconnect(self, websocket: WebSocket, farm_id: str):
        if farm_id in self.active_connections and websocket in self.active_connections[farm_id]:
            self.active_connections[farm_id].remove(websocket)
            if not self.active_connections[farm_id]:
                del self.active_connections[farm_id]

    async def broadcast_to_farm(self, farm_id: str, message: dict):
        if farm_id in self.active_connections:
            for connection in self.active_connections[farm_id]:
                try:
                    await connection.send_json(message)
                except:
                    pass

manager = ConnectionManager()

@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket, token: str, db: Session = Depends(get_db)):
    # Validate token to get farm_id
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        user = db.query(models.User).filter(models.User.username == username).first()
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except jwt.PyJWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    farm_id = user.farm_id
    await manager.connect(websocket, farm_id)
    try:
        while True:
            # Just keep connection open, we don't expect messages from client for now
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, farm_id)

@app.post("/api/internal/broadcast")
async def internal_broadcast(payload: dict, db: Session = Depends(get_db)):
    # This endpoint is called by the mqtt_worker to broadcast real-time updates to connected UI clients.
    if "cow_id" in payload:
        cow = db.query(models.Cow).filter(models.Cow.cow_id == payload["cow_id"]).first()
        if cow:
            await manager.broadcast_to_farm(cow.farm_id, payload)
    return {"status": "ok"}

def send_push_notification(cow_id, action_plan):
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = os.getenv("SMTP_PORT", 587)
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    farmer_email = os.getenv("FARMER_EMAIL", "farmer@example.com")
    
    print(f"[PUSH NOTIFICATION] Alerting {farmer_email} for Cow: {cow_id}")
    
    if not smtp_server or not smtp_user:
        print("[PUSH NOTIFICATION] SMTP credentials not configured. Skipping real email dispatch.")
        return
        
    try:
        msg = MIMEText(f"CRITICAL: SCM Detected for {cow_id}.\n\nAI ACTION PLAN:\n{action_plan}")
        msg["Subject"] = f"LiveSense AI Alert: SCM Detected - {cow_id}"
        msg["From"] = smtp_user
        msg["To"] = farmer_email
        
        with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print("[PUSH NOTIFICATION] Email sent successfully.")
    except Exception as e:
        print(f"[PUSH NOTIFICATION] Failed to send email: {e}")

@app.post("/api/internal/telemetry")
async def ingest_telemetry(payload: dict, db: Session = Depends(get_db)):
    try:
        print(f"[CLOUD INGESTION] Received data for Cow: {payload.get('cow_id')} - Status: {payload.get('edge_inference', {}).get('status')}")
        telemetry = payload.get("telemetry", {})
        inference = payload.get("edge_inference", {})
        
        new_event = models.TelemetryEvent(
            cow_id=payload.get("cow_id"),
            timestamp=datetime.fromisoformat(payload.get("timestamp").replace("Z", "+00:00")),
            mobility_score=telemetry.get("mobility", 0.0),
            ai_prediction=inference.get("status", "UNKNOWN")
        )
        
        db.add(new_event)
        db.commit()
        db.refresh(new_event)
        
        if new_event.ai_prediction == "SCM_DETECTED":
            existing_ticket = db.query(models.MedicalTicket).filter(
                models.MedicalTicket.cow_id == new_event.cow_id,
                models.MedicalTicket.status == "OPEN"
            ).first()
            if not existing_ticket:
                try:
                    client = genai.Client()
                    prompt = f"URGENT: SCM (Subclinical Mastitis) detected in {new_event.cow_id}. The cow's mobility score is {new_event.mobility_score}. Generate a concise 1-3 sentence action plan for the farmer."
                    response = client.models.generate_content(
                        model="gemini-3.5-flash",
                        contents=prompt
                    )
                    action_plan = response.text
                except Exception as e:
                    print(f"Gemini API Error: {e}")
                    action_plan = f"URGENT: SCM detected in {new_event.cow_id}. Isolate cow immediately and conduct a California Mastitis Test (CMT). Administer standard anti-inflammatory as per vet protocol."

                ticket = models.MedicalTicket(cow_id=new_event.cow_id, event_id=new_event.id, action_plan=action_plan)
                db.add(ticket)
                db.commit()
                print(f"[TICKET CREATED] Opened Medical Ticket for Cow: {new_event.cow_id} with Action Plan.")
                
                send_push_notification(new_event.cow_id, action_plan)
                
                cow = db.query(models.Cow).filter(models.Cow.cow_id == new_event.cow_id).first()
                if cow:
                    await manager.broadcast_to_farm(cow.farm_id, {"type": "TICKET_UPDATE", "cow_id": new_event.cow_id})
                
        cow = db.query(models.Cow).filter(models.Cow.cow_id == new_event.cow_id).first()
        if cow:
            await manager.broadcast_to_farm(cow.farm_id, {
                "type": "TELEMETRY_UPDATE",
                "cow_id": new_event.cow_id,
                "timestamp": new_event.timestamp.isoformat(),
                "mobility_score": new_event.mobility_score,
                "ai_prediction": new_event.ai_prediction
            })
        
        return {"status": "ok"}
    except Exception as e:
        print(f"Error processing message: {e}")
        return {"status": "error", "message": str(e)}

# Mount frontend
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
app.mount("/dashboard", StaticFiles(directory=frontend_dir, html=True), name="frontend")

@app.get("/")
def read_root():
    return RedirectResponse(url="/dashboard")

@app.post("/auth/register")
def register(user_data: schemas.UserRegister, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.username == user_data.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = get_password_hash(user_data.password)
    farm_id = user_data.farm_id or f"FARM-{uuid.uuid4().hex[:8].upper()}"
    
    new_user = models.User(username=user_data.username, password_hash=hashed_password, farm_id=farm_id)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User registered successfully", "farm_id": farm_id}

@app.post("/auth/login")
def login(user_data: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == user_data.username).first()
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "farm_id": user.farm_id}

@app.post("/api/cows", response_model=schemas.CowResponse)
def add_cow(cow_data: schemas.CowCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    existing = db.query(models.Cow).filter(models.Cow.cow_id == cow_data.cow_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Cow ID already exists")
    
    new_cow = models.Cow(
        cow_id=cow_data.cow_id,
        farm_id=current_user.farm_id,
        collar_id=cow_data.collar_id,
        status="Healthy"
    )
    db.add(new_cow)
    db.commit()
    db.refresh(new_cow)
    return new_cow

@app.get("/api/cows", response_model=list[schemas.CowResponse])
def get_herd(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    cows = db.query(models.Cow).filter(models.Cow.farm_id == current_user.farm_id).all()
    return cows

@app.get("/api/cows/{cow_id}/telemetry", response_model=list[schemas.TelemetryEventResponse])
def get_cow_telemetry(cow_id: str, limit: int = 100, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    cow = db.query(models.Cow).filter(models.Cow.cow_id == cow_id, models.Cow.farm_id == current_user.farm_id).first()
    if not cow:
        raise HTTPException(status_code=404, detail="Cow not found on this farm")
        
    events = db.query(models.TelemetryEvent).filter(
        models.TelemetryEvent.cow_id == cow_id
    ).order_by(models.TelemetryEvent.timestamp.desc()).limit(limit).all()
    return events

@app.get("/api/tickets", response_model=list[schemas.TicketResponse])
def get_tickets(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    tickets = db.query(models.MedicalTicket).join(models.Cow, models.MedicalTicket.cow_id == models.Cow.cow_id)\
                .filter(models.Cow.farm_id == current_user.farm_id, models.MedicalTicket.status == "OPEN").all()
    return tickets

@app.post("/api/tickets/{ticket_id}/resolve")
def resolve_ticket(ticket_id: int, resolve_data: schemas.TicketResolveRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    ticket = db.query(models.MedicalTicket).join(models.Cow, models.MedicalTicket.cow_id == models.Cow.cow_id)\
                .filter(models.MedicalTicket.id == ticket_id, models.Cow.farm_id == current_user.farm_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    ticket.status = "RESOLVED_TRUE" if resolve_data.true_positive else "RESOLVED_FALSE"
    
    event = db.query(models.TelemetryEvent).filter(models.TelemetryEvent.id == ticket.event_id).first()
    if event:
        event.farmer_feedback = "Confirmed" if resolve_data.true_positive else "False_Alarm"
        
    db.commit()
    return {"message": "Ticket resolved", "status": ticket.status}

@app.get("/api/cows/{cow_id}/chat_history", response_model=list[schemas.ConsultationMessageResponse])
def get_chat_history(cow_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    cow = db.query(models.Cow).filter(models.Cow.cow_id == cow_id, models.Cow.farm_id == current_user.farm_id).first()
    if not cow:
        raise HTTPException(status_code=404, detail="Cow not found on this farm")
        
    messages = db.query(models.ConsultationMessage).filter(models.ConsultationMessage.cow_id == cow_id).order_by(models.ConsultationMessage.timestamp.asc()).all()
    return messages

@app.post("/api/cows/{cow_id}/consult", response_model=schemas.ConsultationMessageResponse)
def consult_caretaker(cow_id: str, payload: schemas.ConsultationMessageCreate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    cow = db.query(models.Cow).filter(models.Cow.cow_id == cow_id, models.Cow.farm_id == current_user.farm_id).first()
    if not cow:
        raise HTTPException(status_code=404, detail="Cow not found on this farm")
        
    user_msg = models.ConsultationMessage(cow_id=cow_id, role="user", message=payload.message)
    db.add(user_msg)
    
    history = db.query(models.ConsultationMessage).filter(
        models.ConsultationMessage.cow_id == cow_id
    ).order_by(models.ConsultationMessage.timestamp.asc()).all()
    
    contents = []
    for msg in history:
        if msg.id is None:
            continue
        role = "user" if msg.role == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg.message)]))
        
    user_parts = [types.Part.from_text(text=payload.message)]
    
    if payload.image_base64:
        import base64
        if "," in payload.image_base64:
            mime_part, b64_data = payload.image_base64.split(",", 1)
            mime_type = mime_part.split(":")[1].split(";")[0]
        else:
            b64_data = payload.image_base64
            mime_type = "image/jpeg"
        
        try:
            image_bytes = base64.b64decode(b64_data)
            user_parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
        except Exception as e:
            print("Failed to decode image:", e)
            
    contents.append(types.Content(role="user", parts=user_parts))
    
    try:
        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=f"You are the AI Caretaker for a cow named {cow_id}. You are monitoring its telemetry in a dairy farm. Keep your responses practical, concise, and helpful to the farmer. If an image is provided, analyze the visual signs of mastitis or other conditions."
            )
        )
        ai_reply = response.text
    except Exception as e:
        ai_reply = f"[Mock Fallback - API Error]: {str(e)[:50]}... Isolation and vet consult recommended."
        
    agent_msg = models.ConsultationMessage(cow_id=cow_id, role="agent", message=ai_reply)
    db.add(agent_msg)
    db.commit()
    db.refresh(agent_msg)
    
    return agent_msg
