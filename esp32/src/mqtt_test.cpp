#include <Arduino.h>
#include <WiFi.h>

#include "mqtt_control.h"
#include "RGB_control.h"
#include "secrets.h"

// =====================================================
// [TEST ONLY]
// 这个文件只用于单独测试 MQTT。
// final demo 时不要编译这个文件。
//
// 测试目标：
// 1. ESP32 能连接 WiFi
// 2. ESP32 能连接 MQTT broker
// 3. ESP32 能 publish fake sensor data 到 wing/sensors
// 4. ESP32 能 subscribe wing/control
// 5. 电脑发送 red/green/yellow/off 后，ESP32 控制 RGB
// =====================================================

unsigned long lastPublish = 0;
const unsigned long TEST_PUBLISH_INTERVAL_MS = 1000;


// =====================================================
// [TEST ONLY]
// 假 sensor 数据
//
// 这部分不需要拷贝到 final demo。
// final demo 中会用 Hx711_control.cpp 里的真实读数。
// =====================================================

long fakeRaw = 8000000;
long fakeDiff = 0;
float fakeVoltage_mV = 0.0;

void update_fake_sensor_data() {
    fakeDiff += 100;

    if (fakeDiff > 2000) {
        fakeDiff = -2000;
    }

    fakeRaw = 8000000 + fakeDiff;
    fakeVoltage_mV = fakeDiff * 20.0 / 8388607.0;
}


// =====================================================
// [TEST ONLY]
// setup()
// 只用于 mqtt_test.cpp。
// final demo 时只有 main.cpp 有 setup()。
// =====================================================

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("=== MQTT Module Test ===");

    // mqtt_control.cpp receives MQTT commands.
    // RGB_control.cpp parses the full three-LED command.
    rgb_init();
    set_leds("1_green,2_green,3_green");

    // Initialize WiFi + MQTT
    mqtt_init();

    // --- WiFi Scan: see which networks the ESP32 can see ---
    Serial.println("\n=== WiFi Scan ===");
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    delay(100);
    int n = WiFi.scanNetworks();
    Serial.print("Found ");
    Serial.print(n);
    Serial.println(" networks:");
    for (int i = 0; i < n; i++) {
        Serial.print("  ");
        Serial.print(i + 1);
        Serial.print(": ");
        Serial.print(WiFi.SSID(i));
        Serial.print(" (");
        Serial.print(WiFi.RSSI(i));
        Serial.print(" dBm) ");
        Serial.println(WiFi.encryptionType(i) == WIFI_AUTH_OPEN ? "open" : "secured");
    }
    if (n == 0) {
        Serial.println("  (no networks found - check ESP32 WiFi antenna/range)");
    }
    // Check if our target SSID is in the list
    bool found = false;
    for (int i = 0; i < n; i++) {
        if (WiFi.SSID(i) == WIFI_SSID) {
            found = true;
            break;
        }
    }
    if (found) {
        Serial.println(">>> Target SSID 'Canny iphone 8P' IS visible");
    } else {
        Serial.println(">>> Target SSID 'Canny iphone 8P' NOT visible - out of range?");
    }
    Serial.println("================\n");

    Serial.println("MQTT test ready.");
    Serial.println("ESP32 will publish fake sensor data to: wing/sensors");
    Serial.println("Server command topic: wing/control");

    Serial.println("Supported RGB command format:");
    Serial.println("1_colour,2_colour,3_colour");

    Serial.println("Examples:");
    Serial.println("1_green,2_green,3_green");
    Serial.println("1_yellow,2_yellow,3_yellow");
    Serial.println("1_red,2_red,3_red");
    Serial.println("1_red,2_yellow,3_green");
    Serial.println("1_green,2_red,3_yellow");
    Serial.println("1_yellow,2_green,3_red");
}



// =====================================================
// [TEST ONLY]
// loop()
// 只用于 mqtt_test.cpp。
// final demo 中 main.cpp 会负责：
// mqtt_loop();
// mqtt_publish_sensor(real HX711 data);
// =====================================================

void loop() {
    mqtt_loop();

    if (millis() - lastPublish >= TEST_PUBLISH_INTERVAL_MS) {
        lastPublish = millis();

        update_fake_sensor_data();

        mqtt_publish_sensor(fakeRaw, fakeDiff, fakeVoltage_mV);
    }
}