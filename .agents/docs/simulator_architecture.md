# Enterprise IoT Simulator Architecture Reference

## The MQTT Messaging Protocol
We use a public, free MQTT broker for zero-installation overhead during university demos (e.g., `broker.emqx.io`).

**Topic Structure:**
`livesense/farm/{farm_id}/cow/{cow_id}/telemetry`

**Edge-to-Cloud JSON Payload:**
```json
{
  "device_id": "WASP-MAC-8F2A",
  "cow_id": "TAG-101",
  "farm_id": "FARM-A",
  "timestamp": "2026-09-03T10:30:00Z",
  "telemetry": {
    "x_mean": 0.05,
    "y_mean": 0.12,
    "z_mean": 9.81,
    "mobility": 14.5
  },
  "edge_inference": {
    "status": "SCM_DETECTED",
    "probability": 0.88,
    "model_version": "v1.ultra"
  }
}
```

## The Database Schema (SQLite)

### Table: `users`
- `id`: Primary Key
- `username`: String
- `farm_id`: String (Foreign Key linking to Farm)

### Table: `cows`
- `cow_id`: Primary Key
- `farm_id`: String
- `collar_id`: String (The hardware MAC address)
- `status`: String (Healthy / SCM_Risk)

### Table: `telemetry_events`
- `id`: Primary Key
- `cow_id`: String
- `timestamp`: DateTime
- `mobility_score`: Float
- `ai_prediction`: String
- `farmer_feedback`: String (Null / Confirmed / False_Alarm) -> Used for MLOps retraining.
