/*
 * StructuraSense AI — reference firmware for ESP32 + MPU6050 (ingestion contract v1)
 *
 * STATUS: reference sketch, NOT yet tested on hardware. It compiles against the
 * Arduino-ESP32 core with the "Adafruit MPU6050" and "ArduinoJson" (v7) libraries,
 * but sampling timing, Wi-Fi robustness and calibration must be validated on the
 * real device before any data is used.
 *
 * Flow: MPU6050 --I2C--> ESP32 --Wi-Fi/HTTPS--> POST /api/v1/ingest/readings
 *
 * Configure the constants below (or move them to NVS / a provisioning flow).
 */
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <time.h>

static const char* WIFI_SSID = "your-ssid";
static const char* WIFI_PASS = "your-password";
static const char* API_URL = "http://192.168.1.10:8000/api/v1/ingest/readings";  // use HTTPS outside a lab network
static const char* DEVICE_ID = "ACC-HW-01";            // must be registered in the Device Registry (data source: real)
static const char* DEVICE_TOKEN = "paste-token-here";  // shown once at registration; send as X-Device-Token
static const char* FIRMWARE_VERSION = "ref-0.1.0";

static const uint32_t SAMPLE_RATE_HZ = 100;   // must match sample_rate_hz in the registry
static const uint16_t BATCH_SIZE = 200;       // readings per POST (server max 2000)
static const float G = 9.80665f;

Adafruit_MPU6050 mpu;
uint32_t seq = 0;  // monotonically increasing; persist across reboots (e.g. NVS) to avoid duplicate rejection

struct Sample { uint32_t seq; time_t sec; uint16_t ms; float ax, ay, az, gx, gy, gz, temp; };
Sample buf[BATCH_SIZE];
uint16_t n = 0;

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(250);
  configTime(0, 0, "pool.ntp.org");  // UTC timestamps; readings without valid time are flagged 'suspect' by the server
}

bool timeValid() { return time(nullptr) > 1700000000; }

void flush() {
  if (n == 0 || WiFi.status() != WL_CONNECTED) return;
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["firmware_version"] = FIRMWARE_VERSION;
  JsonArray arr = doc["readings"].to<JsonArray>();
  char ts[32];
  for (uint16_t i = 0; i < n; i++) {
    JsonObject r = arr.add<JsonObject>();
    r["seq"] = buf[i].seq;
    if (buf[i].sec > 1700000000) {
      struct tm t; gmtime_r(&buf[i].sec, &t);
      snprintf(ts, sizeof ts, "%04d-%02d-%02dT%02d:%02d:%02d.%03uZ", t.tm_year + 1900, t.tm_mon + 1, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, buf[i].ms);
      r["ts"] = ts;
    }
    r["ax"] = buf[i].ax; r["ay"] = buf[i].ay; r["az"] = buf[i].az;   // g
    r["gx"] = buf[i].gx; r["gy"] = buf[i].gy; r["gz"] = buf[i].gz;   // deg/s
    r["temperature_c"] = buf[i].temp;
  }
  String body;
  serializeJson(doc, body);
  HTTPClient http;
  http.begin(API_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  int code = http.POST(body);
  // 202 = accepted (response lists rejected/duplicate items). On network failure keep the batch and retry.
  if (code == 202 || code == 400 || code == 401) n = 0;  // 400/401: do not retry invalid batches forever; inspect the server alert
  http.end();
}

void setup() {
  Serial.begin(115200);
  Wire.begin();
  if (!mpu.begin()) { Serial.println("MPU6050 not found"); while (true) delay(1000); }
  mpu.setAccelerometerRange(MPU6050_RANGE_2_G);
  mpu.setGyroRange(MPU6050_RANGE_250_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_44_HZ);
  connectWifi();
}

void loop() {
  static uint32_t next = micros();
  if ((int32_t)(micros() - next) < 0) return;
  next += 1000000UL / SAMPLE_RATE_HZ;
  sensors_event_t a, g, t;
  mpu.getEvent(&a, &g, &t);
  struct timeval tv; gettimeofday(&tv, nullptr);
  buf[n++] = {seq++, timeValid() ? tv.tv_sec : 0, (uint16_t)(tv.tv_usec / 1000),
              a.acceleration.x / G, a.acceleration.y / G, a.acceleration.z / G,
              g.gyro.x * 57.2958f, g.gyro.y * 57.2958f, g.gyro.z * 57.2958f, t.temperature};
  if (n >= BATCH_SIZE) flush();  // NOTE: blocking POST pauses sampling; use a FreeRTOS task + queue in production
}
