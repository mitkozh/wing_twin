#include "mqtt.h"
#include "wifi_mgr.h"
#include "../config.h"
#include "../utils/watchdog.h"
#include <WiFi.h>
#include <PubSubClient.h>

static WiFiClient    s_wifiClient;
static PubSubClient  s_mqtt(s_wifiClient);
static mqtt_msg_cb_t s_callback = NULL;
static const char*   s_subTopic = NULL;
static String        s_server;
static int           s_port = 0;
static unsigned long s_lastAttempt = 0;
static unsigned int  s_retryMs = MQTT_RETRY_BASE_MS;
static bool          s_connected = false;

static void handle_message(char* topic, byte* payload, unsigned int len) {
    if (!s_callback) return;
    String jsonStr;
    for (unsigned int i = 0; i < len; i++) jsonStr += (char)payload[i];
    s_callback(topic, jsonStr.c_str());
}

void mqtt_init(const char* server, int port, const char* subscribe_topic) {
    s_subTopic = subscribe_topic;
    s_server = server;
    s_port = port;
    s_mqtt.setServer(server, port);
    s_mqtt.setCallback(handle_message);
    Serial.printf("[MQTT] init %s:%d sub=%s\n", server, port, subscribe_topic);
}

void mqtt_set_callback(mqtt_msg_cb_t cb) {
    s_callback = cb;
}

bool mqtt_publish(const char* topic, const char* payload) {
    if (!s_connected) return false;
    bool ok = s_mqtt.publish(topic, payload);
    if (!ok) Serial.printf("[MQTT] publish failed: %s\n", topic);
    return ok;
}

bool mqtt_is_connected(void) {
    return s_connected;
}

void mqtt_loop(void) {
    if (!wifi_mgr_is_connected()) return;
    if (s_mqtt.connected()) {
        if (!s_connected) {
            s_connected = true;
            s_retryMs = MQTT_RETRY_BASE_MS;
            Serial.println("[MQTT] connected");
            if (s_subTopic) {
                s_mqtt.subscribe(s_subTopic);
                Serial.printf("[MQTT] subscribed to %s\n", s_subTopic);
            }
        }
        s_mqtt.loop();
        return;
    }
    if (s_connected) {
        s_connected = false;
        Serial.println("[MQTT] disconnected");
    }
    unsigned long now = millis();
    if (now - s_lastAttempt < s_retryMs) return;
    s_lastAttempt = now;
    watchdog_feed();
    String clientId = "ESP32-Wing-" + String(random(0xffff), HEX);
    Serial.printf("[MQTT] connecting to %s:%d...\n", s_server.c_str(), s_port);
    if (s_mqtt.connect(clientId.c_str())) {
        s_retryMs = MQTT_RETRY_BASE_MS;
    } else {
        Serial.printf("[MQTT] rc=%d, retry in %ums\n", s_mqtt.state(), s_retryMs);
        s_retryMs = min(s_retryMs * 2, MQTT_MAX_RETRY_MS);
    }
}
