/*
 * StructuraSense AI — ESP32 sensor node: MPU6050 (vibration) + DHT11 (temperature/humidity) over MQTT.
 *
 * Publishes (topic prefix "bridge", matching the backend's SS_MQTT_TOPIC_PREFIX):
 *   bridge/<DEVICE_ID>/accel   every 0.5 s: 50 samples at 100 Hz  {token, seq0, t0_ms, rate_hz, ax[], ay[], az[], gx[], gy[], gz[], temp_c, fw}
 *   bridge/<DEVICE_ID>/env     every 2 s:  {token, seq, t_ms, temp_c, rh, sensor}
 *   bridge/<DEVICE_ID>/status  every 10 s: {token, fw, rssi, uptime_s, ip, mpu_ok, env_ok, dropped, free_heap}
 * Units: acceleration in g, angular rate in deg/s, temperature in °C, humidity in %RH. Times are UTC epoch ms (NTP).
 *
 * The backend computes vibration features per 60 s window, compares them with your configured limit and
 * baseline, and raises alerts. Thresholds live on the server (Settings → Alert limits), not in this sketch.
 *
 * Libraries (Arduino Library Manager): "PubSubClient" (Nick O'Leary), "Adafruit MPU6050",
 * "Adafruit Unified Sensor", "DHT sensor library" (Adafruit). Board: ESP32 Dev Module (Arduino-ESP32 core 2.x/3.x).
 *
 * Wiring (default pins):
 *   MPU6050  VCC→3V3  GND→GND  SDA→GPIO21  SCL→GPIO22   (AD0 to GND → I2C address 0x68)
 *   DHT11    VCC→3V3  GND→GND  DATA→GPIO4. A 3-pin DHT11 module already has the pull-up; a bare 4-pin DHT11
 *            needs a 10 kΩ resistor from DATA to 3V3 (pin 3 of the bare sensor is unused).
 *   DHT11 specification: 0–50 °C ±2 °C, 20–90 %RH ±5 %, 1 °C / 1 % resolution — good enough for exposure
 *   trends, too coarse for precise dew-point work. Swap to a DHT22 by changing DHT_TYPE below.
 *
 * STATUS: written for this project and compiled logic reviewed, but not yet run on your hardware. Check the
 * serial monitor (115200 baud) and the Settings → "IoT connection (MQTT)" panel after flashing.
 */
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <DHT.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <sys/time.h>
#include <time.h>

#include "secrets.h"  // copy secrets.example.h → secrets.h

// ---------------------------------------------------------------- configuration
#define DHT_PIN 4
#define DHT_TYPE DHT11        // your sensor; use DHT22 if you upgrade
#define I2C_SDA 21
#define I2C_SCL 22
#define TOPIC_PREFIX "bridge"
#define FW_VERSION "node-0.2.0"

static const uint32_t SAMPLE_RATE_HZ = 100;   // register the device with the same sample rate
static const uint16_t BATCH = 50;             // samples per accel message (0.5 s)
static const uint32_t ENV_PERIOD_MS = 2000;   // DHT11 needs ≥ 1 s between reads (DHT22 ≥ 2 s)
static const uint32_t STATUS_PERIOD_MS = 10000;
static const uint32_t SEQ_BLOCK = 1000000;    // sequence numbers reserved per boot (persisted in NVS)

// Optional local buzzer/LED: set to a GPIO (e.g. 25) and a dynamic-acceleration threshold in g; -1 disables.
// This is only an on-site indicator; official alerts come from the backend.
#define LOCAL_ALARM_PIN -1
static const float LOCAL_ALARM_G = 0.0f;

// ---------------------------------------------------------------- state
struct Sample { int64_t t_ms; float ax, ay, az, gx, gy, gz; };
static QueueHandle_t sampleQueue;
static volatile uint32_t dropped = 0;
static volatile bool mpuOk = false;
static volatile float mpuTempC = NAN;

Adafruit_MPU6050 mpu;
DHT dht(DHT_PIN, DHT_TYPE);
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
Preferences prefs;

static uint32_t seq = 0;
static uint32_t seqBlockEnd = 0;
static bool envOk = false;
static char topicAccel[64], topicEnv[64], topicStatus[64];
static char payload[4096];

static bool timeValid() { return time(nullptr) > 1700000000; }

static int64_t nowMs() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  return (int64_t)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

// Reserve a block of sequence numbers so values never repeat after a reboot (the server rejects duplicates).
static void reserveSeqBlock() {
  prefs.begin("ssnode", false);
  uint32_t block = prefs.getUInt("seqblk", 0) + 1;
  prefs.putUInt("seqblk", block);
  prefs.end();
  seq = block * SEQ_BLOCK;
  seqBlockEnd = seq + SEQ_BLOCK;
}

// ---------------------------------------------------------------- sampling task (core 1, fixed rate)
static void samplingTask(void*) {
  const TickType_t period = pdMS_TO_TICKS(1000 / SAMPLE_RATE_HZ);
  TickType_t last = xTaskGetTickCount();
  sensors_event_t a, g, t;
  for (;;) {
    vTaskDelayUntil(&last, period);
    if (!mpuOk) continue;
    mpu.getEvent(&a, &g, &t);
    Sample s{nowMs(), a.acceleration.x / 9.80665f, a.acceleration.y / 9.80665f, a.acceleration.z / 9.80665f,
             g.gyro.x * 57.29578f, g.gyro.y * 57.29578f, g.gyro.z * 57.29578f};
    mpuTempC = t.temperature;
    if (xQueueSend(sampleQueue, &s, 0) != pdTRUE) dropped++;  // network stalled: drop, the server sees the gap
#if LOCAL_ALARM_PIN >= 0
    float mag = sqrtf(s.ax * s.ax + s.ay * s.ay + s.az * s.az);
    digitalWrite(LOCAL_ALARM_PIN, (LOCAL_ALARM_G > 0 && fabsf(mag - 1.0f) > LOCAL_ALARM_G) ? HIGH : LOW);
#endif
  }
}

// ---------------------------------------------------------------- networking
static void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("Wi-Fi…");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) { delay(250); Serial.print("."); }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf(" connected, IP %s\n", WiFi.localIP().toString().c_str());
    configTime(0, 0, "pool.ntp.org", "time.google.com");  // UTC; without valid time the server stamps arrival time
  } else {
    Serial.println(" failed (will retry)");
  }
}

static void connectMQTT() {
  if (mqtt.connected() || WiFi.status() != WL_CONNECTED) return;
  String clientId = String("ss-") + DEVICE_ID + "-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  Serial.print("MQTT…");
  bool ok = strlen(MQTT_USER) ? mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD) : mqtt.connect(clientId.c_str());
  Serial.println(ok ? " connected" : (String(" failed, state ") + mqtt.state()).c_str());
}

// Append helper for building JSON without heap allocations.
static size_t put(size_t n, const char* fmt, ...) {
  if (n >= sizeof(payload)) return n;
  va_list ap;
  va_start(ap, fmt);
  int w = vsnprintf(payload + n, sizeof(payload) - n, fmt, ap);
  va_end(ap);
  return w > 0 ? n + w : n;
}

static size_t putArray(size_t n, const char* name, const Sample* s, uint16_t count, float Sample::*field, const char* fmt) {
  n = put(n, ",\"%s\":[", name);
  for (uint16_t i = 0; i < count; i++) {
    if (i) n = put(n, ",");
    n = put(n, fmt, s[i].*field);
  }
  return put(n, "]");
}

static void publishAccel() {
  static Sample batch[BATCH];
  static uint16_t count = 0;
  Sample s;
  while (count < BATCH && xQueueReceive(sampleQueue, &s, 0) == pdTRUE) batch[count++] = s;
  if (count < BATCH || !mqtt.connected()) return;
  size_t n = put(0, "{\"token\":\"%s\",\"seq0\":%lu,\"rate_hz\":%lu", DEVICE_TOKEN, (unsigned long)seq, (unsigned long)SAMPLE_RATE_HZ);
  if (timeValid()) n = put(n, ",\"t0_ms\":%lld", (long long)batch[0].t_ms);
  n = putArray(n, "ax", batch, count, &Sample::ax, "%.4f");
  n = putArray(n, "ay", batch, count, &Sample::ay, "%.4f");
  n = putArray(n, "az", batch, count, &Sample::az, "%.4f");
  n = putArray(n, "gx", batch, count, &Sample::gx, "%.2f");
  n = putArray(n, "gy", batch, count, &Sample::gy, "%.2f");
  n = putArray(n, "gz", batch, count, &Sample::gz, "%.2f");
  if (!isnan(mpuTempC)) n = put(n, ",\"temp_c\":%.1f", mpuTempC);
  n = put(n, ",\"fw\":\"%s\"}", FW_VERSION);
  if (n >= sizeof(payload) - 1) { Serial.println("accel payload too large"); count = 0; return; }
  if (mqtt.publish(topicAccel, (const uint8_t*)payload, n, false)) {
    seq += count;
    if (seq >= seqBlockEnd) reserveSeqBlock();
  } else {
    dropped += count;  // keep sequence numbers moving so the gap is visible server-side
    seq += count;
  }
  count = 0;
}

static void publishEnv() {
  static uint32_t last = 0;
  if (millis() - last < ENV_PERIOD_MS || !mqtt.connected()) return;
  last = millis();
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  envOk = !isnan(t) && !isnan(h);
  if (!envOk) { Serial.println("DHT11 read failed (check DATA on GPIO4, 3V3 power and pull-up)"); return; }
  size_t n = put(0, "{\"token\":\"%s\",\"temp_c\":%.2f,\"rh\":%.1f,\"sensor\":\"%s\"", DEVICE_TOKEN, t, h,
                 DHT_TYPE == DHT11 ? "DHT11" : "DHT22");
  // seq = epoch seconds: unique across reboots for a ≥ 1 s period, so the server can reject re-sent duplicates
  if (timeValid()) n = put(n, ",\"seq\":%lld,\"t_ms\":%lld", (long long)(nowMs() / 1000), (long long)nowMs());
  n = put(n, "}");
  mqtt.publish(topicEnv, (const uint8_t*)payload, n, false);
}

static void publishStatus() {
  static uint32_t last = 0;
  if (millis() - last < STATUS_PERIOD_MS || !mqtt.connected()) return;
  last = millis();
  size_t n = put(0, "{\"token\":\"%s\",\"fw\":\"%s\",\"rssi\":%d,\"uptime_s\":%lu,\"ip\":\"%s\",\"mpu_ok\":%s,\"env_ok\":%s,\"dropped\":%lu,\"free_heap\":%lu}",
                 DEVICE_TOKEN, FW_VERSION, WiFi.RSSI(), (unsigned long)(millis() / 1000), WiFi.localIP().toString().c_str(),
                 mpuOk ? "true" : "false", envOk ? "true" : "false", (unsigned long)dropped, (unsigned long)ESP.getFreeHeap());
  mqtt.publish(topicStatus, (const uint8_t*)payload, n, false);
}

// ---------------------------------------------------------------- setup / loop
void setup() {
  Serial.begin(115200);
  delay(500);
  snprintf(topicAccel, sizeof topicAccel, "%s/%s/accel", TOPIC_PREFIX, DEVICE_ID);
  snprintf(topicEnv, sizeof topicEnv, "%s/%s/env", TOPIC_PREFIX, DEVICE_ID);
  snprintf(topicStatus, sizeof topicStatus, "%s/%s/status", TOPIC_PREFIX, DEVICE_ID);
#if LOCAL_ALARM_PIN >= 0
  pinMode(LOCAL_ALARM_PIN, OUTPUT);
#endif
  Wire.begin(I2C_SDA, I2C_SCL);
  mpuOk = mpu.begin();
  if (mpuOk) {
    mpu.setAccelerometerRange(MPU6050_RANGE_2_G);  // best resolution for small structural vibration
    mpu.setGyroRange(MPU6050_RANGE_250_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_44_HZ);    // below Nyquist (50 Hz) for 100 Hz sampling
  } else {
    Serial.println("MPU6050 not found — check SDA/SCL wiring and 3V3 power");
  }
  dht.begin();
  reserveSeqBlock();
  sampleQueue = xQueueCreate(SAMPLE_RATE_HZ * 4, sizeof(Sample));  // 4 s of buffering during network hiccups
  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(sizeof(payload) + 128);
  mqtt.setKeepAlive(30);
  xTaskCreatePinnedToCore(samplingTask, "sampling", 4096, nullptr, 2, nullptr, 1);
  Serial.printf("StructuraSense node %s started (fw %s)\n", DEVICE_ID, FW_VERSION);
}

void loop() {
  static uint32_t lastTry = 0;
  if ((WiFi.status() != WL_CONNECTED || !mqtt.connected()) && millis() - lastTry > 3000) {
    lastTry = millis();
    connectWiFi();
    connectMQTT();
  }
  mqtt.loop();
  publishAccel();
  publishEnv();
  publishStatus();
  delay(2);
}
