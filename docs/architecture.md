# Architecture

StructuraSense AI is a **modular monolith**: one FastAPI process (with an in-process background
loop) and one React single-page application. It runs on a laptop with SQLite and local file storage.

```
┌──────────────────────────── Browser (React SPA, Vite) ─────────────────────────────┐
│  AppShell (top bar, nav)   React Query cache  ◄── SSE /api/v1/stream (invalidation) │
│  Digital Twin: R3F scene ← components (geometry descriptors) · devices · defects    │
│  Pages: Assets · Inspections · Defects · Devices · Sensors · Alerts · History ·      │
│         Reports · Settings          Zustand: selection, layers, filters, camera cmds │
└───────────────────────────────┬────────────────────────────────────────────────────┘
                                │ REST JSON /api/v1 (+ multipart uploads)
┌───────────────────────────────▼──────────────── FastAPI (backend/app) ──────────────┐
│ api/v1/*  routers (validation via Pydantic schemas)                                  │
│ services/                                                                             │
│   operations      inspection pipeline, defect create/update (shared by API + seeder)  │
│   imaging         decode-based file validation, OpenCV quality heuristics             │
│   inference/      InferenceBackend interface · ONNX classifier · model registry       │
│   priority        documented rule engine R1–R6 (review priority, not severity)        │
│   alert_engine    rules, dedup, cooldowns, evidence, audit trail, correlation         │
│   ingestion       device auth (hashed tokens), payload validation, duplicate seq      │
│   vibration       window features vib-features-v1, baselines, anomaly vib-anomaly-v1  │
│   simulation      labelled simulated signals for simulated devices only               │
│   spatial         coordinate systems, camera-ray → component bbox projection          │
│   reports         ReportLab PDF + print HTML from one data collection                 │
│   rul             independent RUL interface (returns "unavailable" + input coverage)  │
│   device_status   online / stale / offline / never-connected / simulated              │
│ background.py     every 5 s: live simulation, feature extraction, status alerts,      │
│                   retention                                                            │
└──────┬──────────────────────────┬─────────────────────────┬──────────────────────────┘
       │ SQLAlchemy 2 + Alembic   │ LocalStorage (opaque keys)│ model_store/<id>/model_card.json + model.onnx
       ▼                          ▼                           ▼
   SQLite (→ PostgreSQL)     data/storage/images|reports   ONNX Runtime (CPU)
```

## Data model (tables)

`assets`, `components` (registry + geometry descriptor + bbox + optional geo), `devices` (cameras and
sensors, pose, data source, token hash), `image_records`, `inspections`, `defects`, `defect_events`,
`sensor_readings` (raw), `vibration_features` (derived), `baselines`, `alert_rules`, `alerts`,
`alert_evidence`, `alert_events` (audit), `event_log` (timeline), `reports`, `model_registry`,
`rul_results`, `system_config`. Users/roles are **not implemented** (see limitations).

Schema changes go through Alembic (`backend/alembic/versions`). A test asserts the migrations match
the ORM models. To use PostgreSQL set `SS_DATABASE_URL=postgresql+psycopg://…` and install `psycopg[binary]`.

## Coordinate systems

| System | Where | Notes |
|---|---|---|
| Image | `defects.image_region` | pixels, u right / v down |
| Camera | `services/spatial.py` | x right, y up, looking −z; pose = yaw·pitch·roll (Euler YXZ, matches three.js) |
| Model | `model_x/y/z`, `pos_*`, `bbox` | local scene metres, Y-up — **not** geographic |
| Geographic | `latitude/longitude` | only when surveyed, or derived through an asset `geo_transform` flagged calibrated/uncalibrated |

Every defect stores `location_kind` (component | surface), `localization_method`
(manual_component, manual_surface_pick, camera_ray_aabb, photogrammetry*, survey*) and
`location_confidence` (component_only, low, approximate, medium, high). *Interfaces only.

## 3D model

The demonstration bridge (`backend/app/seed/demo_bridge.py`) is procedural and is the single source
of truth for component IDs; the frontend renders the stored geometry descriptors (`box`, `beam`,
`cable`) and adds non-interactive scenery. A GLB/GLTF model can replace it by mapping node names to
component IDs through `mesh_ref` (see `frontend/src/twin/model-loader.md`).

## Provenance rules

* `data_source` on readings, features, images, inspections, defects and alerts.
* Simulated readings exist only for devices registered as simulated; real ingestion into a simulated
  device is rejected; simulated devices are never shown as connected.
* Priority rules never let simulated/demo evidence corroborate real/uploaded evidence.
* Alerts store the rule version and parameters; feature windows store feature version, baseline id/version and thresholds.
* AI findings store model id, version, label, confidence and threshold; the model card stores dataset
  provenance and evaluated metrics.
