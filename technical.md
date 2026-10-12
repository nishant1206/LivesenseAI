# LiveSense AI: Technical Architecture

## 1. System Architecture Overview
LiveSense AI follows a distributed **Edge-to-Cloud** architecture, heavily utilizing the Internet of Things (IoT) and Edge ML paradigms. It is designed to be highly scalable, supporting multiple tenant farms simultaneously.

The architecture consists of four main pillars:
1. **Edge Tier (IoT Collars):** Python-based simulation of edge devices running local inference.
2. **Data Ingestion (MQTT Broker & Worker):** Asynchronous messaging queue for handling incoming telemetry.
3. **Cloud API (FastAPI):** The central nervous system providing REST endpoints and WebSocket servers.
4. **Frontend Dashboard:** A vanilla web client with a high-density, monochrome UI.

---

## 2. Technical Components In-Depth

### A. The Edge Tier (`mock_edge_fleet.py`)
This script simulates the physical hardware collars worn by the cows.
- **Edge AI / Local Inference:** Instead of streaming raw sensor data (like 3-axis accelerometer readings), the Edge loads a pre-trained Scikit-Learn machine learning model (`mastitis_ultra_model.pkl`). 
- **Execution Loop:** 
  1. It connects to the PostgreSQL database to discover all registered cows.
  2. For each cow, it spawns an asynchronous task.
  3. The task samples raw data (`X.npy`), extracts features (mean, std, max), and runs inference locally on the "collar".
  4. It publishes a JSON payload with the final prediction (`HEALTHY` or `SUSPECTED_MASTITIS`) via the **MQTT Protocol** over port 1883.

### B. Ingestion & Messaging (`mqtt_worker.py`)
- **MQTT Broker:** Uses Mosquitto (or a similar broker) to handle Pub/Sub messaging.
- **Worker Process:** A background Python daemon that subscribes to the topic wildcard `livesense/farm/+/cow/+/telemetry`.
- **Business Logic:** When a payload arrives:
  1. It persists the telemetry to the database.
  2. If the prediction is `SUSPECTED_MASTITIS`, it automatically generates a `MedicalTicket` in the database.
  3. It fires an HTTP POST request to the FastAPI server's internal webhook (`/internal/trigger_alert`) to notify connected web clients in real-time.

### C. Cloud API Backend (`main.py`)
Built with **FastAPI** and **SQLAlchemy**.
- **Authentication:** Implements stateless JWT (JSON Web Token) authentication. Passwords are hashed using `bcrypt` (via `passlib`).
- **Multi-Tenancy:** Data isolation is enforced at the query level. Every API route extracts the `farm_id` from the JWT and ensures users can only read/write `Cow` and `MedicalTicket` records belonging to their specific farm.
- **WebSockets:** Provides a `/ws/alerts/{farm_id}` endpoint. When the MQTT worker detects an anomaly, the FastAPI server pushes a JSON event down the WebSocket connection so the frontend updates instantly without polling.

### D. Database Schema (`models.py`)
Relational database using **PostgreSQL**.
- `Farm`: Represents the tenant/user. Stores credentials (hashed password).
- `Cow`: Belongs to a Farm. Stores static metadata (name, breed).
- `TelemetryEvent`: Time-series data linked to a Cow. Stores health status and raw metrics.
- `MedicalTicket`: Linked to a Cow. Acts as a case-management system for sick cows (Status: `OPEN`, `IN_PROGRESS`, `CLOSED`).

### E. Frontend Dashboard
- **Design System:** Strict monochrome, high-contrast, high-density enterprise UI. No rounded corners or gradients. Built with raw HTML/CSS/JS.
- **State Management:** Uses browser `localStorage` for JWT persistence.
- **Real-Time Integration:** Establishes a standard browser `WebSocket` connection to listen for incoming telemetry and alert tickets, rendering them directly into the DOM upon receipt.

### F. MLOps Pipeline (`retrain_pipeline.py`)
A simulated backend pipeline for continuous model improvement.
- Extracts historical telemetry from the data warehouse.
- Preprocesses data and retrains the `Pipeline` (StandardScaler + RandomForest/XGBoost).
- Calculates data drift (comparing baseline distributions to current data).
- Saves versioned models (e.g., `mastitis_v2.pkl`) to be deployed via OTA (Over-The-Air) updates to the Edge collars.

---

## 3. Data Flow Example (Sick Cow Scenario)
1. **Edge:** The collar reads sensor data, runs the local ML model, and predicts `SUSPECTED_MASTITIS`.
2. **MQTT:** Collar publishes: `{"status": "SUSPECTED_MASTITIS", "confidence": 0.92}` to `livesense/farm/FARM-A/cow/2001/telemetry`.
3. **Worker:** `mqtt_worker.py` consumes the message, writes to DB, creates a `MedicalTicket`, and sends a POST to `/internal/trigger_alert`.
4. **FastAPI:** Receives the internal trigger and broadcasts the alert over the active WebSocket for `FARM-A`.
5. **Frontend:** The farmer's dashboard receives the WebSocket message and instantly flashes a warning row on the screen.
