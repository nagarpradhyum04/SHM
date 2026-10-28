# Hardware integration guide — ESP32 + MPU6050

> **Status:** the software side (device registry, authenticated ingestion API, validation,
> feature extraction, baselines, alerts and dashboards) is implemented and tested with
> uploaded and simulated data. **No physical hardware has been connected or validated.**
> The firmware in `firmware/esp32_mpu6050/` is a reference sketch that has not been run on a device.

## Data path

```
MPU6050 ──I²C──► ESP32 ──Wi-Fi (HTTP/HTTPS)──► FastAPI  POST /api/v1/ingest/readings
                                                   │  validate · dedupe · authenticate
                                                   ▼
                                     sensor_readings (source = "real", raw)
                                                   │  background job, every 5 s
                                                   ▼
                     vibration_features (60 s windows, vib-features-v1) ── baseline comparison (vib-anomaly-v1)
                                                   │
                                                   ▼
                       alerts (vibration anomaly · combined visual+vibration · stale · offline)
                                                   │
                                                   ▼
                          Digital twin markers · Sensor Analytics · Reports
```

## 1. Register the device

Device Registry → **Register device** (or `POST /api/v1/devices`):

| Field | Value |
|---|---|
| Device ID | e.g. `ACC-HW-01` (used by the firmware) |
| Type | Accelerometer |
| Data source | **Real hardware** |
| Component | the structural component the sensor is attached to |
| X/Y/Z, yaw/pitch/roll | installation pose in the 3D model's **local** coordinates |
| Latitude/longitude | only if surveyed |
| Sample rate | must equal the firmware's `SAMPLE_RATE_HZ` (used for completeness checks) |

The response contains a one-time **ingestion token**. Put it in the firmware (`DEVICE_TOKEN`).
It is stored only as a SHA-256 hash; rotate it from the registry if it leaks. Optionally a shared
key can be configured with `SS_DEVICE_SHARED_KEY` (keep it out of source control).

## 2. Firmware

`firmware/esp32_mpu6050/esp32_mpu6050.ino` (Arduino-ESP32, libraries: *Adafruit MPU6050*, *ArduinoJson v7*):

* samples at a fixed rate, converts m/s² → g and rad/s → deg/s,
* stamps UTC time via NTP (readings without valid time are accepted but flagged `suspect`),
* keeps a monotonically increasing `seq` (persist it across reboots, e.g. in NVS, otherwise the
  server rejects repeated sequence numbers as duplicates),
* posts batches of 200 readings with the `X-Device-Token` header.

Before relying on data, validate on hardware: sampling jitter (move HTTP posting to a separate
FreeRTOS task), MPU6050 offsets/calibration and mounting orientation, Wi-Fi reconnection and
buffering during outages, HTTPS with certificate pinning for anything beyond a lab network.

## 3. Dashboard behaviour

* Top bar → **Data: Real** shows only real readings; simulated and uploaded data are hidden, never merged.
* A real device shows *Never connected* until its first reading, then *Online*, *Stale* (> `stale_after_s`)
  or *Offline* (> `offline_after_s`). Stale/offline raise alerts; missing data is never treated as "normal".
* Features are computed per 60 s window. Windows below 80 % completeness are stored but not evaluated.
* **Create a baseline** (Sensor Analytics → Baselines) from a period you have verified as representative.
  Without a baseline no anomaly is evaluated. Baselines are versioned and recorded with each feature window.

## 4. Testing without hardware

```bash
TOKEN=...  # from registration
curl -X POST http://127.0.0.1:8000/api/v1/ingest/readings \
  -H "Content-Type: application/json" -H "X-Device-Token: $TOKEN" \
  -d '{"device_id":"ACC-HW-01","readings":[{"seq":1,"ts":"2026-10-28T12:00:00Z","ax":0.01,"ay":0.0,"az":1.0}]}'
```

## 5. Anomaly interpretation

An anomaly means the window's dynamic RMS or peak exceeded `baseline mean + k·σ`. Traffic,
wind, temperature, loose mounting and electrical noise all cause this. Alerts ask for engineering
review; they are not damage detections or failure predictions. Thresholds (`k`) are configurable and
recorded with every evaluated window.
