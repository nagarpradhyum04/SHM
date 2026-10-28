# API reference (v1)

Base URL: `http://127.0.0.1:8000/api/v1` (proxied by the Vite dev server at `http://127.0.0.1:5173/api/v1`).
Interactive OpenAPI documentation is served by the backend at `/docs` (Swagger UI) and `/openapi.json`.

Conventions
* JSON in/out; timestamps are ISO-8601 in UTC (`...+00:00`). Naive timestamps are interpreted as UTC.
* Errors: `{"detail": "..."}` (or FastAPI's validation list for 422). 404 unknown IDs, 409 conflicts/invalid transitions, 413 oversize uploads.
* Every observation-like record carries a data source: `real`, `uploaded`, `simulated` or `demo`.
* Model coordinates (`model_x/y/z`, `pos_*`) are local 3D scene coordinates in metres (Y-up), never latitude/longitude.
* File paths are never returned; images and reports are served through ID-based endpoints.
* No user authentication is implemented yet (single-user local build). Device ingestion requires a per-device token.

## Device ingestion contract (ESP32 + MPU6050)

`POST /api/v1/ingest/readings` with header `X-Device-Token: <token issued at registration>`

```json
{
  "device_id": "ACC-HW-01",
  "firmware_version": "ref-0.1.0",
  "readings": [
    {"seq": 1024, "ts": "2026-10-28T12:00:00.010Z", "ax": 0.012, "ay": -0.004, "az": 1.001,
     "gx": 0.1, "gy": -0.2, "gz": 0.0, "temperature_c": 24.1}
  ]
}
```

* `seq` (required, ≥ 0, monotonically increasing per device): duplicates are rejected and counted.
* `ax/ay/az` in g (|value| ≤ 16), `gx/gy/gz` in deg/s (|value| ≤ 2000) optional, `temperature_c` optional.
* `ts` optional: if missing the server substitutes its receive time and marks the reading `quality: "suspect"`. Timestamps more than 5 minutes in the future are rejected.
* Max 2000 readings per request. Response `202`:
  `{"accepted": 199, "rejected": 1, "duplicates": 0, "errors": ["seq 5: acceleration non-finite or beyond ±16.0 g"], "source": "real"}`.
  Any rejection raises (or deduplicates into) a *Data validation failure* alert for the device.
* `401` unknown device / bad token, `400` device not a sensor or registered as simulated, `409` decommissioned.

Historical CSV upload (`POST /sensors/{device_id}/upload`, multipart `file`, header `seq,ts,ax,ay,az[,gx,gy,gz,temperature_c]`) stores readings with source `uploaded`.

## Endpoints

### Alerts

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/alert-rules` | Rules |
| GET | `/api/v1/alerts` | List Alerts |
| GET | `/api/v1/alerts/{alert_id}` | Alert Detail |
| PATCH | `/api/v1/alert-rules/{rule_id}` | Patch Rule |
| POST | `/api/v1/alerts/evaluate` | Evaluate |
| POST | `/api/v1/alerts/{alert_id}/acknowledge` | Acknowledge |
| POST | `/api/v1/alerts/{alert_id}/assign` | Assign |
| POST | `/api/v1/alerts/{alert_id}/reopen` | Reopen |
| POST | `/api/v1/alerts/{alert_id}/resolve` | Resolve |

### Assets

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/assets` | List Assets |
| GET | `/api/v1/assets/{asset_id}` | Get Asset |
| GET | `/api/v1/assets/{asset_id}/components` | List Components |
| GET | `/api/v1/assets/{asset_id}/summary` | Metrics computed from stored records only. ``None`` means no data (not zero risk). |
| GET | `/api/v1/components/{component_id}` | Component Detail |
| PATCH | `/api/v1/assets/{asset_id}` | Patch Asset |
| PATCH | `/api/v1/components/{component_id}` | Patch Component |
| POST | `/api/v1/assets` | Create Asset |
| POST | `/api/v1/assets/{asset_id}/components` | Create Component |

### Defects

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/defects` | List Defects |
| GET | `/api/v1/defects/{defect_id}` | Detail |
| PATCH | `/api/v1/defects/{defect_id}` | Patch |
| POST | `/api/v1/defects` | Create |
| POST | `/api/v1/defects/{defect_id}/recompute-priority` | Recompute |
| POST | `/api/v1/spatial/project` | Project an image pixel from a registered camera onto a component (approximate, see spatial module docs). |

### Devices

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/devices` | List Devices |
| GET | `/api/v1/devices/{device_id}` | Get Device |
| GET | `/api/v1/devices/{device_id}/status` | Device Status |
| PATCH | `/api/v1/devices/{device_id}` | Patch Device |
| POST | `/api/v1/devices` | Registers a device. For real sensors a one-time ingestion token is returned (store it in the firmware config). |
| POST | `/api/v1/devices/{device_id}/rotate-token` | Rotate Token |

### History

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/events` | Events |
| GET | `/api/v1/history/compare` | Side-by-side comparison of two inspections. Images are NOT spatially registered. |
| GET | `/api/v1/history/components/{component_id}` | Component History |
| GET | `/api/v1/history/repeated` | Groups findings of the same category on the same component (and within radius when both have surface positions). |
| GET | `/api/v1/history/vibration` | Vibration History |

### Inspections

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/demo-images` | Demo Images |
| GET | `/api/v1/demo-images/{variant}` | Demo Image Preview |
| GET | `/api/v1/images/{image_id}` | Get Image |
| GET | `/api/v1/images/{image_id}/file` | Get Image File |
| GET | `/api/v1/inspections` | List Inspections |
| GET | `/api/v1/inspections/{inspection_id}` | Get Inspection |
| POST | `/api/v1/inspections/demo` | Run the normal inspection pipeline on a synthetic, clearly-labelled demonstration image. |
| POST | `/api/v1/inspections/image` | Validate an uploaded image, store it, run the configured model (if any) and record the inspection. |

### Reports

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/reports` | List Reports |
| GET | `/api/v1/reports/{report_id}/download` | Download |
| GET | `/api/v1/reports/{report_id}/print` | Print View |
| POST | `/api/v1/reports` | Create Report |

### Sensors

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/sensors/{device_id}/baselines` | Baselines |
| GET | `/api/v1/sensors/{device_id}/features` | Features |
| GET | `/api/v1/sensors/{device_id}/latest` | Latest Reading |
| GET | `/api/v1/sensors/{device_id}/readings` | Readings |
| GET | `/api/v1/simulation` | Simulation Status |
| POST | `/api/v1/ingest/readings` | Device ingestion endpoint (ESP32 + MPU6050 contract v1). Requires ``X-Device-Token``. |
| POST | `/api/v1/sensors/{device_id}/analyze` | Analyze |
| POST | `/api/v1/sensors/{device_id}/baselines` | Create Baseline |
| POST | `/api/v1/sensors/{device_id}/upload` | Upload historical readings as CSV (stored with source='uploaded'). |
| POST | `/api/v1/simulation/generate` | Simulation Generate |
| PUT | `/api/v1/simulation` | Set Simulation |

### Stream

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/stream` | Server-sent events: change notifications (alerts, defects, readings, features, devices). Clients refetch over REST. |

### System

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/health` | Health |
| GET | `/api/v1/models` | Models |
| GET | `/api/v1/rul/results` | Rul Results |
| GET | `/api/v1/settings` | Get Settings All |
| GET | `/api/v1/system/status` | System Status |
| POST | `/api/v1/models/reload` | Reload Models |
| POST | `/api/v1/rul/estimate` | Rul Estimate |
| PUT | `/api/v1/settings/{key}` | Put Setting |
