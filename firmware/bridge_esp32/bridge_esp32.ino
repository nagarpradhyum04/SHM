// Smart Bridge Monitor — ESP32 DevKit + MPU6050 + DHT11 -> MQTT
//
// Wiring:
//   MPU6050  VCC -> 3V3, GND -> GND, SDA -> GPIO21 (D21), SCL -> GPIO22 (D22)
//   DHT11    VCC -> 3V3, GND -> GND, DATA -> GPIO4 (D4)
//
// Libraries (Arduino Library Manager):
//   PubSubClient (Nick O'Leary), Adafruit MPU6050, Adafruit Unified Sensor,
//   DHT sensor library (Adafruit)
//
// Publishes JSON to "bridge/sensors" every 500 ms:
//   {"vib":0.012,"tilt":1.35,"temp":27.0,"hum":61.0,"mpu":true,"dht":true,"simulated":false}
//   vib  = peak deviation from 1 g during the last 500 ms window (in g)
//   tilt = angle of the board from vertical (degrees)
//   temp = DHT11 temperature (°C), hum = DHT11 relative humidity (%)
//   Values are null when that sensor isn't responding.

#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <DHT.h>
#include "secrets.h"

const char* WIFI_SSID = WIFI_SSID_VALUE;
const char* WIFI_PASS = WIFI_PASS_VALUE;
const char* MQTT_HOST = MQTT_HOST_VALUE;
const uint16_t MQTT_PORT = 1883;
const char* TOPIC = "bridge/sensors";

// Pins
const int I2C_SDA = 21;
const int I2C_SCL = 22;
const int DHT_PIN = 4;

// Timing
const unsigned long PUBLISH_INTERVAL_MS = 500;
const unsigned long DHT_INTERVAL_MS = 2000;   // DHT11 can't be read faster than ~1 s
const unsigned long MQTT_RETRY_MS = 3000;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
Adafruit_MPU6050 mpu;
DHT dht(DHT_PIN, DHT11);

bool mpuOk = false;

// Vibration window state (sampled every loop, reported every publish)
float peakVibration = 0.0;
float lastTilt = NAN;

// Latest DHT values (DHT11 is slow, so we cache them)
float lastTemp = NAN;
float lastHum = NAN;

unsigned long lastPublish = 0;
unsigned long lastDhtRead = 0;
unsigned long lastMqttAttempt = 0;

void connectWiFi() {
  Serial.print("Connecting to Wi-Fi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (millis() - start > 20000) {          // give up after 20 s, try again later
      Serial.println("\nWi-Fi timeout, will retry.");
      return;
    }
  }
  Serial.print("\nWi-Fi connected, ESP32 IP: ");
  Serial.println(WiFi.localIP());
}

// Non-blocking: tries once, then waits MQTT_RETRY_MS before the next try,
// so sensor sampling keeps running while the broker is unreachable.
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

void sampleMPU() {
  if (!mpuOk) return;

  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  float ax = a.acceleration.x, ay = a.acceleration.y, az = a.acceleration.z;
  float mag = sqrt(ax * ax + ay * ay + az * az);

  // Vibration: how far total acceleration deviates from gravity, in g.
  float dev = fabs(mag - SENSORS_GRAVITY_STANDARD) / SENSORS_GRAVITY_STANDARD;
  if (dev > peakVibration) peakVibration = dev;

  // Tilt: angle between the board's Z axis and vertical, in degrees.
  lastTilt = atan2(sqrt(ax * ax + ay * ay), az) * 180.0 / PI;
}

void sampleDHT() {
  if (millis() - lastDhtRead < DHT_INTERVAL_MS && lastDhtRead != 0) return;
  lastDhtRead = millis();

  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (isnan(t) || isnan(h)) {
    Serial.println("DHT11 read failed - check DATA on D4");
  }
  lastTemp = t;
  lastHum = h;
}

// Writes a float as JSON, or null if it's not a number.
void jsonNum(char* buf, size_t len, float v, int decimals) {
  if (isnan(v)) snprintf(buf, len, "null");
  else snprintf(buf, len, "%.*f", decimals, v);
}

void publishReading() {
  char vib[16], tilt[16], temp[16], hum[16];
  jsonNum(vib, sizeof(vib), mpuOk ? peakVibration : NAN, 3);
  jsonNum(tilt, sizeof(tilt), mpuOk ? lastTilt : NAN, 2);
  jsonNum(temp, sizeof(temp), lastTemp, 1);
  jsonNum(hum, sizeof(hum), lastHum, 1);

  bool dhtOk = !isnan(lastTemp) && !isnan(lastHum);

  char payload[192];
  snprintf(payload, sizeof(payload),
           "{\"vib\":%s,\"tilt\":%s,\"temp\":%s,\"hum\":%s,"
           "\"mpu\":%s,\"dht\":%s,\"simulated\":false}",
           vib, tilt, temp, hum,
           mpuOk ? "true" : "false", dhtOk ? "true" : "false");

  Serial.print(payload);
  if (mqtt.connected() && mqtt.publish(TOPIC, payload)) {
    Serial.println("  -> published");
  } else {
    Serial.println("  -> NOT published (MQTT offline)");
  }

  peakVibration = 0.0;  // start a new vibration window
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\nSmart Bridge Monitor starting...");

  Wire.begin(I2C_SDA, I2C_SCL);
  mpuOk = mpu.begin();
  if (mpuOk) {
    mpu.setAccelerometerRange(MPU6050_RANGE_2_G);
    mpu.setGyroRange(MPU6050_RANGE_250_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_44_HZ);
    Serial.println("MPU6050 found.");
  } else {
    Serial.println("MPU6050 NOT found - check SDA=D21, SCL=D22, 3V3, GND.");
  }

  dht.begin();
  Serial.println("DHT11 started on D4.");

  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
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

  delay(5);  // ~200 Hz MPU sampling
}
