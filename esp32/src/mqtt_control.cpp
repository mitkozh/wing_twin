#include "mqtt_control.h"

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#include "secrets.h"
#include "RGB_control.h"
#include "Stepper_control.h"

// =====================================================
// MQTT topics
// =====================================================
const char* PUBLISH_TOPIC   = "wing/sensors";
const char* SUBSCRIBE_TOPIC = "wing/control";

// =====================================================
// WiFi / MQTT client objects
// =====================================================
WiFiClient   espClient;
PubSubClient mqttClient(espClient);

// =====================================================
// Non-blocking connection state
// =====================================================
static bool             s_wifiConnected   = false;
static bool             s_mqttConnected   = false;
static unsigned long    s_lastConnectAttempt = 0;
static unsigned int     s_connectRetryMs  = 2000;      // starts at 2s, doubles on failure
static const unsigned int MAX_RETRY_MS    = 60000;     // caps at 60s
static const unsigned int WIFI_TIMEOUT_MS = 15000;     // give up on WiFi after 15s

// =====================================================
// JSON parsing for incoming wing/control messages
//
// Expected format from Python engine:
//   {"position": 1234, "leds": ["green", "yellow", "red"]}
// =====================================================

void mqtt_callback(char* topic, byte* payload, unsigned int length) {
    // Convert to null-terminated string
    String jsonStr;
    for (unsigned int i = 0; i < length; i++) {
        jsonStr += (char)payload[i];
    }

    Serial.print("[MQTT received] ");
    Serial.println(jsonStr);

    // Parse JSON
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, jsonStr);
    if (err) {
        Serial.print("[MQTT] JSON parse error: ");
        Serial.println(err.c_str());
        return;
    }

    // --- 1. Stepper position ---
    if (doc.containsKey("position")) {
        long pos = doc["position"].as<long>();
        stepper_set_target(pos);
        Serial.print("[MQTT] Stepper target -> ");
        Serial.println(pos);
    }

    // --- 2. LED colors ---
    if (doc.containsKey("leds")) {
        JsonArray leds = doc["leds"].as<JsonArray>();
        if (leds.size() == 3) {
            // Convert ["green","yellow","red"] -> "1_green,2_yellow,3_red"
            String cmd = "";
            for (int i = 0; i < 3; i++) {
                if (i > 0) cmd += ",";
                cmd += String(i + 1) + "_" + leds[i].as<String>();
            }
            cmd.toLowerCase();

            Serial.print("[MQTT] LED command -> ");
            Serial.println(cmd);

            set_leds(cmd);
        } else {
            Serial.print("[MQTT] Expected 3 LED colors, got ");
            Serial.println(leds.size());
        }
    }
}


// =====================================================
// Non-blocking WiFi connection with timeout
// =====================================================

static void setup_wifi_nonblocking() {
    static bool s_wifiPending = false;
    unsigned long now = millis();

    wl_status_t status = WiFi.status();

    // --- Already connected ---
    if (status == WL_CONNECTED) {
        if (!s_wifiConnected) {
            s_wifiConnected = true;
            s_wifiPending = false;
            s_connectRetryMs = 2000;
            Serial.println();
            Serial.print("[WiFi] Connected, IP: ");
            Serial.println(WiFi.localIP());
        }
        return;
    }

    // --- Connection lost ---
    if (s_wifiConnected) {
        s_wifiConnected = false;
        s_wifiPending = false;
        Serial.println("[WiFi] Connection lost");
    }

    // --- Connection in progress, just wait ---
    if (status == WL_IDLE_STATUS || status == WL_DISCONNECTED) {
        // Check for timeout
        if (s_wifiPending && (now - s_lastConnectAttempt > WIFI_TIMEOUT_MS)) {
            Serial.println("[WiFi] Timeout — resetting");
            WiFi.disconnect(true);
            s_wifiPending = false;
            s_lastConnectAttempt = now;
        }
        return;
    }

    // --- Connection failed or idle — start a new attempt ---
    if (now - s_lastConnectAttempt < 2000) {
        return;   // throttle retries to every 2s
    }

    Serial.print("[WiFi] Connecting to ");
    Serial.println(WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    s_lastConnectAttempt = now;
    s_wifiPending = true;
}


// =====================================================
// Non-blocking MQTT reconnect with exponential backoff
// =====================================================

static void mqtt_reconnect_nonblocking() {
    unsigned long now = millis();

    if (!s_wifiConnected) {
        return;   // can't connect MQTT without WiFi
    }

    if (mqttClient.connected()) {
        if (!s_mqttConnected) {
            s_mqttConnected = true;
            s_connectRetryMs = 2000;
            Serial.println("[MQTT] Connected to broker");

            // Re-subscribe on reconnect
            mqttClient.subscribe(SUBSCRIBE_TOPIC);
            Serial.print("[MQTT] Subscribed to ");
            Serial.println(SUBSCRIBE_TOPIC);
        }
        return;
    }

    // Connection lost
    if (s_mqttConnected) {
        s_mqttConnected = false;
        Serial.println("[MQTT] Connection lost");
    }

    // Throttle reconnect attempts
    if (now - s_lastConnectAttempt < s_connectRetryMs) {
        return;
    }

    Serial.print("[MQTT] Reconnecting to ");
    Serial.print(MQTT_SERVER);
    Serial.print(":");
    Serial.println(MQTT_PORT);

    s_lastConnectAttempt = now;

    String clientId = "ESP32-Wing-" + String(random(0xffff), HEX);
    if (mqttClient.connect(clientId.c_str())) {
        s_connectRetryMs = 2000;   // reset on success
        // Will set s_mqttConnected in the next loop() call
    } else {
        Serial.print("[MQTT] Failed, rc=");
        Serial.print(mqttClient.state());
        Serial.print(", retry in ");
        Serial.print(s_connectRetryMs);
        Serial.println("ms");

        // Exponential backoff with cap
        s_connectRetryMs = min(s_connectRetryMs * 2, MAX_RETRY_MS);
    }
}


// =====================================================
// Public API
// =====================================================

void mqtt_init() {
    randomSeed(analogRead(0));

    mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
    mqttClient.setCallback(mqtt_callback);

    s_lastConnectAttempt = 0;
    s_connectRetryMs = 2000;

    Serial.println("[MQTT] Initialized");
}


void mqtt_loop() {
    // Non-blocking WiFi connection
    setup_wifi_nonblocking();

    // Non-blocking MQTT reconnect
    mqtt_reconnect_nonblocking();

    // Process incoming messages (only if connected)
    if (mqttClient.connected()) {
        mqttClient.loop();
    }
}


bool mqtt_is_connected() {
    return s_wifiConnected && s_mqttConnected;
}


void mqtt_publish_sensor(long raw, long diff, float voltage_mV) {
    if (!mqttClient.connected()) {
        return;
    }

    char payload[200];
    snprintf(payload, sizeof(payload),
             "{\"raw\":%ld,\"diff\":%ld,\"voltage_mV\":%.6f,\"timestamp\":%lu}",
             raw, diff, voltage_mV, millis());

    if (mqttClient.publish(PUBLISH_TOPIC, payload)) {
        Serial.print("[MQTT] Published sensor: ");
        Serial.println(payload);
    }
}


void mqtt_publish_payload(const char* payload) {
    if (!mqttClient.connected()) {
        Serial.println("[MQTT] Not connected — payload dropped");
        return;
    }

    if (mqttClient.publish(PUBLISH_TOPIC, payload)) {
        Serial.print("[MQTT] Published payload: ");
        Serial.println(payload);
    } else {
        Serial.println("[MQTT] Publish failed");
    }
} 

 