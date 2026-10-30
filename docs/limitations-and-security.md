# Limitations, honesty constraints and security

## What is implemented vs. not

| Capability | State |
|---|---|
| Interactive 3D digital twin (procedural bridge, selection, layers, markers, focus) | Implemented |
| Asset/component/device registries, defect registry, alerts, history, reports | Implemented, database-backed |
| Image upload, validation, storage, quality heuristics | Implemented |
| AI crack classification | **Interface + ONNX runtime implemented; no trained model is shipped.** Uploads report `model_unavailable` until a model is installed. |
| Training / evaluation pipeline | `backend/ml/` — evaluation tooling tested; training script verified only on a tiny synthetic smoke dataset (see `backend/ml/README.md`), not on a real dataset in this environment |
| Detection / segmentation / corrosion / exposed-rebar models | Interfaces and categories only; no models |
| Sensor ingestion, validation, features, baselines, anomaly rules | Implemented; exercised with simulated and uploaded data only |
| ESP32 + MPU6050 + DHT MQTT firmware | Written for this project, syntax-checked and payload-verified on the host; **not yet flashed to hardware** |
| MQTT bridge | Implemented, tested with a real Mosquitto broker; broker auth is configured in Mosquitto (anonymous by default on a LAN) |
| Temperature / humidity | Implemented as exposure context and configurable alerts — **cannot detect cracks** |
| Webcam agent (live preview, frame analysis, event clips) | Implemented and tested with a video file; detections require an installed model |
| Uploaded GLB models | Implemented for self-contained .glb without Draco/meshopt compression |
| Image registration for before/after comparison | Not implemented — comparisons are explicitly side-by-side, unregistered |
| Precise 3D localisation from images | Not implemented — camera-ray→bounding-box projection is labelled low/medium confidence |
| Photogrammetry / survey localisation | Interface values only |
| Calibrated model-to-world transform | Data model only; demo asset has none |
| Map view | Requires `VITE_MAP_TILE_URL` and assets with coordinates |
| Remaining useful life | Interface only; always returns "RUL prediction unavailable: insufficient validated data." |
| User authentication / authorization | **Not implemented** (single-user local build) |

## Review priority is not structural severity

Priority levels (Unassessed, Low, Medium, High, Critical review) are produced by documented rules
(`backend/app/services/priority.py`). The default category levels are placeholders that the
responsible engineer must review in Settings. No default physical thresholds (e.g. crack width) are
shipped. Model confidence never raises priority.

## Demonstration data

The demo bridge, its images (watermarked "SYNTHETIC DEMO IMAGE"), its findings (entered as manual
demo findings) and its sensor data (simulation provider) are fictional and labelled throughout the UI,
API and reports. To start without demo data set `SS_SEED_DEMO_DATA=false` before the first start
(or delete `backend/data/`).

## Security

Implemented:
* Upload validation by decoding the file (not by extension), type allow-list, size and pixel limits.
* Pydantic validation of every request body; ingestion payload range checks; per-request batch limit.
* Per-device ingestion tokens (random 256-bit, stored as SHA-256 hash, constant-time comparison, rotation) for HTTP, MQTT and the camera agent.
* MQTT payloads flagged as simulated are refused; real ingestion into simulated devices is refused.
* Wi-Fi credentials and tokens live in the git-ignored `firmware/**/secrets.h`.
* Secrets via environment variables (`backend/.env`, git-ignored); `.env.example` contains no secrets.
* Storage keys are opaque and path-traversal checked; filesystem paths are never returned by the API.
* Audit trail for alert transitions, defect review changes, rule and settings changes (`event_log`, `alert_events`, `defect_events`).
* The dev servers bind to `127.0.0.1` by default.

Planned / required before multi-user or network deployment:
* User authentication and role-based authorization (actor names are currently self-declared).
* HTTPS/TLS termination, CORS restricted to the deployed origin, rate limiting on ingestion.
* Device certificate or HMAC-signed payloads; replay protection beyond sequence numbers.
* Database backups, object storage with access control, antivirus scanning of uploads.
