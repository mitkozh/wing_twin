#include <Arduino.h>
#include "esp_task_wdt.h"

#include "RGB_control.h"
#include "Hx711_control.h"
#include "mqtt_control.h"
// #include "Stepper_control.h"


// =====================================================
// Publish interval — send sensor data every 1 second
// =====================================================
unsigned long lastPublishTime = 0;
const unsigned long PUBLISH_INTERVAL = 1000;

// =====================================================
// Watchdog timeout — if loop() blocks for 5s, reset
// =====================================================
const unsigned long WATCHDOG_TIMEOUT_MS = 5000;


// =====================================================
// [SETUP]
// =====================================================

void setup() {
    Serial.begin(115200);
    delay(500);

    Serial.println();
    Serial.println("=================================");
    Serial.println(" ESP32 Wing Digital Twin Node");
    Serial.println(" HX711 + MQTT + RGB + Stepper");
    Serial.println("=================================");

    // --- RGB LEDs ---
    rgb_init();
    set_leds("1_green,2_green,3_green");

    // --- Stepper motor ---
    // stepper_init();

    // --- HX711 strain gauges ---
    hx711_init();

    // --- WiFi + MQTT ---
    mqtt_init();

    Serial.println("System initialization finished.");
    print_rgb_pin_info();
    hx711_print_pin_info();

    // Enable hardware watchdog
    esp_task_wdt_init(WATCHDOG_TIMEOUT_MS / 1000, true);
    esp_task_wdt_add(NULL);
}


// =====================================================
// [LOOP]
// =====================================================

void loop() {
    esp_task_wdt_reset();

    // --- 1. MQTT housekeeping (reconnect + callback processing) ---
    mqtt_loop();

    // --- 2. Stepper motor (move toward target position) ---
    // stepper_loop();

    // --- 3. Periodic HX711 read + publish ---
    if (millis() - lastPublishTime >= PUBLISH_INTERVAL) {
        lastPublishTime = millis();

        bool readOk = hx711_read_all_channels();

        if (!readOk) {
            Serial.print("[HX711] Read error count: ");
            Serial.println(hx711_get_read_error_count());

            if (hx711_get_read_error_count() > 5) {
                Serial.println("[HX711] Too many consecutive errors — skipping publish");
            }
        }

        hx711_print_latest_values();

        char payload[1000];
        hx711_build_sensor_payload(payload, sizeof(payload));
        mqtt_publish_payload(payload);
    }
}
