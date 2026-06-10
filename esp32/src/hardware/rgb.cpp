#include "rgb.h"
#include "../pins.h"

// 3 feedback LEDs, each with red+green channels.
// LED1 = tip, LED2 = span, LED3 = root.
// Input format: "1_green,2_yellow,3_red"

static void set_one(int led, const char* colour) {
    bool g = false, r = false;
    if      (strcmp(colour, "green")  == 0) { g = true; }
    else if (strcmp(colour, "yellow") == 0) { g = true; r = true; }
    else if (strcmp(colour, "red")    == 0) { r = true; }
    switch (led) {
        case 1: digitalWrite(LED1_STATUS_GREEN, g ? HIGH : LOW); digitalWrite(LED1_STATUS_RED, r ? HIGH : LOW); break;
        case 2: digitalWrite(LED2_STATUS_GREEN, g ? HIGH : LOW); digitalWrite(LED2_STATUS_RED, r ? HIGH : LOW); break;
        case 3: digitalWrite(LED3_STATUS_GREEN, g ? HIGH : LOW); digitalWrite(LED3_STATUS_RED, r ? HIGH : LOW); break;
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
    char buf[64];
    strncpy(buf, command, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';
    for (int i = 0; buf[i]; i++) buf[i] = tolower((unsigned char)buf[i]);

    bool seen[4] = {false, false, false, false};
    int  cols[4] = {0, 0, 0, 0};

    char* part = strtok(buf, ",");
    while (part) {
        char* us = strchr(part, '_');
        if (!us || us == part) { Serial.println("[RGB] bad command"); return; }
        *us = '\0';
        int n = atoi(part);
        const char* c = us + 1;
        if (n < 1 || n > 3 || (strcmp(c, "green") != 0 && strcmp(c, "yellow") != 0 && strcmp(c, "red") != 0)) {
            Serial.println("[RGB] bad command"); return;
        }
        if (seen[n]) { Serial.println("[RGB] duplicate LED"); return; }
        seen[n] = true;
        if      (strcmp(c, "green")  == 0) cols[n] = 1;
        else if (strcmp(c, "yellow") == 0) cols[n] = 2;
        else if (strcmp(c, "red")    == 0) cols[n] = 3;
        part = strtok(NULL, ",");
    }
    for (int i = 1; i <= 3; i++) {
        if (seen[i]) {
            const char* colour = (cols[i] == 1) ? "green" : (cols[i] == 2) ? "yellow" : "red";
            set_one(i, colour);
        }
    }
    Serial.printf("[RGB] set: %s\n", command);
}


