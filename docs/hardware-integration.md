# Hardware integration — ESP32 + MPU6050 + DHT11 over MQTT, USB webcam, uploaded 3D model

> **Status.** Everything on the server side (MQTT bridge, validation, vibration features, limits,
> environment readings, alerts, webcam agent, clip storage, GLB upload, device placement) is
> implemented and tested — including against a real Mosquitto broker and a host-run of the
> firmware's own payload code. **The firmware has not yet been flashed to your board.** Expect to
> verify wiring, the DHT type and timing on the real hardware (see *Checks* below).

```
 MPU6050 ─I²C─┐                                           ┌──────────── laptop ─────────────┐
 DHT11 ──GPIO4─┤ ESP32 ──Wi-Fi──► Mosquitto :1883 ───────►│ StructuraSense backend :8000    │
               │  bridge/<ID>/accel | env | status         │  MQTT bridge → validation →     │
               └───────────────────────────────────────────│  readings / features / alerts   │
 USB webcam ──► edge/camera_agent.py ──HTTP──────────────► │  frames → model → inspections   │
                (ring buffer, clips, live preview :8081)   │  clips stored with the event     │
                                                           └──────── browser :5173 ─────────┘
```

## 1. Wiring

| Part | Pin | ESP32 |
|---|---|---|
| MPU6050 | VCC / GND | 3V3 / GND |
| | SDA / SCL | GPIO21 / GPIO22 |
| | AD0 | GND (address 0x68) |
| DHT11 | VCC / GND | 3V3 / GND |
| | DATA | GPIO4 (3-pin module: pull-up already fitted; bare 4-pin sensor: add 10 kΩ DATA→3V3) |

Mount the MPU6050 rigidly on the structure (screwed/epoxied, not taped) — a loose mount measures the
mount, not the structure. Keep the DHT sensor shaded and ventilated.

## 2. Broker on the laptop (Mosquitto)

* **Windows:** install from mosquitto.org, then create `mosquitto.conf`:
  ```
  listener 1883 0.0.0.0
  allow_anonymous true
  ```
  run `mosquitto -c mosquitto.conf -v` and allow TCP 1883 in Windows Defender Firewall (private network).
* **Linux/macOS:** `sudo apt install mosquitto` / `brew install mosquitto`, same config.
* On shared networks use a password file instead of anonymous access
  (`mosquitto_passwd -c passwd node`, `password_file passwd`, `allow_anonymous false`) and set
  `SS_MQTT_USERNAME/SS_MQTT_PASSWORD` in `backend/.env` and `MQTT_USER/MQTT_PASSWORD` in the firmware.

The backend connects to `127.0.0.1:1883` by default (`SS_MQTT_*` in `backend/.env`).
**Settings → IoT connection (MQTT)** shows the connection state and the last 60 messages with the
reason any message was rejected.

## 3. Register the node

Digital Twin → select the part where it is mounted → **Add device here** (or Device Registry →
Register device): type **Sensor node**, data source **Real hardware**, sample rate **100 Hz**.
Copy the one-time **token**. Then select the new marker → **Edit placement** → **Pick position on
model** and click where the node is installed → **Save placement**.

## 4. Flash the firmware

`firmware/esp32_mqtt_node/`:

1. Arduino IDE → Board: *ESP32 Dev Module*. Library Manager: **PubSubClient**, **Adafruit MPU6050**,
   **Adafruit Unified Sensor**, **DHT sensor library**.
2. Copy `secrets.example.h` → `secrets.h` (git-ignored) and fill in Wi-Fi, the laptop's IPv4
   (e.g. `192.168.29.107`), `DEVICE_ID` (exactly as registered) and `DEVICE_TOKEN`.
3. The sketch is set for your **DHT11** (`#define DHT_TYPE DHT11`); change it only if you upgrade to a DHT22.
4. Upload, open Serial Monitor at 115200 baud.

What it sends (every message carries the token):

| Topic | Rate | Content |
|---|---|---|
| `bridge/<ID>/accel` | every 0.5 s | 50 samples @ 100 Hz: `seq0`, `t0_ms` (UTC via NTP), `ax/ay/az` in g, `gx/gy/gz` in °/s, MPU temperature |
| `bridge/<ID>/env` | every 2 s | `temp_c`, `rh`, sensor type |
| `bridge/<ID>/status` | every 10 s | firmware, RSSI, uptime, IP, `mpu_ok`, `env_ok`, dropped samples |

Your earlier test sketch published made-up values flagged `"simulated": true` to `bridge/sensors`;
the backend lists such messages in the MQTT panel as rejected and never stores them as real data.

## 5. Vibration alerts ("if it exceeds the limit")

The backend cuts the 100 Hz stream into 60 s windows and computes `rms_dyn` (RMS of the dynamic
part of the acceleration magnitude, gravity removed) and `peak_dyn`. Two independent rules:

* **Absolute limit** — Settings → *Alert limits*: `Vibration RMS limit (g)` / `peak limit (g)`.
  A complete window above a limit raises **"Vibration above configured limit"** (priority high). No
  default numbers are shipped: the limit must come from the bridge's design/serviceability criteria
  or your engineer.
* **Baseline anomaly** — after ~10 normal minutes, Sensor Analytics → *Create baseline*; windows above
  `baseline + k·σ` raise **"Vibration anomaly"**.

Windows with < 80 % of the expected samples are stored but not evaluated. A spike can be traffic,
wind or a loose mount; alerts mean "review", not "damage".

## 6. Temperature & humidity — what they can and cannot tell you

**Your DHT11:** 0–50 °C ±2 °C, 20–90 %RH ±5 %, 1-unit resolution. Readings outside that rated range are
stored but marked *suspect*. With this accuracy the computed dew point is only good to roughly ±2–3 °C, so
if you use the condensation-margin alert, set the margin larger than that (or upgrade to a DHT22/SHT31).

They **cannot detect or confirm cracks**. They are recorded because temperature changes the
structure's stiffness and therefore its vibration, and because heat/moisture cycling, near-condensation
and freeze–thaw drive deterioration. The dashboard shows temperature, humidity, dew point and 0 °C
crossings; Settings → *Alert limits* lets you alert on max/min temperature, max humidity or a
condensation margin (air temperature − dew point), after N consecutive samples.

## 7. Webcam: detect, keep a short clip and the photo, update the dashboard

1. Register a **Camera** (data source real) on the part it watches; place it with **Edit placement**
   and **Aim at point**.
2. On the laptop the USB webcam is plugged into, first find its index (built-in laptop cameras are usually 0,
   a plugged-in USB camera is often 1), and close other apps that use the camera (Zoom, Camera app, browser):
   ```bash
   cd backend
   .venv/bin/python -m edge.camera_agent --list-cameras          # Windows: .venv\Scripts\python -m edge.camera_agent --list-cameras
   .venv/bin/python -m edge.camera_agent --device-id WEBCAM-01 --token <token> --source 1
   ```
   (on Windows the agent opens webcams through DirectShow; `--interval 5` seconds between analysed frames;
   `--pre 5 --post 5` clip seconds; `--bind 0.0.0.0 --public-host <laptop IP>` to view the live preview
   from other machines.)
3. Every interval the newest frame goes to the backend, which runs the installed model. On a finding it
   stores the **photo**, creates the finding on that component (shown on the 3D model), raises an alert,
   and the agent uploads a **WebM clip** of the seconds around the detection. Repeated detections of an
   already-open finding are not stored again for 1 h. One reference photo per hour is kept regardless.

**Important:** crack detection needs a trained model (`backend/ml/README.md`). Without one the agent
still streams the live preview and stores the hourly reference photos, but nothing is "detected".

## 8. Your own 3D model

Infrastructure Assets → *Register asset* → **3D structural model → Upload 3D model (.glb)**.
Export one self-contained `.glb` (Blender: File → Export → glTF Binary; +Y up; metres; no Draco
compression). Named parts become selectable components; re-uploading a revised model keeps component
IDs by part name, so findings and devices stay attached. Defect and device markers then appear on
your model, and you place devices with **Edit placement**.

## Windows quick start

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1        # backend + frontend in two windows
mosquitto -c mosquitto.conf -v                                  # in the Mosquitto install folder
cd backend; .venv\Scripts\python -m edge.camera_agent --device-id WEBCAM-01 --token <token> --source 1
```

## Checks after flashing

* Serial monitor shows Wi-Fi + MQTT "connected"; no "MPU6050 not found" / "DHT read failed".
* Settings → MQTT panel: accel/env/status messages *accepted* (a rejection says why: token, ID, JSON).
* Device turns **Online**; Sensor Analytics shows readings; with the node still, `az ≈ ±1 g`.
* The ESP32 syncs its clock from `pool.ntp.org` over your internet connection; if NTP ever fails, readings are still accepted but marked `suspect`.
* Unplug the node: after 2 min it becomes **Stale**, after 15 min **Offline**, each with an alert.
