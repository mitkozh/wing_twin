#include "RGB_control.h"

const int LED_STATUS_GREEN = 13;
const int LED_STATUS_YELLOW_R = 19; //these pins were comfimed
const int LED_STATUS_YELLOW_G = 21;
const int LED_STATUS_RED = 32;

void rgb_init() {
    pinMode(LED_STATUS_GREEN, OUTPUT);
    pinMode(LED_STATUS_YELLOW_R, OUTPUT);
    pinMode(LED_STATUS_YELLOW_G, OUTPUT);
    pinMode(LED_STATUS_RED, OUTPUT);

    all_leds_off();
}

void all_leds_off() {
    digitalWrite(LED_STATUS_GREEN, LOW);
    digitalWrite(LED_STATUS_YELLOW_R, LOW);
    digitalWrite(LED_STATUS_YELLOW_G, LOW);
    digitalWrite(LED_STATUS_RED, LOW);
}

void set_leds(String state) {
    state.trim();
    state.toLowerCase();

    all_leds_off();

    if (state == "green") {
        digitalWrite(LED_STATUS_GREEN, HIGH);
    }
    else if (state == "yellow") {
        digitalWrite(LED_STATUS_YELLOW_R, HIGH);
        digitalWrite(LED_STATUS_YELLOW_G, HIGH);
    }
    else if (state == "red") {
        digitalWrite(LED_STATUS_RED, HIGH);
    }
    else if (state == "off") {
        all_leds_off();
    }
}
//expected received string

void print_rgb_pin_info() {
    Serial.println("RGB feedback pin mapping:");
    Serial.print("GREEN  -> GPIO ");
    Serial.println(LED_STATUS_GREEN);

    Serial.print("YELLOW R -> GPIO ");
    Serial.println(LED_STATUS_YELLOW_R);

    Serial.print("YELLOW G -> GPIO ");
    Serial.println(LED_STATUS_YELLOW_G);

    Serial.print("RED    -> GPIO ");
    Serial.println(LED_STATUS_RED);
}
