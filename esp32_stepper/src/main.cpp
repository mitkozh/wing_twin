#include <Arduino.h>
#include <ArduinoJson.h>

#include "pins.h"
#include "config.h"
#include "secrets.h"

#include "hardware/stepper.h"

#include "comms/wifi_mgr.h"
#include "comms/mqtt.h"

#include "utils/watchdog.h"

static const char* SUB_TOPIC  = "wing/stepper/command";
static const char* PUB_TOPIC  = "wing/stepper/status";

static unsigned long s_lastStatusPub = 0;

static void publish_status(void) {
    StaticJsonDocument<256> doc;
    doc["position"]  = stepper_get_position();
    doc["target"]    = stepper_get_target();
    doc["enabled"]   = stepper_is_enabled();
    doc["moving"]    = stepper_is_moving();
    doc["mid_move"]  = stepper_was_mid_move();

    String out;
    serializeJson(doc, out);
    mqtt_publish(PUB_TOPIC, out.c_str());
}

static void on_mqtt_message(const char* topic, const char* payload) {
    StaticJsonDocument<192> doc;
    DeserializationError err = deserializeJson(doc, payload);
    if (err) {
        Serial.printf("[MQTT] parse error: %s\n", err.c_str());
        return;
    }
    Serial.printf("[MQTT] << %s\n", payload);

    if (doc.containsKey("position")) {
        stepper_set_target(doc["position"].as<long>());
    }

    if (doc.containsKey("enable")) {
        stepper_enable(doc["enable"].as<bool>());
    }

    if (doc.containsKey("reset_position")) {
        stepper_reset_position(doc["reset_position"].as<long>());
        stepper_save_position();
        stepper_set_dirty(false);
        Serial.printf("[MAIN] position reset to %ld\n", doc["reset_position"].as<long>());
    }
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== Wing Stepper Node ===");

    stepper_init();

    wifi_mgr_init();
    mqtt_init(MQTT_SERVER, MQTT_PORT, SUB_TOPIC);
    mqtt_set_callback(on_mqtt_message);

    long savedPos = 0;
    bool hadSavedPos = stepper_load_position(&savedPos);
    if (hadSavedPos) {
        stepper_reset_position(savedPos);
        Serial.printf("[MAIN] Restored stepper position: %ld\n", savedPos);
    }

    if (stepper_was_mid_move()) {
        Serial.println("[MAIN] WARNING: previous shutdown mid-move");
    }

    watchdog_init(WATCHDOG_TIMEOUT_S);
    Serial.println("=== Stepper Node Ready ===");
}

void loop() {
    watchdog_feed();
    wifi_mgr_loop();
    mqtt_loop();
    stepper_loop();

    if (millis() - s_lastStatusPub >= STATUS_PUBLISH_INTERVAL_MS) {
        s_lastStatusPub = millis();
        publish_status();
    }
}
