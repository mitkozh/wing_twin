#include "rgb.h"
#include "../pins.h"

// 3 feedback LEDs, each with red+green channels.
// LED1 = tip, LED2 = span, LED3 = root.
// Input format: "1_green,2_yellow,3_red"

static void set_one(int led, const String& colour) {
    switch (led) {
        case 1:
            digitalWrite(LED1_STATUS_GREEN, LOW); digitalWrite(LED1_STATUS_RED, LOW);
            if (colour == "green")  digitalWrite(LED1_STATUS_GREEN, HIGH);
            else if (colour == "yellow") { digitalWrite(LED1_STATUS_GREEN, HIGH); digitalWrite(LED1_STATUS_RED, HIGH); }
            else if (colour == "red")   digitalWrite(LED1_STATUS_RED, HIGH);
            break;
        case 2:
            digitalWrite(LED2_STATUS_GREEN, LOW); digitalWrite(LED2_STATUS_RED, LOW);
            if (colour == "green")  digitalWrite(LED2_STATUS_GREEN, HIGH);
            else if (colour == "yellow") { digitalWrite(LED2_STATUS_GREEN, HIGH); digitalWrite(LED2_STATUS_RED, HIGH); }
            else if (colour == "red")   digitalWrite(LED2_STATUS_RED, HIGH);
            break;
        case 3:
            digitalWrite(LED3_STATUS_GREEN, LOW); digitalWrite(LED3_STATUS_RED, LOW);
            if (colour == "green")  digitalWrite(LED3_STATUS_GREEN, HIGH);
            else if (colour == "yellow") { digitalWrite(LED3_STATUS_GREEN, HIGH); digitalWrite(LED3_STATUS_RED, HIGH); }
            else if (colour == "red")   digitalWrite(LED3_STATUS_RED, HIGH);
            break;
    }
}

void rgb_init(void) {
    pinMode(LED1_STATUS_GREEN, OUTPUT); pinMode(LED1_STATUS_RED, OUTPUT);
    pinMode(LED2_STATUS_RED, OUTPUT);   pinMode(LED2_STATUS_GREEN, OUTPUT);
    pinMode(LED3_STATUS_GREEN, OUTPUT); pinMode(LED3_STATUS_RED, OUTPUT);
    rgb_all_off();
}

void rgb_all_off(void) {
    digitalWrite(LED1_STATUS_GREEN, LOW); digitalWrite(LED1_STATUS_RED, LOW);
    digitalWrite(LED2_STATUS_RED, LOW);   digitalWrite(LED2_STATUS_GREEN, LOW);
    digitalWrite(LED3_STATUS_GREEN, LOW); digitalWrite(LED3_STATUS_RED, LOW);
}

void rgb_set_all(const char* command) {
    String cmd(command);
    cmd.trim(); cmd.toLowerCase();
    bool seen[4] = {false,false,false,false};
    int cols[4] = {0,0,0,0};
    int pos = 0;
    while (pos < (int)cmd.length()) {
        int comma = cmd.indexOf(',', pos);
        String part = (comma == -1) ? cmd.substring(pos) : cmd.substring(pos, comma);
        pos = (comma == -1) ? cmd.length() : comma + 1;
        part.trim();
        int us = part.indexOf('_');
        if (us <= 0) { Serial.println("[RGB] bad command"); return; }
        int n = part.substring(0, us).toInt();
        String c = part.substring(us + 1);
        if (n < 1 || n > 3 || (c != "green" && c != "yellow" && c != "red")) {
            Serial.println("[RGB] bad command"); return;
        }
        if (seen[n]) { Serial.println("[RGB] duplicate LED"); return; }
        seen[n] = true;
        if (c == "green")      cols[n] = 1;
        else if (c == "yellow") cols[n] = 2;
        else if (c == "red")    cols[n] = 3;
    }
    for (int i = 1; i <= 3; i++) {
        if (seen[i]) {
            const char* colour =
                cols[i] == 1 ? "green" :
                cols[i] == 2 ? "yellow" :
                cols[i] == 3 ? "red" : "";
            set_one(i, colour);
        }
    }
    Serial.printf("[RGB] set: %s\n", command);
}

void rgb_print_pins(void) {
    Serial.println("RGB pins:");
    Serial.printf("  LED1/tip   green=GPIO%d red=GPIO%d\n", LED1_STATUS_GREEN, LED1_STATUS_RED);
    Serial.printf("  LED2/span  green=GPIO%d red=GPIO%d\n", LED2_STATUS_GREEN, LED2_STATUS_RED);
    Serial.printf("  LED3/root  green=GPIO%d red=GPIO%d\n", LED3_STATUS_GREEN, LED3_STATUS_RED);
}
