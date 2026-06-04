#include "mqtt_control.h"

#include <WiFi.h>
#include <PubSubClient.h>

#include "secrets.h"
#include "RGB_control.h"

// =====================================================
// [KEEP IN mqtt_control.cpp]
// 正式保留：MQTT topics
//
// ESP32 publish sensor data to PUBLISH_TOPIC
// ESP32 subscribe server command from SUBSCRIBE_TOPIC
// =====================================================

const char* PUBLISH_TOPIC = "wing/sensors";
const char* SUBSCRIBE_TOPIC = "wing/control";


// =====================================================
// [KEEP IN mqtt_control.cpp]
// 正式保留：WiFi and MQTT client objects
// =====================================================

WiFiClient espClient;
PubSubClient mqttClient(espClient);


// =====================================================
// [KEEP IN mqtt_control.cpp]
// 正式保留：MQTT receive part
//
// 当电脑/server 发送消息到 wing/control 时，会进入这里。
//
// 当前 RGB_control 只接受完整三灯状态指令，例如：
// 1_green,2_green,3_green
// 1_red,2_yellow,3_green
// 1_yellow,2_red,3_red
//
// 所以这里不再单独判断 red / green / yellow。
// MQTT 只负责接收 message，然后交给 RGB_control 解析。
// =====================================================

void mqtt_callback(char* topic, byte* payload, unsigned int length) {
    String message = "";

    for (unsigned int i = 0; i < length; i++) {
        message += (char)payload[i];
    }

    message.trim();
    message.toLowerCase();

    Serial.print("[MQTT received] topic: ");
    Serial.print(topic);
    Serial.print(" | message: ");
    Serial.println(message);

    set_leds(message);
}


// =====================================================
// [KEEP IN mqtt_control.cpp]
// 正式保留：WiFi connection
// =====================================================

void setup_wifi() {
    Serial.print("Connecting to WiFi: ");
    Serial.println(WIFI_SSID);

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }

    Serial.println();
    Serial.println("WiFi connected.");

    Serial.print("ESP32 IP: ");
    Serial.println(WiFi.localIP());
}


// =====================================================
// [KEEP IN mqtt_control.cpp]
// 正式保留：MQTT connection / reconnect
//
// ESP32 会连接电脑上的 Mosquitto broker。
// 连接成功后订阅 wing/control，用于接收 server 指令。
// =====================================================

void mqtt_reconnect() {
    while (!mqttClient.connected()) {
        Serial.print("Connecting to MQTT broker ");
        Serial.print(MQTT_SERVER);
        Serial.print(":");
        Serial.println(MQTT_PORT);

        String clientId = "ESP32-Wing-" + String(random(0xffff), HEX);

        if (mqttClient.connect(clientId.c_str())) {
            Serial.println("MQTT connected.");

            mqttClient.subscribe(SUBSCRIBE_TOPIC);

            Serial.print("Subscribed to: ");
            Serial.println(SUBSCRIBE_TOPIC);
        }
        else {
            Serial.print("MQTT failed, rc = ");
            Serial.print(mqttClient.state());
            Serial.println(". Retry in 2 seconds.");

            delay(2000);
        }
    }
}


// =====================================================
// [KEEP IN mqtt_control.cpp]
// 正式保留：MQTT initialization
//
// 初始化 WiFi、设置 MQTT broker 地址、绑定 receive callback。
// =====================================================

void mqtt_init() {
    setup_wifi();

    mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
    mqttClient.setCallback(mqtt_callback);
}


// =====================================================
// [KEEP IN mqtt_control.cpp]
// 正式保留：MQTT loop
//
// main.cpp 或 mqtt_test.cpp 的 loop() 中必须持续调用。
// 不调用这个，ESP32 就收不到 wing/control 的指令。
// =====================================================

void mqtt_loop() {
    if (!mqttClient.connected()) {
        mqtt_reconnect();
    }

    mqttClient.loop();
}


// =====================================================
// [KEEP IN mqtt_control.cpp]
// 正式保留：MQTT transfer part
//
// 用于 mqtt_test.cpp。
// ESP32 将 fake sensor data 发送到 wing/sensors。
// =====================================================

void mqtt_publish_sensor(long raw, long diff, float voltage_mV) {
    char payload[200];

    snprintf(payload, sizeof(payload),
             "{\"raw\":%ld,\"diff\":%ld,\"voltage_mV\":%.6f,\"timestamp\":%lu}",
             raw,
             diff,
             voltage_mV,
             millis());

    bool ok = mqttClient.publish(PUBLISH_TOPIC, payload);

    if (ok) {
        Serial.print("[MQTT published sensor] ");
        Serial.println(payload);
    }
    else {
        Serial.println("[MQTT publish sensor failed]");
    }
}


// =====================================================
// [KEEP IN mqtt_control.cpp]
// 正式保留：MQTT transfer part
//
// 用于 final demo。
// Hx711_control.cpp 先构建完整 JSON payload，
// 然后 main.cpp 调用这个函数发送到 wing/sensors。
// =====================================================

void mqtt_publish_payload(const char* payload) {
    bool ok = mqttClient.publish(PUBLISH_TOPIC, payload);

    if (ok) {
        Serial.print("[MQTT published payload] ");
        Serial.println(payload);
    }
    else {
        Serial.println("[MQTT publish payload failed]");
    }
} 

 