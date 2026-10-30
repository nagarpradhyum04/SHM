// Copy this file to secrets.h (git-ignored) and fill in your values.
#pragma once

#define WIFI_SSID "your-wifi-or-hotspot-name"
#define WIFI_PASS "your-wifi-password"

// IPv4 address of the laptop running Mosquitto + the StructuraSense backend (e.g. 192.168.29.107)
#define MQTT_HOST "192.168.29.107"
#define MQTT_PORT 1883
// Leave empty for an anonymous broker; set if you configured Mosquitto with a password file.
#define MQTT_USER ""
#define MQTT_PASSWORD ""

// Must match the Device ID registered in StructuraSense (type "Sensor node", data source "Real hardware")
#define DEVICE_ID "NODE-01"
// Ingestion token shown once when the device was registered (Device Registry → key icon rotates it)
#define DEVICE_TOKEN "paste-the-token-here"
