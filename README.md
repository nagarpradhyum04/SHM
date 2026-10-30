# StructuraSense AI

AI-ready structural-health-monitoring platform built around an interactive **3D digital twin** of a
civil-infrastructure asset. Engineers can explore a bridge component by component, see where cameras
and sensors are installed, inspect findings with their evidence, trace alerts to the observations that
raised them, review history and generate PDF inspection reports.

The first release is fully usable **without physical IoT hardware**: it works with uploaded images,
uploaded sensor history and a clearly labelled simulation provider, and exposes versioned, validated
interfaces for ESP32 + MPU6050 sensors and future cameras.

> **Honesty constraints.** No trained AI model, real sensor data or real structure is included. The
> demonstration bridge is procedural; its images are synthetic and watermarked; its sensor data is
> simulated; all of it is labelled as such in the UI, API and reports. Review priorities are rule-based
> and configurable — they are **not** certified structural assessments. No remaining-useful-life
> prediction is made. See [docs/limitations-and-security.md](docs/limitations-and-security.md).

## Quick start

Requirements: Python 3.11+ (tested with 3.12), Node.js 20+ (tested with 22).

```bash
./scripts/dev.sh
```

This creates `backend/.venv`, installs dependencies, starts the API on http://127.0.0.1:8000 and the
web app on http://127.0.0.1:5173 (open this one). On first start the database is migrated and the
demonstration bridge is seeded (~15 s). API docs: http://127.0.0.1:8000/docs.

Manual start:

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

Start with an empty database instead of the demo: set `SS_SEED_DEMO_DATA=false` in `backend/.env`
and delete `backend/data/`.

## Connecting your hardware

* **ESP32 + MPU6050 + DHT22 → MQTT:** run Mosquitto on the laptop, register a *Sensor node*, flash
  `firmware/esp32_mqtt_node/` (fill in `secrets.h`). Readings, vibration windows, temperature/humidity and
  alerts appear live; Settings → *IoT connection (MQTT)* shows every message and why any was rejected.
* **USB webcam:** register a *Camera*, run `python -m edge.camera_agent --device-id … --token …` in `backend/`.
  Frames are analysed by the installed model; findings keep the photo and a short clip. (Crack detection
  requires a trained model — none is shipped.)
* **Your own 3D model:** Infrastructure Assets → *Upload 3D model (.glb)*; named parts become components.
  Place devices from the Digital Twin with *Add device here* → *Edit placement* (pick on surface, aim cameras).

Step-by-step guide: [docs/hardware-integration.md](docs/hardware-integration.md).

## What you can do

| Section | Highlights |
|---|---|
| **Digital Twin** (default) | Orbit/pan/zoom, reset, fit, front/side/top/perspective views, smooth focus on components, devices and defects; click-to-select components; component tree with search; layer toggles (model, device markers, defect markers, boundaries, heatmap, wireframe, labels, historical findings, camera coverage); defect filters; surface-level vs component-level markers with approximate-location rings; pulsing markers for new findings (disabled by reduced motion); evidence panel; record findings by picking a point on the 3D surface; KPI strip from stored records; timeline of inspections, discoveries, anomalies and alerts |
| Infrastructure Assets | Asset registry (bridge, flyover, dam, building…), component registry, local-vs-geographic coordinates, optional Leaflet map (`VITE_MAP_TILE_URL`) |
| Inspections | Upload (type/size validated by decoding) or synthetic demo image → quality check → model inference if installed, else explicit *model unavailable*; history with filters; record findings from an image |
| Defect Registry | Filter by priority/status/category/component/detection/data source/date, sort, evidence with image region, model output, localisation method & confidence, priority rationale, review workflow and history, *Show in 3D* |
| Device Registry | Cameras, sensor nodes (acceleration + temperature/humidity) and sensors with 3D pose, data source, connection status, last MQTT status report; one-time ingestion tokens and rotation; placement editing in the twin |
| Sensor Analytics | Live readings, 60 s vibration features (mean/std/RMS/peak, completeness, duplicates, gaps), baselines, anomaly evaluation with recorded thresholds, simulation controls, CSV upload |
| Alerts Center | Rule-based alerts with deduplication, cooldowns, evidence links, acknowledge/assign/resolve/reopen and audit trail |
| Historical Analysis | Component inspection history, side-by-side (explicitly unregistered) comparison, status changes, repeated observations, vibration across windows and baseline changes, event log, RUL interface |
| Reports | PDF and print view: provenance warnings, summary, findings with evidence, vibration charts, alerts, devices, model/config versions, disclaimer |
| Settings & System Health | Data-source mode (real / uploaded / simulated / all, never merged), priority rules, alert rules, thresholds, model registry, reduced motion, backend/storage/model health, security status |

## Repository layout

```
backend/
  app/
    api/v1/        REST routers (assets, devices, sensors, inspections, defects, alerts, history, reports, system, SSE stream)
    services/      operations, imaging, inference/, priority, alert_engine, ingestion, vibration,
                   simulation, spatial, reports, rul, device_status, settings_store, storage, events
    seed/          procedural demo bridge (component registry) + synthetic demo images + demo seeding
    models.py      SQLAlchemy schema        schemas.py  Pydantic API contract
    background.py  live simulation, feature extraction, device-status alerts, retention
  alembic/         migrations               ml/  training / evaluation / metrics for crack classifier
  model_store/     drop installed models here (none shipped)
  tests/           pytest suite
frontend/
  src/twin/        3D scene: BridgeScene, BridgeModel, Markers, Decor, Sidebar, Details, Timeline
  src/pages/       the ten application sections
  src/components/  evidence panel, upload, record-finding form, sensor charts, UI kit
  src/api/ store/ lib/ hooks/   API client + React Query hooks, Zustand UI store, pure geometry helpers
  e2e/smoke.mjs    browser end-to-end smoke test
firmware/esp32_mqtt_node/ ESP32 + MPU6050 + DHT22 MQTT firmware (current)
firmware/esp32_mpu6050/   earlier HTTP-ingestion reference sketch
backend/edge/             webcam agent (ring buffer, clips, live preview)
docs/              architecture, API reference, hardware integration, limitations & security
scripts/           dev.sh (start both servers), test.sh (run test suites)
```

How the parts interact: the React app talks only to the REST API (`/api/v1`) and listens to a
server-sent-event stream for change notifications. The 3D viewer renders geometry descriptors stored
with each component, so component IDs are shared by the database, the API and the scene. The backend
runs inference through a pluggable model registry, stores images/reports on local disk behind opaque
keys, and a background loop turns raw sensor readings into features, baselines comparisons and alerts.
Details: [docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md),
[docs/hardware-integration.md](docs/hardware-integration.md), [backend/ml/README.md](backend/ml/README.md).

## Configuration

Backend: environment variables with prefix `SS_` (see [backend/.env.example](backend/.env.example)) —
database URL, storage and model directories, CORS origins, upload limit, device-auth settings,
background loop, demo seeding. Runtime settings (data-source mode, priority rules, thresholds,
retention) are stored in the database and edited in **Settings**.

Frontend (optional): `VITE_API_PROXY_TARGET` (default `http://127.0.0.1:8000`), `VITE_MAP_TILE_URL`
and `VITE_MAP_ATTRIBUTION` for the map view.

## Tests

```bash
./scripts/test.sh                       # backend pytest + frontend typecheck + vitest
node frontend/e2e/smoke.mjs             # browser smoke test against running servers (needs `playwright`)
```

### Test results (recorded in the development environment, 2026-10-30)

| Suite | Result |
|---|---|
| Backend `pytest` (51 tests, adding: MQTT handler + end-to-end through a real Mosquitto broker, environment ingestion/thresholds/dew point, absolute vibration limit without baseline, camera frames/clips/suppression/heartbeat, webcam agent end-to-end against a live uvicorn, GLB upload/bounds/ID-preserving re-upload) | 51 passed |
| Frontend `tsc` typecheck + `vitest` (20 tests, adding placement/aim maths, GLB node mapping, scene framing) | clean · 20 passed |
| Browser e2e `frontend/e2e/smoke.mjs` | 9/9 passed |
| Firmware `esp32_mqtt_node.ino` | g++ syntax/type check against API stubs; its payload-building code run on the host and accepted by the backend MQTT handler. **Not compiled for or flashed to an ESP32** (toolchain download blocked in this environment). |
| Manual run: emulated node over MQTT (scratch harness, not committed) | readings/env/status ingested; 60 s windows; limit alert fired only for the window above the configured limit; node went Stale when publishing stopped |

The test-only ONNX model used by inference tests is generated inside the tests and is not a crack detector.

## Roadmap (next phases)

1. Train/evaluate a crack classifier on a verified, licensed dataset with `backend/ml` and install it.
2. Connect the ESP32 + MPU6050 firmware; validate sampling, calibration and baselines on site.
3. Authentication/authorization, HTTPS, PostgreSQL deployment.
4. Camera calibration and image-to-surface projection on real meshes; GLB model loader.
5. Detection/segmentation models and overlays; additional sensor types; validated RUL research.
