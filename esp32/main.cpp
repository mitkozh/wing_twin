#include <Arduino.h>

#include "RGB_control.h"
#include "Hx711_control.h"
#include "mqtt_control.h"

const unsigned long PUBLISH_INTERVAL_MS = 100;
unsigned long lastPublish = 0;

char sensorPayload[512];

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("=== Wing Digital Twin ESP32 Client ===");

    rgb_init();
    set_leds("green");
    Serial.println("RGB module initialized.");

    hx711_init();
    Serial.println("HX711 module initialized.");

    mqtt_init();
    Serial.println("MQTT module initialized.");

    Serial.println("System ready.");
}

void loop() {
    mqtt_loop();

    if (millis() - lastPublish >= PUBLISH_INTERVAL_MS) {
        lastPublish = millis();

        bool readOk = hx711_read_all_channels();

        if (readOk) {
            hx711_build_sensor_payload(sensorPayload, sizeof(sensorPayload));
            mqtt_publish_payload(sensorPayload);
        } else {
            Serial.println("[HX711] Read failed.");
            set_leds("yellow");
        }
    }
}
