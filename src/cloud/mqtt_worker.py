import json
import paho.mqtt.client as mqtt
from datetime import datetime
import sys
import os
import requests
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
from google import genai

load_dotenv()

# Add the project root to sys.path so we can import src.cloud
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.cloud.database import SessionLocal
from src.cloud.models import TelemetryEvent, MedicalTicket

MQTT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC = "livesense/farm/+/cow/+/telemetry"

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

def on_connect(client, userdata, flags, rc):
    print(f"Cloud Ingestion Worker connected with result code {rc}")
    client.subscribe(MQTT_TOPIC)
    print(f"Subscribed to topic: {MQTT_TOPIC}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        print(f"[CLOUD INGESTION] Received data for Cow: {payload.get('cow_id')} - Status: {payload.get('edge_inference', {}).get('status')}")
        
        # Save to database
        db = SessionLocal()
        
        telemetry = payload.get("telemetry", {})
        inference = payload.get("edge_inference", {})
        
        new_event = TelemetryEvent(
            cow_id=payload.get("cow_id"),
            timestamp=datetime.fromisoformat(payload.get("timestamp").replace("Z", "+00:00")),
            mobility_score=telemetry.get("mobility", 0.0),
            ai_prediction=inference.get("status", "UNKNOWN")
        )
        
        db.add(new_event)
        db.commit()
        db.refresh(new_event)
        
        # Auto-create a medical ticket if SCM is detected and no open ticket exists
        if new_event.ai_prediction == "SCM_DETECTED":
            existing_ticket = db.query(MedicalTicket).filter(
                MedicalTicket.cow_id == new_event.cow_id,
                MedicalTicket.status == "OPEN"
            ).first()
            if not existing_ticket:
                # Generate AI Action Plan via Gemini
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

                ticket = MedicalTicket(cow_id=new_event.cow_id, event_id=new_event.id, action_plan=action_plan)
                db.add(ticket)
                db.commit()
                print(f"[TICKET CREATED] Opened Medical Ticket for Cow: {new_event.cow_id} with Action Plan.")
                
                # Dispatch Push Notification
                send_push_notification(new_event.cow_id, action_plan)
                
                # Broadcast ticket update
                try:
                    requests.post("http://localhost:8000/api/internal/broadcast", json={
                        "type": "TICKET_UPDATE",
                        "cow_id": new_event.cow_id
                    })
                except:
                    pass
                
        # Broadcast telemetry update
        try:
            requests.post("http://localhost:8000/api/internal/broadcast", json={
                "type": "TELEMETRY_UPDATE",
                "cow_id": new_event.cow_id,
                "timestamp": new_event.timestamp.isoformat(),
                "mobility_score": new_event.mobility_score,
                "ai_prediction": new_event.ai_prediction
            })
        except:
            pass
            
        db.close()
    except Exception as e:
        print(f"Error processing message: {e}")

if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    client.on_connect = on_connect
    client.on_message = on_message

    print("Connecting to public MQTT broker...")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)

    # Blocking call that processes network traffic, dispatches callbacks and handles reconnecting.
    client.loop_forever()
