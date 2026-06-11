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
#include "calibration/zero.h"
#include "utils/watchdog.h"

// ---------------------------------------------------------------------------
// MQTT topics
// ---------------------------------------------------------------------------
static const char* PUBLISH_TOPIC    = "wing/sensors";
static const char* SUBSCRIBE_TOPICS = "wing/control,wing/stepper/status";

// ---------------------------------------------------------------------------
// Stepper state (tracked from wing/stepper/status MQTT messages)
// ---------------------------------------------------------------------------
static struct {
    long   position = 0;
    long   target   = 0;
    bool   enabled  = true;
    bool   moving   = false;
    bool   online   = false;
    bool   midMove  = false;
} s_stepper;

// ---------------------------------------------------------------------------
// State tracking
// ---------------------------------------------------------------------------
static bool          s_zeroCalibrated = false;
static unsigned long s_lastMqttMsg    = 0;
static bool          s_mqttMsgSeen    = false;
static bool          s_autoZeroFired  = false;

// ---------------------------------------------------------------------------
// Forward declarations
// ---------------------------------------------------------------------------
static void mqtt_send_stepper_command(const char* json);

// ---------------------------------------------------------------------------
// MQTT message handler
// ---------------------------------------------------------------------------
static void on_mqtt_message(const char* topic, const char* payload) {
    if (strcmp(topic, "wing/stepper/status") == 0) {
        StaticJsonDocument<256> doc;
        DeserializationError err = deserializeJson(doc, payload);
        if (err) return;
        s_stepper.position = doc["position"] | s_stepper.position;
        s_stepper.target   = doc["target"]   | s_stepper.target;
        s_stepper.enabled  = doc["enabled"]  | s_stepper.enabled;
        s_stepper.moving   = doc["moving"]   | s_stepper.moving;
        s_stepper.midMove  = doc["mid_move"] | s_stepper.midMove;
        s_stepper.online   = true;
        zero_update_stepper_state(s_stepper.position, s_stepper.moving, s_stepper.online);
        return;
    }

    // wing/control messages
    s_lastMqttMsg = millis();
    s_mqttMsgSeen = true;
    s_autoZeroFired = false;

    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, payload);
    if (err) {
        Serial.printf("[MQTT] parse error: %s\n", err.c_str());
        return;
    }
    Serial.printf("[MQTT] << %s\n", payload);

    if (doc.containsKey("calibrate") && doc["calibrate"].as<bool>()) {
        s_zeroCalibrated = false;
        if (zero_run()) {
            s_zeroCalibrated = true;
        }
    }

    if (doc.containsKey("tare") && doc["tare"].as<bool>()) {
        if (hx711_tare()) {
            hx711_save_calibration();
            Serial.println("[MQTT] tare done");
        } else {
            Serial.println("[MQTT] tare failed");
        }
    }

    if (doc.containsKey("status") && doc["status"].as<bool>()) {
        Serial.printf("[MQTT] status: wifi=%d mqtt=%d stepper_pos=%ld target=%ld enabled=%d moving=%d online=%d\n",
                      wifi_mgr_is_connected(), mqtt_is_connected(),
                      s_stepper.position, s_stepper.target, s_stepper.enabled, s_stepper.moving, s_stepper.online);
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

static void mqtt_send_stepper_command(const char* json) {
    if (!mqtt_is_connected()) return;
    mqtt_publish(STEPPER_COMMAND_TOPIC, json);
}

// ---------------------------------------------------------------------------
// Sensor data publishing
// ---------------------------------------------------------------------------
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
    doc["stepper_position"] = s_stepper.position;
    doc["home_offset"]      = zero_get_offset();
    doc["timestamp"]        = millis();

    String out;
    serializeJson(doc, out);
    mqtt_publish(PUBLISH_TOPIC, out.c_str());
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== Wing Digital Twin Node (Dual-ESP) ===");

    rgb_init();

    if (!LittleFS.begin(false)) {
        Serial.println("[MAIN] LittleFS mount failed, trying format...");
        if (!LittleFS.begin(true)) {
            Serial.println("[MAIN] LittleFS mount + format failed");
        }
    }

    hx711_init();

    wifi_mgr_init();
    mqtt_init(MQTT_SERVER, MQTT_PORT, SUBSCRIBE_TOPICS);
    mqtt_set_callback(on_mqtt_message);

    zero_init();

    // Wait for MQTT connection and stepper status
    Serial.println("[MAIN] Waiting for MQTT and stepper...");
    unsigned long mqttStart = millis();
    while (millis() - mqttStart < 30000) {
        watchdog_feed();
        wifi_mgr_loop();
        mqtt_loop();
        if (mqtt_is_connected() && zero_is_stepper_ready()) {
            Serial.println("[MAIN] MQTT + Stepper online");
            break;
        }
        delay(10);
    }

    if (zero_is_stepper_ready()) {
        if (s_stepper.midMove) {
            Serial.println("[MAIN] Stepper was mid-move — running calibration");
        } else {
            Serial.printf("[MAIN] Stepper restored to position %ld\n", s_stepper.position);
        }

        zero_run();
        s_zeroCalibrated = true;
    } else {
        Serial.println("[MAIN] WARNING: stepper not available — skipping calibration");
    }

    // After calibration, ensure stepper is reset to 0 at home
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"reset_position\":0}");
    mqtt_send_stepper_command(buf);
    s_stepper.position = 0;

    watchdog_init(WATCHDOG_TIMEOUT_S);
    rgb_set_all("1_green,2_green,3_green");
    Serial.println("=== Ready ===");
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------
void loop() {
    watchdog_feed();
    wifi_mgr_loop();
    mqtt_loop();

    if (mqtt_is_connected() && s_mqttMsgSeen && !s_autoZeroFired &&
        millis() - s_lastMqttMsg > MQTT_POSITION_TIMEOUT_MS &&
        !s_stepper.moving) {
        Serial.println("[MAIN] MQTT timeout — zeroing stepper");
        mqtt_send_stepper_command("{\"position\":0}");
        s_autoZeroFired = true;
    }

    // Connection-state LED feedback
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

    // Periodic publish
    static unsigned long lastPub = 0;
    if (millis() - lastPub >= PUBLISH_INTERVAL_MS) {
        lastPub = millis();
        publish_sensor_data();
    }

    // Periodic drift correction status log (every 30s)
    static unsigned long lastDriftLog = 0;
    if (hx711_is_drift_correcting() && millis() - lastDriftLog > 30000) {
        lastDriftLog = millis();
        Serial.println("[HX711] drift correction active");
    }
}
