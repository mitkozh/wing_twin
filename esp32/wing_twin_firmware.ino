#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "secrets.h"

// HX711 – 10 chips, shared SCK, alternating between A and B channels
// Chip   DOUT  A         B
//   0    GPIO14 root_0   root_1
//   1    GPIO12 root_2   root_3
//   2    GPIO26 root_4   root_5
//   3    GPIO25 middle_0 middle_1
//   4    GPIO33 middle_2 middle_3
//   5    GPIO18 middle_4 middle_5
//   6    GPIO22 tip_0    tip_1
//   7    GPIO23 tip_2    tip_3
//   8    GPIO4  tip_4    tip_5
//   9    GPIO15 dummy    spare
const int HX711_SCK = 27;

const int NUM_HX711_CHIPS = 10;
const int NUM_ACTIVE       = 18;
const int NUM_TOTAL_GAUGES = NUM_HX711_CHIPS * 2;

const int DOUT_ROOT_0      = 14;
const int DOUT_ROOT_45     = 12;
const int DOUT_ROOT_90     = 26;
const int DOUT_MIDDLE_0    = 25;
const int DOUT_MIDDLE_45   = 33;
const int DOUT_MIDDLE_90   = 18;
const int DOUT_TIP_0       = 22;
const int DOUT_TIP_45      = 23;
const int DOUT_TIP_90      = 4;
const int DOUT_DUMMY_GAUGE = 15;

const int HX711_DT_PINS[NUM_HX711_CHIPS] = {
    DOUT_ROOT_0, DOUT_ROOT_45, DOUT_ROOT_90,
    DOUT_MIDDLE_0, DOUT_MIDDLE_45, DOUT_MIDDLE_90,
    DOUT_TIP_0, DOUT_TIP_45, DOUT_TIP_90,
    DOUT_DUMMY_GAUGE
};

const char* CHANNEL_NAMES[NUM_TOTAL_GAUGES] = {
    "root_0", "root_1", "root_2", "root_3", "root_4", "root_5",
    "middle_0", "middle_1", "middle_2", "middle_3", "middle_4", "middle_5",
    "tip_0", "tip_1", "tip_2", "tip_3", "tip_4", "tip_5",
    "dummy", "spare"
};

// 3 LEDs: root (index 0), middle (1), tip (2)
// Each has R + G pins: R+HIGH,G=LOW=red, R+HIGH,G+HIGH=yellow, R=LOW,G+HIGH=green
const int LED_ROOT_R = 13;
const int LED_ROOT_G = 19;
const int LED_MID_R  = 21;
const int LED_MID_G  = 32;
const int LED_TIP_R  = 16;
const int LED_TIP_G  = 17;

// Set to -1 to disable stepper
const int STEPPER_STEP = -1;
const int STEPPER_DIR  = -1;

const char* PUBLISH_TOPIC   = "wing/sensors";
const char* SUBSCRIBE_TOPIC = "wing/control";

WiFiClient espClient;
PubSubClient mqttClient(espClient);

long rawValues[NUM_HX711_CHIPS] = {0};
long chipRawA[NUM_HX711_CHIPS] = {0};
long chipRawB[NUM_HX711_CHIPS] = {0};
float strainValues[NUM_TOTAL_GAUGES] = {0.0};
float strainOffset[NUM_TOTAL_GAUGES] = {0.0};
float strainScale = 1.0;

int stepperPosition = 0;
int stepperTarget = 0;

unsigned long lastPublish = 0;
const int PUBLISH_INTERVAL_MS = 200;

// Dual-channel read state machine:
// After power-up all chips default to channel A.
// Even reads (27p): read A data, switch next conversion to B.
// Odd reads  (25p): read B data, switch next conversion to A.
// Publish after every odd read (both A+B available).
unsigned int readCount = 0;

void init_hx711() {
    pinMode(HX711_SCK, OUTPUT);
    digitalWrite(HX711_SCK, LOW);
    for (int i = 0; i < NUM_HX711_CHIPS; i++) {
        pinMode(HX711_DT_PINS[i], INPUT_PULLUP);
    }
}

inline void pulse_sck_read(int bitPos) {
    digitalWrite(HX711_SCK, HIGH);
    delayMicroseconds(1);
    if (bitPos >= 0) {
        for (int i = 0; i < NUM_HX711_CHIPS; i++) {
            if (digitalRead(HX711_DT_PINS[i]) == HIGH) {
                rawValues[i] |= (1L << bitPos);
            }
        }
    }
    digitalWrite(HX711_SCK, LOW);
    delayMicroseconds(1);
}

bool read_all_channels() {
    for (int i = 0; i < NUM_HX711_CHIPS; i++) rawValues[i] = 0;

    int timeout = 10000;
    while (--timeout > 0) {
        bool allReady = true;
        for (int i = 0; i < NUM_HX711_CHIPS; i++) {
            if (digitalRead(HX711_DT_PINS[i]) != LOW) {
                allReady = false;
                break;
            }
        }
        if (allReady) break;
    }
    if (timeout <= 0) return false;

    for (int bit = 23; bit >= 0; bit--) pulse_sck_read(bit);

    // 27 pulses = next conversion on B, 25 pulses = next on A
    if (readCount % 2 == 0) {
        pulse_sck_read(-1); pulse_sck_read(-1); pulse_sck_read(-1);
        for (int i = 0; i < NUM_HX711_CHIPS; i++) {
            if (rawValues[i] & 0x800000) rawValues[i] |= 0xFF000000;
            chipRawA[i] = rawValues[i];
        }
    } else {
        pulse_sck_read(-1);
        for (int i = 0; i < NUM_HX711_CHIPS; i++) {
            if (rawValues[i] & 0x800000) rawValues[i] |= 0xFF000000;
            chipRawB[i] = rawValues[i];
        }
    }

    readCount++;
    return true;
}

void reconstruct_strain_values() {
    for (int i = 0; i < NUM_HX711_CHIPS; i++) {
        strainValues[i * 2]     = (chipRawA[i] - strainOffset[i * 2]) * strainScale;
        strainValues[i * 2 + 1] = (chipRawB[i] - strainOffset[i * 2 + 1]) * strainScale;
    }
}

void tare() {
    const int SAMPLES = 10;
    long accumA[NUM_HX711_CHIPS] = {0};
    long accumB[NUM_HX711_CHIPS] = {0};
    int countA = 0, countB = 0;

    readCount = 0;

    for (int s = 0; s < SAMPLES * 2; s++) {
        if (read_all_channels()) {
            if (readCount % 2 == 1) {
                for (int i = 0; i < NUM_HX711_CHIPS; i++) {
                    accumA[i] += chipRawA[i];
                    accumB[i] += chipRawB[i];
                }
                countA++;
                countB++;
            }
        }
        delay(100);
    }

    if (countA > 0 && countB > 0) {
        for (int i = 0; i < NUM_HX711_CHIPS; i++) {
            strainOffset[i * 2]     = (float)accumA[i] / countA;
            strainOffset[i * 2 + 1] = (float)accumB[i] / countB;
        }
    }
}

struct LedPins { int r; int g; };
const LedPins SECTION_LEDS[3] = {
    {LED_ROOT_R, LED_ROOT_G},
    {LED_MID_R,  LED_MID_G},
    {LED_TIP_R,  LED_TIP_G},
};

void init_leds() {
    for (int i = 0; i < 3; i++) {
        if (SECTION_LEDS[i].r >= 0) pinMode(SECTION_LEDS[i].r, OUTPUT);
        if (SECTION_LEDS[i].g >= 0) pinMode(SECTION_LEDS[i].g, OUTPUT);
    }
    set_all_leds("green");
}

void set_led(int index, const char* color) {
    if (index < 0 || index > 2) return;
    int rPin = SECTION_LEDS[index].r;
    int gPin = SECTION_LEDS[index].g;

    bool rState = LOW, gState = LOW;
    if (strcmp(color, "green") == 0)  { rState = LOW;  gState = HIGH; }
    else if (strcmp(color, "yellow") == 0) { rState = HIGH; gState = HIGH; }
    else if (strcmp(color, "red") == 0)    { rState = HIGH; gState = LOW; }

    if (rPin >= 0) digitalWrite(rPin, rState);
    if (gPin >= 0) digitalWrite(gPin, gState);
}

void set_all_leds(const char* color) {
    for (int i = 0; i < 3; i++) set_led(i, color);
}

void all_leds_off() {
    for (int i = 0; i < 3; i++) {
        if (SECTION_LEDS[i].r >= 0) digitalWrite(SECTION_LEDS[i].r, LOW);
        if (SECTION_LEDS[i].g >= 0) digitalWrite(SECTION_LEDS[i].g, LOW);
    }
}

void init_stepper() {
    if (STEPPER_STEP >= 0) { pinMode(STEPPER_STEP, OUTPUT); digitalWrite(STEPPER_STEP, LOW); }
    if (STEPPER_DIR >= 0)  { pinMode(STEPPER_DIR, OUTPUT);  digitalWrite(STEPPER_DIR, LOW);  }
}

void update_stepper() {
    if (STEPPER_STEP < 0 || STEPPER_DIR < 0) return;
    if (stepperPosition == stepperTarget) return;

    int dir = (stepperTarget > stepperPosition) ? HIGH : LOW;
    digitalWrite(STEPPER_DIR, dir);

    int rem = abs(stepperTarget - stepperPosition);
    int stepDelay = max(500, 2000 - rem * 3);
    int steps = min(rem, 50);

    for (int i = 0; i < steps; i++) {
        digitalWrite(STEPPER_STEP, HIGH);
        delayMicroseconds(stepDelay);
        digitalWrite(STEPPER_STEP, LOW);
        delayMicroseconds(stepDelay);
        stepperPosition += (dir == HIGH) ? 1 : -1;
    }
}

void mqtt_callback(char* topic, byte* payload, unsigned int length) {
    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) {
        Serial.print("JSON parse error: ");
        Serial.println(err.c_str());
        return;
    }

    if (doc.containsKey("position")) {
        stepperTarget = doc["position"].as<int>();
    }

    if (doc.containsKey("leds")) {
        JsonArray leds = doc["leds"].as<JsonArray>();
        int count = min((int)leds.size(), 3);
        for (int i = 0; i < count; i++) {
            const char* color = leds[i];
            if (strcmp(color, "green") == 0 || strcmp(color, "yellow") == 0 ||
                strcmp(color, "red") == 0 || strcmp(color, "off") == 0) {
                set_led(i, color);
            }
        }
    }
}

void mqtt_reconnect() {
    while (!mqttClient.connected()) {
        Serial.print("MQTT connecting...");
        String clientId = "ESP32-Wing-" + String(random(0xFFFF), HEX);
        if (mqttClient.connect(clientId.c_str())) {
            Serial.println("connected");
            mqttClient.subscribe(SUBSCRIBE_TOPIC);
        } else {
            Serial.print(" failed (rc=");
            Serial.print(mqttClient.state());
            Serial.println(") retry in 5s");
            delay(5000);
        }
    }
}

void publish_data() {
    char payload[768];
    int len = snprintf(payload, sizeof(payload), "{\"strain_vector\":[");

    for (int i = 0; i < NUM_ACTIVE; i++) {
        len += snprintf(payload + len, sizeof(payload) - len,
                        "%.3f%s", strainValues[i],
                        (i < NUM_ACTIVE - 1) ? "," : "");
    }
    len += snprintf(payload + len, sizeof(payload) - len, "],\"channels\":[");
    for (int i = 0; i < NUM_ACTIVE; i++) {
        len += snprintf(payload + len, sizeof(payload) - len,
                        "\"%s\"%s", CHANNEL_NAMES[i],
                        (i < NUM_ACTIVE - 1) ? "," : "");
    }
    snprintf(payload + len, sizeof(payload) - len,
             "],\"dummy_raw\":%.3f,\"timestamp\":%lu}",
             strainValues[NUM_ACTIVE], millis());

    mqttClient.publish(PUBLISH_TOPIC, payload);
}

void setup_wifi() {
    delay(10);
    Serial.print("Connecting to WiFi...");
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
    Serial.println("\nWiFi connected");
    Serial.print("IP: "); Serial.println(WiFi.localIP());
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n=== Wing Digital Twin ESP32 ===");
    Serial.print("HX711 chips: ");
    Serial.print(NUM_HX711_CHIPS);
    Serial.print(", total gauges: ");
    Serial.println(NUM_TOTAL_GAUGES);
    Serial.print("Active: ");
    Serial.println(NUM_ACTIVE);

    init_leds();
    Serial.println("LEDs initialized (green)");

    init_hx711();
    delay(100);
    tare();
    Serial.println("HX711 initialized and tared");

    init_stepper();

    setup_wifi();
    mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
    mqttClient.setCallback(mqtt_callback);

    Serial.println("=== System Ready ===");
}

void loop() {
    if (!mqttClient.connected()) mqtt_reconnect();
    mqttClient.loop();

    bool readOk = read_all_channels();
    if (readOk) {
        // Publish after odd reads: B was just stored, A was stored in the
        // preceding even read, so both A+B are current.
        if (readCount % 2 == 0) {
            reconstruct_strain_values();
            if (millis() - lastPublish >= PUBLISH_INTERVAL_MS) {
                publish_data();
                lastPublish = millis();
            }
        }
    }

    update_stepper();
    delay(5);
}
