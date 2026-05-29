#include <Arduino.h>

// RGB LEDs from original code
// Common cathode assumed:
// HIGH = ON, LOW = OFF
const int LED1_G = 13;
const int LED2_R = 19;
const int LED2_G = 21;
const int LED3_R = 5;

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

void setup() {
    Serial.begin(115200);

    pinMode(LED1_G, OUTPUT);
    pinMode(LED2_R, OUTPUT);
    pinMode(LED2_G, OUTPUT);
    pinMode(LED3_R, OUTPUT);

    Serial.println("RGB LED test started");

    set_leds("green");
}

void loop() {
    set_leds("green");
    Serial.println("green");
    delay(1000);

    set_leds("yellow");
    Serial.println("yellow");
    delay(1000);

    set_leds("red");
    Serial.println("red");
    delay(1000);
}
