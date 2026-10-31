// Smart Bridge Monitor — ESP32 DevKit + MPU6050 + DHT11 -> MQTT
//
// Wiring:
//   MPU6050  VCC -> 3V3, GND -> GND, SDA -> GPIO21 (D21), SCL -> GPIO22 (D22)
//   DHT11    VCC -> 3V3, GND -> GND, DATA -> GPIO4 (D4)
//
// Libraries (Arduino Library Manager):
//   PubSubClient (Nick O'Leary), DHT sensor library (Adafruit),
//   Adafruit Unified Sensor (needed by the DHT library)
//   The MPU6050 is read directly over I2C (no library) so clone chips work too.
//
// Needs secrets.h in this folder (copy secrets.example.h and fill it in).
//
// Publishes JSON to "bridge/sensors" every 500 ms, e.g.:
//   {"vib":0.0061,"peak":0.0133,"level":"CALM","tilt":1.25,"temp":29.5,
//    "hum":52.0,"mpu":true,"dht":true,"simulated":false}
//   vib   = RMS vibration over the last 500 ms (g, gravity removed)
//   peak  = biggest single jolt in the last 500 ms (g)
//   level = CALM / LOW / MODERATE / HIGH / SEVERE (from vib)
//   tilt  = angle of the sensor from vertical (degrees)
//   temp  = °C, hum = % relative humidity (DHT11, refreshed every 2 s)
//   Values are null when that sensor isn't responding.

#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <DHT.h>
#include "secrets.h"

// ---------- Network ----------
const char* WIFI_SSID = WIFI_SSID_VALUE;
const char* WIFI_PASS = WIFI_PASS_VALUE;
const char* MQTT_HOST = MQTT_HOST_VALUE;
const uint16_t MQTT_PORT = 1883;
const char* TOPIC = "bridge/sensors";

// ---------- Pins ----------
const int I2C_SDA = 21;
const int I2C_SCL = 22;
const int DHT_PIN = 4;

// ---------- Timing ----------
const unsigned long SAMPLE_US = 2000;            // MPU: 500 samples/s
const unsigned long PUBLISH_INTERVAL_MS = 500;
const unsigned long DHT_INTERVAL_MS = 2000;      // DHT11 is slow
const unsigned long MQTT_RETRY_MS = 3000;
const unsigned long MPU_RETRY_MS = 5000;         // re-detect MPU if it drops out

// ---------- Vibration ----------
const float GRAVITY_FILTER = 0.02;   // how slowly the gravity estimate follows changes

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
DHT dht(DHT_PIN, DHT11);

// MPU state
uint8_t mpuAddr = 0;          // 0 = not found
bool mpuOk = false;
float gX = 0, gY = 0, gZ = 0; // gravity estimate (g)
float sumSq = 0, peak = 0;    // current vibration window
unsigned long samples = 0;
int mpuErrors = 0;

// DHT state
float lastTemp = NAN, lastHum = NAN;

// Timers
unsigned long lastSample = 0, lastPublish = 0, lastDhtRead = 0;
unsigned long lastMqttAttempt = 0, lastMpuAttempt = 0;

// ================= MPU6050 (raw I2C) =================

void mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(mpuAddr);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

bool mpuReadAccel(float &x, float &y, float &z) {
  Wire.beginTransmission(mpuAddr);
  Wire.write(0x3B);                                  // ACCEL_XOUT_H
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(mpuAddr, (uint8_t)6) < 6) return false;

  int16_t ax = (Wire.read() << 8) | Wire.read();
  int16_t ay = (Wire.read() << 8) | Wire.read();
  int16_t az = (Wire.read() << 8) | Wire.read();
  x = ax / 16384.0;                                  // ±2 g range
  y = ay / 16384.0;
  z = az / 16384.0;
  return true;
}

bool mpuInit() {
  mpuAddr = 0;
  for (uint8_t addr : {0x68, 0x69}) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) { mpuAddr = addr; break; }
  }
  if (mpuAddr == 0) {
    Serial.println("MPU6050 NOT found - check SDA=D21, SCL=D22, 3V3, GND.");
    return false;
  }

  mpuWrite(0x6B, 0x00);   // wake up
  mpuWrite(0x1C, 0x00);   // accel ±2 g
  mpuWrite(0x1A, 0x01);   // digital low-pass ~184 Hz
  delay(100);

  // Calibrate gravity (keep the sensor still)
  Serial.println("Calibrating MPU... keep the sensor STILL for 2 s.");
  float x, y, z, sx = 0, sy = 0, sz = 0;
  int n = 0;
  for (int i = 0; i < 400; i++) {
    if (mpuReadAccel(x, y, z)) { sx += x; sy += y; sz += z; n++; }
    delay(5);
  }
  if (n < 100) {
    Serial.println("MPU6050 calibration failed - loose wire?");
    return false;
  }
  gX = sx / n; gY = sy / n; gZ = sz / n;
  Serial.printf("MPU6050 OK at 0x%02X, gravity X=%.2f Y=%.2f Z=%.2f g\n",
                mpuAddr, gX, gY, gZ);

  sumSq = 0; peak = 0; samples = 0; mpuErrors = 0;
  return true;
}

void sampleMPU() {
  if (!mpuOk) {
    // Try to find the MPU again every few seconds
    if (millis() - lastMpuAttempt >= MPU_RETRY_MS) {
      lastMpuAttempt = millis();
      mpuOk = mpuInit();
    }
    return;
  }

  if (micros() - lastSample < SAMPLE_US) return;
  lastSample = micros();

  float x, y, z;
  if (!mpuReadAccel(x, y, z)) {
    if (++mpuErrors > 50) {               // ~0.1 s of failed reads
      Serial.println("MPU6050 stopped responding.");
      mpuOk = false;
      lastMpuAttempt = millis();
    }
    return;
  }
  mpuErrors = 0;

  // Gravity slowly follows the reading, so slow tilt isn't vibration
  gX += GRAVITY_FILTER * (x - gX);
  gY += GRAVITY_FILTER * (y - gY);
  gZ += GRAVITY_FILTER * (z - gZ);

  float dx = x - gX, dy = y - gY, dz = z - gZ;
  float mag = sqrt(dx * dx + dy * dy + dz * dz);

  sumSq += mag * mag;
  if (mag > peak) peak = mag;
  samples++;
}

float currentTilt() {
  // Angle between the gravity vector and the sensor's Z axis
  return atan2(sqrt(gX * gX + gY * gY), gZ) * 180.0 / PI;
}

const char* vibLevel(float rms) {
  if (rms < 0.01) return "CALM";
  if (rms < 0.03) return "LOW";
  if (rms < 0.10) return "MODERATE";
  if (rms < 0.30) return "HIGH";
  return "SEVERE";
}

// ================= DHT11 =================

void sampleDHT() {
  if (lastDhtRead != 0 && millis() - lastDhtRead < DHT_INTERVAL_MS) return;
  lastDhtRead = millis();

  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (isnan(t) || isnan(h)) {
    Serial.println("DHT11 read failed - check DATA on D4.");
  }
  lastTemp = t;
  lastHum = h;
}

// ================= Network =================

void connectWiFi() {
  Serial.print("Connecting to Wi-Fi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (millis() - start > 20000) {
      Serial.println("\nWi-Fi timeout, will retry.");
      return;
    }
  }
  Serial.print("\nWi-Fi connected, ESP32 IP: ");
  Serial.println(WiFi.localIP());
}

void ensureMQTT() {
  if (mqtt.connected()) return;
  if (millis() - lastMqttAttempt < MQTT_RETRY_MS) return;
  lastMqttAttempt = millis();

  String clientId = "bridge-esp32-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  Serial.printf("Connecting to MQTT %s:%u ... ", MQTT_HOST, MQTT_PORT);
  if (mqtt.connect(clientId.c_str())) {
    Serial.println("CONNECTED");
  } else {
    // -2 = broker unreachable (wrong IP / firewall / broker not running)
    Serial.printf("FAILED, state=%d, retrying in %lu s\n",
                  mqtt.state(), MQTT_RETRY_MS / 1000);
  }
}

// ================= Publish =================

void jsonNum(char* buf, size_t len, float v, int decimals) {
  if (isnan(v)) snprintf(buf, len, "null");
  else snprintf(buf, len, "%.*f", decimals, v);
}

void publishReading() {
  bool haveVib = mpuOk && samples > 0;
  float rms = haveVib ? sqrt(sumSq / samples) : NAN;

  char vib[16], pk[16], tilt[16], temp[16], hum[16], level[16];
  jsonNum(vib, sizeof(vib), rms, 4);
  jsonNum(pk, sizeof(pk), haveVib ? peak : NAN, 4);
  jsonNum(tilt, sizeof(tilt), mpuOk ? currentTilt() : NAN, 2);
  jsonNum(temp, sizeof(temp), lastTemp, 1);
  jsonNum(hum, sizeof(hum), lastHum, 1);
  if (haveVib) snprintf(level, sizeof(level), "\"%s\"", vibLevel(rms));
  else snprintf(level, sizeof(level), "null");

  bool dhtOk = !isnan(lastTemp) && !isnan(lastHum);

  char payload[256];
  snprintf(payload, sizeof(payload),
           "{\"vib\":%s,\"peak\":%s,\"level\":%s,\"tilt\":%s,"
           "\"temp\":%s,\"hum\":%s,"
           "\"mpu\":%s,\"dht\":%s,\"simulated\":false}",
           vib, pk, level, tilt, temp, hum,
           mpuOk ? "true" : "false", dhtOk ? "true" : "false");

  Serial.print(payload);
  if (mqtt.connected() && mqtt.publish(TOPIC, payload)) {
    Serial.println("  -> published");
  } else {
    Serial.println("  -> NOT published (MQTT offline)");
  }

  // Start a new vibration window
  sumSq = 0; peak = 0; samples = 0;
}

// ================= Main =================

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== Smart Bridge Monitor ===");

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);
  mpuOk = mpuInit();
  lastMpuAttempt = millis();

  dht.begin();
  Serial.println("DHT11 started on D4.");

  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);   // default 256 is tight for this payload
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (WiFi.status() == WL_CONNECTED) ensureMQTT();
  mqtt.loop();

  sampleMPU();
  sampleDHT();

  if (millis() - lastPublish >= PUBLISH_INTERVAL_MS) {
    lastPublish = millis();
    publishReading();
  }
}
