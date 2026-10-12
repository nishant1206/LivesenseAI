---
name: simulator-workflow
description: >-
  Instructions for understanding, starting, and debugging the massive distributed Edge-IoT Data Simulator for LiveSense AI.
---

# LiveSense AI: Enterprise Distributed Simulator

This simulator mimics a massive fleet of WASP IoT neck collars communicating with a central Cloud Ingestion Engine over MQTT.

## Execution Strategy (The "Demo" Workflow)

To run this distributed system locally, we use a 3-Terminal execution strategy to prove the decoupling of the Edge and Cloud.

1. **Terminal 1: The Cloud Database & SaaS Backend**
   Starts the FastAPI Cloud SaaS backend which connects to a local SQLite database (for zero-setup demo purposes) and subscribes to the MQTT Broker to listen for edge events.
   ```cmd
   cd src/cloud
   uvicorn main:app --reload
   ```

2. **Terminal 2: The Edge Fleet**
   Runs the `mock_edge_fleet.py` script. This script spawns 50 asynchronous "Virtual Collars". Each virtual collar runs the `mastitis_ultra_model.pkl` inference locally (Edge AI) and publishes the results to the MQTT Broker.
   ```cmd
   cd src/edge
   python mock_edge_fleet.py
   ```

3. **Terminal 3: The Frontend (Optional)**
   If the React/SaaS platform is built as a separate Node project, it runs here. Otherwise, it is served by the Cloud Backend.

## Dependencies Required
- `paho-mqtt` (For the distributed IoT messaging)
- `SQLAlchemy` (For the SQLite database schema)
- `fastapi`, `uvicorn` (For the Cloud Server)
