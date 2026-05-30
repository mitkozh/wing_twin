#include "mqtt_control.h"

#include <WiFi.h>
#include <PubSubClient.h>

#include "secrets.h"
#include "RGB_control.h"

const char* PUBLISH_TOPIC = "wing/sensors";
const char* SUBSCRIBE_TOPIC = "wing/control";

WiFiClient espClient;
PubSubClient mqttClient(espClient);


// MQTT reception: server -> ESP32(client)
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

    if (message == "red") {
        set_leds("red");
    }
    else if (message == "green") {
        set_leds("green");
    }
    else if (message == "yellow") {
        set_leds("yellow");
    }
    else if (message == "off") {
        all_leds_off();
    }
    else {
        Serial.println("Unknown MQTT command.");
    }
}


// WiFi connection
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


// MQTT connection
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


// MQTT setup
void mqtt_init() {
    setup_wifi();

    mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
    mqttClient.setCallback(mqtt_callback);
}


void mqtt_loop() {
    if (!mqttClient.connected()) {
        mqtt_reconnect();
    }

    mqttClient.loop();
}


// MQTT transmission: ESP32(client) -> server
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
