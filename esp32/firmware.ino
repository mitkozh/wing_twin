/*
 * Wing Digital Twin - ESP32 Firmware v1.0
 * Reads strain gauges (HX711), IMU (MPU-6050), publishes to MQTT
 * Subscribes to control messages for servo PWM and LED state
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <HX711.h>
#include <Servo.h>

// ============== CONFIGURATION ==============
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

const char* MQTT_SERVER = "192.168.1.100";
const int MQTT_PORT = 1883;

const char* PUBLISH_TOPIC = "wing/sensors";
const char* SUBSCRIBE_TOPIC = "wing/control";

const int MPU_ADDRESS = 0x68;

// ============== PINS ==============
const int HX711_DT = 4;
const int HX711_SCK = 5;
const int MPU_SDA = 21;
const int MPU_SCL = 22;
const int SERVO_PIN = 13;
const int LED_GREEN = 25;
const int LED_YELLOW = 26;
const int LED_RED = 27;

// ============== GLOBALS ==============
WiFiClient espClient;
PubSubClient mqttClient(espClient);
HX711 scale;
Servo servo;

int16_t accelX, accelY, accelZ;
int16_t gyroX, gyroY, gyroZ;

int servoPosition = 90;
int targetPosition = 90;
float strainScale = 1.0;
float strainOffset = 0.0;

// ============== SETUP ==============
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

void mqtt_callback(char* topic, byte* payload, unsigned int length) {
    payload[length] = '\0';
    String message = String((char*)payload);
    Serial.print("Message [");
    Serial.print(topic);
    Serial.print("] ");
    Serial.println(message);

    if (message.indexOf("servo") >= 0) {
        int pos = message.substring(message.indexOf("servo") + 7).toInt();
        targetPosition = constrain(pos, 0, 180);
    }
    if (message.indexOf("green") >= 0) set_leds("green");
    else if (message.indexOf("yellow") >= 0) set_leds("yellow");
    else if (message.indexOf("red") >= 0) set_leds("red");
}

void mqtt_reconnect() {
    while (!mqttClient.connected()) {
        Serial.print("MQTT connection...");
        String clientId = "ESP32-Wing-" + String(random(1000));
        
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

void mpu_setup() {
    Wire.begin(MPU_SDA, MPU_SCL);
    Wire.beginTransmission(MPU_ADDRESS);
    Wire.write(0x6B);
    Wire.write(0);
    Wire.endTransmission(true);
    Serial.println("MPU-6050 initialized");
}

void mpu_read() {
    Wire.beginTransmission(MPU_ADDRESS);
    Wire.write(0x3B);
    Wire.endTransmission(false);
    Wire.requestFrom(MPU_ADDRESS, 6, true);
    accelX = Wire.read() << 8 | Wire.read();
    accelY = Wire.read() << 8 | Wire.read();
    accelZ = Wire.read() << 8 | Wire.read();
    
    Wire.beginTransmission(MPU_ADDRESS);
    Wire.write(0x43);
    Wire.endTransmission(false);
    Wire.requestFrom(MPU_ADDRESS, 6, true);
    gyroX = Wire.read() << 8 | Wire.read();
    gyroY = Wire.read() << 8 | Wire.read();
    gyroZ = Wire.read() << 8 | Wire.read();
}

void set_leds(String state) {
    digitalWrite(LED_GREEN, state == "green" ? HIGH : LOW);
    digitalWrite(LED_YELLOW, state == "yellow" ? HIGH : LOW);
    digitalWrite(LED_RED, state == "red" ? HIGH : LOW);
}

float read_strain() {
    if (scale.is_ready()) {
        long raw = scale.read();
        return (raw - strainOffset) * strainScale;
    }
    return 0.0;
}

void publish_data() {
    float strain = read_strain();
    mpu_read();
    unsigned long ts = millis();
    
    char payload[128];
    snprintf(payload, sizeof(payload),
        "{\"strain\":%.2f,\"accel_z\":%d,\"gyro_z\":%d,\"timestamp\":%lu}",
        strain, accelZ, gyroZ, ts);
    
    mqttClient.publish(PUBLISH_TOPIC, payload);
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    
    pinMode(LED_GREEN, OUTPUT);
    pinMode(LED_YELLOW, OUTPUT);
    pinMode(LED_RED, OUTPUT);
    set_leds("green");
    
    scale.begin(HX711_DT, HX711_SCK);
    scale.set_scale(2280.0);
    scale.tare();
    
    servo.attach(SERVO_PIN);
    servo.write(servoPosition);
    
    mpu_setup();
    
    setup_wifi();
    mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
    mqttClient.setCallback(mqtt_callback);
    
    Serial.println("\n=== Wing Digital Twin Ready ===");
}

void loop() {
    if (!mqttClient.connected()) mqtt_reconnect();
    mqttClient.loop();
    
    if (servoPosition != targetPosition) {
        servoPosition += (servoPosition < targetPosition) ? 1 : -1;
        servo.write(servoPosition);
    }
    
    static unsigned long lastPub = 0;
    if (millis() - lastPub > 100) {
        publish_data();
        lastPub = millis();
    }
    
    delay(10);
}