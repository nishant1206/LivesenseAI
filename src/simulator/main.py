import asyncio
import json
import numpy as np
import joblib
import os
import random
from datetime import datetime
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="LiveSense AI Simulator")

# Adjust paths to correctly locate files from src/simulator
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_FILE = os.path.join(BASE_DIR, "data", "processed", "processed_data", "hourly_windows", "X.npy")
MODEL_FILE = os.path.join(BASE_DIR, "models", "mastitis_ultra_model.pkl")

# Mount Static Files for Frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/dashboard", StaticFiles(directory=static_dir, html=True), name="static")

# Load Data and Model
print(f"Loading data from {DATA_FILE}...")
try:
    X_raw = np.load(DATA_FILE)
    print(f"Data loaded. Shape: {X_raw.shape}")
except Exception as e:
    print(f"Error loading data: {e}")
    # Mock data if file doesn't exist to prevent crash during demo
    X_raw = np.random.rand(100, 168, 4)

print(f"Loading model from {MODEL_FILE}...")
class StackingEnsemble:
    def __init__(self):
        self.xgb = xgb.XGBClassifier(
            n_estimators=300, 
            max_depth=5, 
            learning_rate=0.03, 
            scale_pos_weight=25,
            eval_metric='logloss',
            random_state=42
        )
        self.rf = RandomForestClassifier(
            n_estimators=300, 
            max_depth=10, 
            class_weight='balanced_subsample', 
            random_state=42
        )
        self.meta = LogisticRegression(class_weight='balanced')
        self.scaler = StandardScaler()

    def fit(self, X, y):
        self.scaler.fit(X)
        Xs = self.scaler.transform(X)
        
        self.xgb.fit(X, y)
        self.rf.fit(X, y)
        
        p1 = self.xgb.predict_proba(X)[:, 1]
        p2 = self.rf.predict_proba(X)[:, 1]
        
        self.meta.fit(np.column_stack((p1, p2)), y)

    def predict_proba(self, X):
        Xs = self.scaler.transform(X)
        p1 = self.xgb.predict_proba(X)[:, 1]
        p2 = self.rf.predict_proba(X)[:, 1]
        return self.meta.predict_proba(np.column_stack((p1, p2)))[:, 1]

try:
    import __main__
    __main__.StackingEnsemble = StackingEnsemble
    model = joblib.load(MODEL_FILE)
    print("Model loaded successfully.")
except Exception as e:
    print(f"Error loading model: {e}")
    model = None

def extract_features_single(X_single):
    """
    Extracts features for a single sample.
    X_single shape: (1, 168, 4)
    """
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

@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Client connected to stream.")
    
    num_samples = X_raw.shape[0]
    
    try:
        while True:
            # Pick a random cow/sample to simulate streaming
            sample_idx = random.randint(0, num_samples - 1)
            cow_id = f"TAG-{1000 + sample_idx}"
            
            # Extract current data
            X_single = X_raw[sample_idx:sample_idx+1] # Shape: (1, 168, 4)
            
            # Extract features for prediction
            features = extract_features_single(X_single)
            
            # Predict
            prob = 0.0
            if model:
                prob = float(model.predict_proba(features)[0])
            else:
                # Mock probability if model failed to load
                prob = random.random() * 0.3
            
            # Determine status based on strict threshold from research
            threshold = 0.20
            status = "SCM DETECTED" if prob >= threshold else "HEALTHY"
            
            # Calculate simple metrics to send to UI
            x_mean = float(np.mean(X_single[0, :, 0]))
            y_mean = float(np.mean(X_single[0, :, 1]))
            z_mean = float(np.mean(X_single[0, :, 2]))
            mobility = float(np.sum(np.abs(np.diff(X_single[0], axis=0))))
            
            payload = {
                "cow_id": cow_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "raw_data": {
                    "x_mean": round(x_mean, 4),
                    "y_mean": round(y_mean, 4),
                    "z_mean": round(z_mean, 4),
                    "mobility": round(mobility, 2)
                },
                "prediction": {
                    "status": status,
                    "probability": round(prob, 4)
                }
            }
            
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(2.0) # Tick every 2 seconds
            
    except WebSocketDisconnect:
        print("Client disconnected.")
    except Exception as e:
        print(f"WebSocket error: {e}")
