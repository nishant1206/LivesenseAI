import asyncio
import json
import random
import datetime
import paho.mqtt.client as mqtt
import numpy as np
import pickle
import sys
import os

# Ensure we can import edge utilities
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.edge.model_utils import inject_model_classes

MQTT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC = "livesense/farm/{farm_id}/cow/{cow_id}/telemetry"
FARM_ID = "FARM-A"

import joblib

# Load Data and Model
DATA_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../data/processed/processed_data/hourly_windows/X.npy'))
MODEL_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../models/mastitis_ultra_model.pkl'))

print("Initializing Edge Fleet...")
X_raw = np.load(DATA_PATH)
num_samples = X_raw.shape[0]

inject_model_classes()
edge_model = joblib.load(MODEL_PATH)

# Mock feature extraction for the edge
def extract_features_single(X_single):
    mean = np.mean(X_single, axis=1)
    std = np.std(X_single, axis=1)
    max_val = np.max(X_single, axis=1)
    min_val = np.min(X_single, axis=1)
    q75 = np.percentile(X_single, 75, axis=1)
    q25 = np.percentile(X_single, 25, axis=1)
    iqr = q75 - q25
    diff = np.sum(np.abs(np.diff(X_single, axis=1)), axis=1)
    
    features = np.hstack([mean, std, max_val, min_val, iqr, diff])
    raw_flat = X_single.reshape(X_single.shape[0], -1)
    
    return np.hstack([features, raw_flat])

async def virtual_collar(cow_id: str, farm_id: str, mqtt_client: mqtt.Client):
    """Simulates a single physical IoT collar running Edge AI."""
    print(f"Collar {cow_id} (Farm: {farm_id}) initialized.")
    while True:
        # Simulate an hourly window inference loop (scaled down to a few seconds for demo)
        await asyncio.sleep(random.uniform(3.0, 7.0))
        
        # Grab a random sample from our dataset to simulate current readings
        sample_idx = random.randint(0, num_samples - 1)
        X_single = X_raw[sample_idx:sample_idx+1]
        
        # Edge Inference
        features = extract_features_single(X_single)
        prob = float(edge_model.predict_proba(features)[0])
        
        status = "SCM_DETECTED" if prob > 0.5 else "HEALTHY"
        
        # Calculate a mock 'mobility' score based on accelerometer std-dev
        mobility = float(np.mean(np.std(X_single[0][:, :3], axis=0))) * 10
        
        payload = {
            "device_id": f"WASP-MAC-{cow_id}",
            "cow_id": cow_id,
            "farm_id": farm_id,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "telemetry": {
                "x_mean": float(np.mean(X_single[0][:, 0])),
                "y_mean": float(np.mean(X_single[0][:, 1])),
                "z_mean": float(np.mean(X_single[0][:, 2])),
                "mobility": round(mobility, 2)
            },
            "edge_inference": {
                "status": status,
                "probability": round(float(prob), 4),
                "model_version": "v1.ultra"
            }
        }
        
        topic = f"livesense/farm/{farm_id}/cow/{cow_id}/telemetry"
        mqtt_client.publish(topic, json.dumps(payload))
        print(f"[EDGE -> CLOUD] {cow_id} published telemetry. Status: {status}")

async def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start() # Background thread for MQTT network traffic
    
    from src.cloud.database import SessionLocal
    from src.cloud.models import Cow
    
    active_cows = set()
    tasks = {}
    
    print("Listening for new registered cows in the database...")
    
    while True:
        try:
            db = SessionLocal()
            cows = db.query(Cow).all()
            db.close()
            
            current_cows = set((c.cow_id, c.farm_id) for c in cows)
            new_cows = current_cows - active_cows
            
            for cow_id, farm_id in new_cows:
                task = asyncio.create_task(virtual_collar(cow_id, farm_id, client))
                tasks[cow_id] = task
                active_cows.add((cow_id, farm_id))
                
        except Exception as e:
            print(f"Error querying database: {e}")
            
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
