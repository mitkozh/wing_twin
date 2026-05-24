/*
 * Wing Digital Twin - ESP32 Firmware v2.0
 *
 * Hardware:
 *   - 9 strain gauges in half-bridge Wheatstone config, each via dedicated HX711
 *   - 1 dummy strain gauge + HX711 for temperature compensation
 *   - All 10 HX711 share a common SCK and power; each has an independent DT pin
 *   - Stepper motor with step/direction driver
 *   - 3 RGB LEDs (common cathode)
 *
 * Publishing: {"strain_vector":[...], "timestamp":...} on wing/sensors @ 10 Hz
 * Subscribing: wing/control for stepper steps and LED state
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include "secrets.h"

// WiFi / MQTT
const char* PUBLISH_TOPIC = "wing/sensors";
const char* SUBSCRIBE_TOPIC = "wing/control";

// HX711
const int NUM_ACTIVE = 9;
const int NUM_CHANNELS = 10;  // 9 active + 1 dummy
const int HX711_DT_PINS[NUM_CHANNELS] = {4, 12, 13, 14, 15, 16, 17, 18, 19, 21};
const int HX711_SCK = 5;

// Stepper motor
const int STEPPER_STEP = 22;
const int STEPPER_DIR = 23;

// RGB LEDs (common cathode, assumed). All colour channels are software-tied
// LOW as fallback in case the hardware GND connection on unused pins is loose.
//   LED1 = green (only G driven)
//   LED2 = yellow (R+G driven)
//   LED3 = red   (only R driven)
//   Unused colour channels on each LED are hardware-tied to GND, not connected to MCU.
const int LED1_G = 25;
const int LED2_R = 26;
const int LED2_G = 27;
const int LED3_R = 32;

// Globals
WiFiClient espClient;
PubSubClient mqttClient(espClient);

long rawValues[NUM_CHANNELS] = {0};
float strains[NUM_ACTIVE] = {0.0};
float strainOffset[NUM_ACTIVE] = {0.0};
float strainScale = 1.0;

int stepperPosition = 0;
int stepperTarget = 0;

unsigned long lastPublish = 0;
const int PUBLISH_INTERVAL_MS = 100;  // 10 Hz

// HX711 shared-SCK read

void init_hx711() {
    pinMode(HX711_SCK, OUTPUT);
    digitalWrite(HX711_SCK, LOW);
    for (int i = 0; i < NUM_CHANNELS; i++) {
        pinMode(HX711_DT_PINS[i], INPUT_PULLUP);
    }
}

// Pulse SCK low->high->low. When bitPos >= 0, reads each DOUT after the rising
// edge (the bit at that position has just been shifted out) and stores it.
inline void pulse_sck_read(int bitPos) {
    digitalWrite(HX711_SCK, HIGH);
    delayMicroseconds(1);
    if (bitPos >= 0) {
        for (int i = 0; i < NUM_CHANNELS; i++) {
            if (digitalRead(HX711_DT_PINS[i]) == HIGH) {
                rawValues[i] |= (1L << bitPos);
            }
        }
    }
    digitalWrite(HX711_SCK, LOW);
    delayMicroseconds(1);
}

// Read all 10 HX711 channels simultaneously via shared SCK.
// Returns true if all channels were ready, false on timeout.
bool read_all_channels() {
    // Wait until every DOUT goes low (data ready).
    int timeout = 10000;
    while (--timeout > 0) {
        bool allReady = true;
        for (int i = 0; i < NUM_CHANNELS; i++) {
            if (digitalRead(HX711_DT_PINS[i]) != LOW) {
                allReady = false;
                break;
            }
        }
        if (allReady) break;
    }
    if (timeout <= 0) {
        for (int i = 0; i < NUM_CHANNELS; i++) rawValues[i] = 0;
        return false;
    }

    // Read 24 bits MSB first
    for (int i = 0; i < NUM_CHANNELS; i++) rawValues[i] = 0;

    for (int bit = 23; bit >= 0; bit--) {
        pulse_sck_read(bit);
    }

    // 25th pulse sets gain to 128 for the next conversion on all chips.
    pulse_sck_read(-1);

    // Sign-extend from 24-bit two's complement to 32-bit signed
    for (int i = 0; i < NUM_CHANNELS; i++) {
        if (rawValues[i] & 0x800000) {
            rawValues[i] |= 0xFF000000;
        }
    }

    return true;
}

// Temperature compensation. Subtract dummy gauge from all active channels.
void compensate_temperature() {
    long dummy = rawValues[NUM_CHANNELS - 1];
    for (int i = 0; i < NUM_ACTIVE; i++) {
        long compensated = rawValues[i] - dummy;
        strains[i] = (compensated - strainOffset[i]) * strainScale;
    }
}

// Tare: average N readings to establish zero offset per channel.
void tare() {
    const int SAMPLES = 10;
    long accum[NUM_ACTIVE] = {0};

    for (int s = 0; s < SAMPLES; s++) {
        if (read_all_channels()) {
            for (int i = 0; i < NUM_ACTIVE; i++) {
                accum[i] += rawValues[i] - rawValues[NUM_CHANNELS - 1];
            }
        }
        delay(10);
    }

    for (int i = 0; i < NUM_ACTIVE; i++) {
        strainOffset[i] = (float)accum[i] / SAMPLES;
    }
}

// Stepper motor

void init_stepper() {
    pinMode(STEPPER_STEP, OUTPUT);
    pinMode(STEPPER_DIR, OUTPUT);
    digitalWrite(STEPPER_DIR, LOW);
    digitalWrite(STEPPER_STEP, LOW);
}

void update_stepper() {
    if (stepperPosition == stepperTarget) return;

    int dir = (stepperTarget > stepperPosition) ? HIGH : LOW;
    digitalWrite(STEPPER_DIR, dir);

    int steps = abs(stepperTarget - stepperPosition);
    int stepDelay = 2000;
    if (steps > 500) stepDelay = 800;

    for (int i = 0; i < min(steps, 50); i++) {
        digitalWrite(STEPPER_STEP, HIGH);
        delayMicroseconds(stepDelay);
        digitalWrite(STEPPER_STEP, LOW);
        delayMicroseconds(stepDelay);
        stepperPosition += (dir == HIGH) ? 1 : -1;
    }
}

// LEDs

void set_leds(String state) {
    digitalWrite(LED1_G, LOW);
    digitalWrite(LED2_R, LOW);
    digitalWrite(LED2_G, LOW);
    digitalWrite(LED3_R, LOW);

    if (state == "green")
        digitalWrite(LED1_G, HIGH);
    else if (state == "yellow") {
        digitalWrite(LED2_R, HIGH);
        digitalWrite(LED2_G, HIGH);
    }
    else if (state == "red")
        digitalWrite(LED3_R, HIGH);
}

// MQTT

void mqtt_callback(char* topic, byte* payload, unsigned int length) {
    payload[length] = '\0';
    String message = String((char*)payload);
    Serial.print("Message [");
    Serial.print(topic);
    Serial.print("] ");
    Serial.println(message);

    int idx;

    idx = message.indexOf("\"steps\"");
    if (idx >= 0) {
        int colon = message.indexOf(':', idx + 7);
        int comma = message.indexOf(',', colon + 1);
        String val = message.substring(colon + 1);
        if (comma >= 0) val = message.substring(colon + 1, comma);
        val.trim();
        stepperTarget += val.toInt();
        return;
    }

    idx = message.indexOf("\"position\"");
    if (idx >= 0) {
        int colon = message.indexOf(':', idx + 9);
        int comma = message.indexOf(',', colon + 1);
        String val = message.substring(colon + 1);
        if (comma >= 0) val = message.substring(colon + 1, comma);
        val.trim();
        stepperTarget = val.toInt();
        return;
    }

    idx = message.indexOf("\"led\"");
    if (idx >= 0) {
        int colon = message.indexOf(':', idx + 5);
        int bracket = message.indexOf('}', colon + 1);
        String val = message.substring(colon + 1);
        if (bracket >= 0) val = message.substring(colon + 1, bracket);
        val.replace("\"", "");
        val.trim();
        val.toLowerCase();
        set_leds(val);
    }
}

void mqtt_reconnect() {
    while (!mqttClient.connected()) {
        Serial.print("MQTT connection...");
        String clientId = "ESP32-Wing-" + String(random(0xFFFF), HEX);
        if (mqttClient.connect(clientId.c_str())) {
            Serial.println("connected");
            mqttClient.subscribe(SUBSCRIBE_TOPIC);
        } else {
            Serial.print(" failed (");
            Serial.print(mqttClient.state());
            Serial.println(") retry in 5s");
            delay(5000);
        }
    }
}

// Publish

void publish_data() {
    unsigned long ts = millis();

    char payload[256];
    int len = snprintf(payload, sizeof(payload), "{\"strain_vector\":[");
    for (int i = 0; i < NUM_ACTIVE; i++) {
        len += snprintf(payload + len, sizeof(payload) - len,
                        "%.2f%s", strains[i], (i < NUM_ACTIVE - 1) ? "," : "");
    }
    snprintf(payload + len, sizeof(payload) - len, "],\"timestamp\":%lu}", ts);

    mqttClient.publish(PUBLISH_TOPIC, payload);
}

// WiFi

void setup_wifi() {
    delay(10);
    Serial.println();
    Serial.print("Connecting to WiFi: ");
    Serial.println(WIFI_SSID);

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }

    Serial.println("\nWiFi connected");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n\n=== Wing Digital Twin ===");
    Serial.print("Channels: ");
    Serial.print(NUM_ACTIVE);
    Serial.print(" active + 1 dummy = ");
    Serial.println(NUM_CHANNELS);

    // LEDs
    pinMode(LED1_G, OUTPUT);
    pinMode(LED2_R, OUTPUT);
    pinMode(LED2_G, OUTPUT);
    pinMode(LED3_R, OUTPUT);
    set_leds("green");

    // HX711 array (shared SCK)
    init_hx711();
    delay(100);
    tare();
    // NOTE: strainScale is currently 1.0 (raw ADC counts, not microstrain).
    // Before use, calibrate by applying a known load, computing expected
    // microstrain from beam theory (epsilon = F*L / (E*I * distance)),
    // then set: strainScale = expected_microstrain / measured_raw_count
    // The Python pipeline expects microstrain (ue) input.
    Serial.println("HX711 array initialized and tared");

    // Stepper
    init_stepper();
    Serial.println("Stepper initialized");

    // WiFi / MQTT
    setup_wifi();
    mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
    mqttClient.setCallback(mqtt_callback);

    Serial.println("=== Ready ===");
}

void loop() {
    if (!mqttClient.connected()) mqtt_reconnect();
    mqttClient.loop();

    bool ok = read_all_channels();
    if (ok) compensate_temperature();

    update_stepper();

    if (millis() - lastPublish >= PUBLISH_INTERVAL_MS) {
        if (ok) publish_data();
        lastPublish = millis();
    }

    delay(5);
}
