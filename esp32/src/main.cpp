#include <Arduino.h>
#include <ArduinoJson.h>

#include "pins.h"
#include "config.h"
#include "secrets.h"

#include "hardware/rgb.h"
#include "hardware/hx711.h"
#include "hardware/stepper.h"

#include "comms/wifi_mgr.h"
#include "comms/mqtt.h"

#include <LittleFS.h>
#include "calibration/zero.h"
#include "utils/watchdog.h"

// ---------------------------------------------------------------------------
// MQTT topics
// ---------------------------------------------------------------------------
static const char* PUBLISH_TOPIC   = "wing/sensors";
static const char* SUBSCRIBE_TOPIC = "wing/control";

// ---------------------------------------------------------------------------
// Stepper state tracking
// ---------------------------------------------------------------------------
static bool          s_zeroCalibrated = false;
static unsigned long s_lastMqttMsg    = 0;
static bool          s_mqttMsgSeen    = false;
static bool          s_autoZeroFired  = false;

// ---------------------------------------------------------------------------
// MQTT message handler
// ---------------------------------------------------------------------------
static void on_mqtt_message(const char* topic, const char* payload) {
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
            stepper_reset_position(0);
            stepper_save_position();
            stepper_set_dirty(false);
        }
    } else if (doc.containsKey("position")) {
        stepper_set_target(doc["position"].as<long>());
    }

    if (doc.containsKey("tare") && doc["tare"].as<bool>()) {
        if (hx711_tare()) {
            hx711_save_calibration();
            Serial.println("[MQTT] tare done");
        } else {
            Serial.println("[MQTT] tare failed");
        }
    }

    if (doc.containsKey("stepper_enable")) {
        stepper_enable(doc["stepper_enable"].as<bool>());
    }

    if (doc.containsKey("status") && doc["status"].as<bool>()) {
        Serial.printf("[MQTT] status: wifi=%d mqtt=%d stepper_pos=%ld target=%ld enabled=%d\n",
                      wifi_mgr_is_connected(), mqtt_is_connected(),
                      stepper_get_position(), stepper_get_target(), stepper_is_enabled());
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
    doc["stepper_position"] = stepper_get_position();
    doc["home_offset"]      = zero_get_offset();
    doc["timestamp"]        = millis();

    String out;
    serializeJson(doc, out);
    mqtt_publish(PUBLISH_TOPIC, out.c_str());
}

// ---------------------------------------------------------------------------
// Stepper wait helper (passed to zero calibrator via callbacks)
// ---------------------------------------------------------------------------
static void wait_for_stepper(unsigned long timeout_ms) {
    unsigned long start = millis();
    while (stepper_is_moving() && millis() - start < timeout_ms) {
        stepper_loop();
        watchdog_feed();
        delay(1);
    }
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== Wing Digital Twin Node ===");

    rgb_init();

    // Mount LittleFS once at startup for all components
    if (!LittleFS.begin(false)) {
        Serial.println("[MAIN] LittleFS mount failed, trying format...");
        if (!LittleFS.begin(true)) {
            Serial.println("[MAIN] LittleFS mount + format failed");
        }
    }

    hx711_init();
    stepper_init();

    wifi_mgr_init();
    mqtt_init(MQTT_SERVER, MQTT_PORT, SUBSCRIBE_TOPIC);
    mqtt_set_callback(on_mqtt_message);

    zero_callbacks_t cbs = {
        hx711_get_strain,
        stepper_set_target,
        stepper_get_position,
        wait_for_stepper
    };
    zero_init(cbs);

    // Restore last known physical position before calibrating
    long savedPos = 0;
    bool hadSavedPos = stepper_load_position(&savedPos);
    if (hadSavedPos) {
        stepper_reset_position(savedPos);
        Serial.printf("[MAIN] Restored stepper position: %ld\n", savedPos);
    }

    if (stepper_was_mid_move()) {
        Serial.println("[MAIN] WARNING: previous shutdown mid-move - resetting to 0");
        stepper_reset_position(0);
        stepper_save_position();
        stepper_set_dirty(false);
    }

    zero_run();
    stepper_reset_position(0);
    stepper_save_position();
    stepper_set_dirty(false);
    s_zeroCalibrated = true;

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
    stepper_loop();

    if (mqtt_is_connected() && s_mqttMsgSeen && !s_autoZeroFired &&
        millis() - s_lastMqttMsg > MQTT_POSITION_TIMEOUT_MS &&
        !stepper_is_moving()) {
        Serial.println("[MAIN] MQTT timeout — zeroing stepper");
        stepper_set_target(0);
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
