#include <Arduino.h>
#include <ArduinoJson.h>

#include "pins.h"
#include "config.h"
#include "secrets.h"

#include "hardware/rgb.h"
#include "hardware/hx711.h"

#include "comms/wifi_mgr.h"
#include "comms/mqtt.h"

#include <LittleFS.h>
#include "utils/watchdog.h"

static const char* PUBLISH_TOPIC   = "wing/sensor/data";
static const char* SUBSCRIBE_TOPIC = "wing/sensor/command";

static void on_mqtt_message(const char* topic, const char* payload) {
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, payload);
    if (err) {
        Serial.printf("[MQTT] parse error: %s\n", err.c_str());
        return;
    }
    Serial.printf("[MQTT] << %s\n", payload);

    if (doc.containsKey("tare") && doc["tare"].as<bool>()) {
        if (hx711_tare()) {
            hx711_save_calibration();
            Serial.println("[MQTT] tare done");
        } else {
            Serial.println("[MQTT] tare failed");
        }
    }

    if (doc.containsKey("status") && doc["status"].as<bool>()) {
        Serial.printf("[MQTT] status: wifi=%d mqtt=%d\n",
                      wifi_mgr_is_connected(), mqtt_is_connected());
        for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
            Serial.printf("  hx711[%d] raw=%ld sat=%d\n", i, hx711_get_raw(i), hx711_get_saturated(i));
        }
    }

    if (doc.containsKey("leds")) {
        JsonArray leds = doc["leds"].as<JsonArray>();
        if (leds.size() == 3 &&
            leds[0].is<const char*>() &&
            leds[1].is<const char*>() &&
            leds[2].is<const char*>()) {
            const char* c0 = leds[0].as<const char*>();
            const char* c1 = leds[1].as<const char*>();
            const char* c2 = leds[2].as<const char*>();
            if (c0 && c1 && c2) {
                char buf[64];
                snprintf(buf, sizeof(buf), "1_%s,2_%s,3_%s", c0, c1, c2);
                rgb_set_all(buf);
            }
        }
    }
}

static void publish_sensor_data(void) {
    if (!hx711_read_all()) {
        Serial.println("[MAIN] HX711 read failed - skipping publish");
        return;
    }
    hx711_update_drift();

    StaticJsonDocument<1024> doc;

    JsonArray rawArr = doc.createNestedArray("raw");
    for (int i = 0; i < HX711_NUM_ACTIVE; i++)
        rawArr.add(hx711_get_raw(i));

    JsonArray offsetArr = doc.createNestedArray("offset");
    for (int i = 0; i < HX711_NUM_ACTIVE; i++)
        offsetArr.add(hx711_get_offset(i));

    JsonArray saturatedArr = doc.createNestedArray("saturated");
    for (int i = 0; i < HX711_NUM_ACTIVE; i++)
        saturatedArr.add(hx711_get_saturated(i));

    doc["dummy_raw"]  = hx711_get_raw(HX711_NUM_CHANNELS - 1);
    doc["timestamp"]  = millis();

    String out;
    serializeJson(doc, out);
    mqtt_publish(PUBLISH_TOPIC, out.c_str());
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== Wing Sensor Node ===");

    rgb_init();

    if (!LittleFS.begin(false)) {
        Serial.println("[MAIN] LittleFS mount failed, trying format...");
        if (!LittleFS.begin(true)) {
            Serial.println("[MAIN] LittleFS mount + format failed");
        }
    }

    hx711_init();

    wifi_mgr_init();
    mqtt_init(MQTT_SERVER, MQTT_PORT, SUBSCRIBE_TOPIC);
    mqtt_set_callback(on_mqtt_message);

    watchdog_init(WATCHDOG_TIMEOUT_S);
    rgb_set_all("1_green,2_green,3_green");
    Serial.println("=== Ready ===");
}

void loop() {
    watchdog_feed();
    wifi_mgr_loop();
    mqtt_loop();

    static bool s_prev_mqtt_connected = false;
    bool mqtt_ok = mqtt_is_connected();
    if (mqtt_ok != s_prev_mqtt_connected) {
        s_prev_mqtt_connected = mqtt_ok;
        if (mqtt_ok) {
            rgb_set_all("1_green,2_green,3_green");
        } else {
            rgb_set_all("1_red,2_red,3_red");
        }
    }

    static unsigned long lastPub = 0;
    if (millis() - lastPub >= PUBLISH_INTERVAL_MS) {
        lastPub = millis();
        publish_sensor_data();
    }

    static unsigned long lastDriftLog = 0;
    if (hx711_is_drift_correcting() && millis() - lastDriftLog > 30000) {
        lastDriftLog = millis();
        Serial.println("[HX711] drift correction active");
    }
}
