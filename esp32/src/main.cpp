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

#include "calibration/zero.h"
#include "cli/shell.h"
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

// ---------------------------------------------------------------------------
// MQTT message handler
// ---------------------------------------------------------------------------
static void on_mqtt_message(const char* topic, const char* payload) {
    s_lastMqttMsg = millis();
    s_mqttMsgSeen = true;

    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, payload);
    if (err) {
        Serial.printf("[MQTT] parse error: %s\n", err.c_str());
        return;
    }
    Serial.printf("[MQTT] << %s\n", payload);

    if (doc.containsKey("position")) {
        long pos = doc["position"].as<long>();
        if (pos == 0 && !s_zeroCalibrated) {
            s_zeroCalibrated = true;
            zero_run();
            stepper_reset_position(0);
        } else if (pos != 0) {
            s_zeroCalibrated = false;
            stepper_set_target(pos);
        } else {
            stepper_set_target(0);
        }
    }

    if (doc.containsKey("leds")) {
        JsonArray leds = doc["leds"].as<JsonArray>();
        if (leds.size() == 3 &&
            leds[0].is<const char*>() &&
            leds[1].is<const char*>() &&
            leds[2].is<const char*>()) {
            char buf[64];
            snprintf(buf, sizeof(buf), "1_%s,2_%s,3_%s",
                     leds[0].as<const char*>(),
                     leds[1].as<const char*>(),
                     leds[2].as<const char*>());
            rgb_set_all(buf);
        }
    }
}

// ---------------------------------------------------------------------------
// Sensor data publishing
// ---------------------------------------------------------------------------
static void publish_sensor_data(void) {
    hx711_read_all();

    StaticJsonDocument<512> doc;

    JsonArray strain = doc.createNestedArray("strain_vector");
    for (int i = 0; i < HX711_NUM_ACTIVE; i++)
        strain.add(hx711_get_strain(i));

    JsonArray channels = doc.createNestedArray("channels");
    for (int i = 0; i < HX711_NUM_ACTIVE; i++)
        channels.add(hx711_get_channel_name(i));

    doc["dummy_raw"]  = hx711_get_raw(9);
    doc["stepper_position"] = stepper_get_position();
    doc["home_offset"]      = zero_get_offset();
    doc["timestamp"]        = millis();

    String out;
    serializeJson(doc, out);
    mqtt_publish(PUBLISH_TOPIC, out.c_str());
}

// ---------------------------------------------------------------------------
// Shell commands
// ---------------------------------------------------------------------------
static void cmd_hx711(int argc, char** argv) {
    if (argc > 1 && strcmp(argv[1], "tare") == 0) {
        hx711_tare();
        hx711_save_calibration();
    } else if (argc > 1 && strcmp(argv[1], "read") == 0) {
        hx711_read_all();
        hx711_print_values();
    } else {
        Serial.println("usage: hx711 read|tare");
    }
}

static void cmd_stepper_cmd(int argc, char** argv) {
    if (argc > 2 && strcmp(argv[1], "set") == 0) {
        stepper_set_target(atol(argv[2]));
        Serial.printf("stepper target -> %ld\n", atol(argv[2]));
    } else if (argc > 1 && strcmp(argv[1], "get") == 0) {
        Serial.printf("position=%ld target=%ld\n", stepper_get_position(), stepper_get_target());
    } else {
        Serial.println("usage: stepper set <steps> | get");
    }
}

static void cmd_home(int, char**) {
    s_zeroCalibrated = true;
    zero_run();
    stepper_reset_position(0);
}

static void cmd_leds(int argc, char** argv) {
    if (argc > 1) {
        rgb_set_all(argv[1]);
    } else {
        Serial.println("usage: leds 1_green,2_yellow,3_red");
    }
}

static void cmd_status(int, char**) {
    Serial.printf("stepper: pos=%ld\n", stepper_get_position());
    Serial.printf("wifi:    %s\n", wifi_mgr_is_connected() ? "connected" : "disconnected");
    Serial.printf("mqtt:    %s\n", mqtt_is_connected() ? "connected" : "disconnected");
    Serial.printf("hx711:   errors=%d\n", hx711_get_error_count());
    Serial.printf("zero:    offset=%ld calibrated=%d\n", zero_get_offset(), s_zeroCalibrated);
}

// ---------------------------------------------------------------------------
// Stepper wait helper (passed to zero calibrator via callbacks)
// ---------------------------------------------------------------------------
static void wait_for_stepper(unsigned long timeout_ms) {
    unsigned long start = millis();
    while (stepper_is_moving() && millis() - start < timeout_ms) {
        stepper_loop();
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
    zero_run();
    stepper_reset_position(0);
    s_zeroCalibrated = true;

    shell_init();
    shell_register("stepper", "set <steps> | get", cmd_stepper_cmd);
    shell_register("hx711",   "read | tare",       cmd_hx711);
    shell_register("home",    "run zero calibration", cmd_home);
    shell_register("leds",    "<r,g,b>",          cmd_leds);
    shell_register("status",  "show all states",  cmd_status);

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
    shell_loop();

    // Auto-zero if no MQTT message for timeout period
    if (mqtt_is_connected() && s_mqttMsgSeen &&
        millis() - s_lastMqttMsg > MQTT_POSITION_TIMEOUT_MS &&
        !stepper_is_moving()) {
        Serial.println("[MAIN] MQTT timeout — zeroing stepper");
        stepper_set_target(0);
        s_lastMqttMsg = millis();
    }

    // Periodic publish
    static unsigned long lastPub = 0;
    if (millis() - lastPub >= PUBLISH_INTERVAL_MS) {
        lastPub = millis();
        publish_sensor_data();
    }
}
