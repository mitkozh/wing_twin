#include "stepper.h"
#include "../pins.h"
#include "../config.h"

static long s_position = 0;
static long s_target   = 0;
static long s_stepsTaken = 0;
static unsigned long s_lastStep = 0;
static unsigned long s_rate = STEPPER_MAX_RATE_US;
static bool s_enabled = true;

void stepper_init(void) {
    pinMode(STEP_PIN, OUTPUT);
    pinMode(DIR_PIN, OUTPUT);
    pinMode(ENABLE_PIN, OUTPUT);
    digitalWrite(STEP_PIN, LOW);
    digitalWrite(DIR_PIN, LOW);
    digitalWrite(ENABLE_PIN, LOW);
    s_position = 0;
    s_target = 0;
    s_lastStep = micros();
    s_rate = STEPPER_MAX_RATE_US;
    Serial.println("[STEPPER] init done");
}

void stepper_set_target(long steps) {
    if (steps < STEPPER_MIN_POSITION) steps = STEPPER_MIN_POSITION;
    if (steps > STEPPER_MAX_POSITION) steps = STEPPER_MAX_POSITION;
    s_target = steps;
    s_stepsTaken = 0;
}

void stepper_reset_position(long pos) {
    s_position = pos;
    s_target = pos;
    s_stepsTaken = 0;
}

long stepper_get_position(void) {
    return s_position;
}

long stepper_get_target(void) {
    return s_target;
}

bool stepper_is_moving(void) {
    return abs(s_position - s_target) > STEPPER_POSITION_TOLERANCE;
}

void stepper_enable(bool on) {
    s_enabled = on;
    digitalWrite(ENABLE_PIN, on ? LOW : HIGH);
}

void stepper_loop(void) {
    if (!s_enabled) return;
    long diff = s_target - s_position;
    if (abs(diff) <= STEPPER_POSITION_TOLERANCE) {
        s_rate = STEPPER_MAX_RATE_US;
        return;
    }
    unsigned long now = micros();
    if (now - s_lastStep < s_rate) return;
    s_lastStep = now;
    long remain = abs(diff);
    long ramp = min(s_stepsTaken, remain);
    if (ramp < STEPPER_ACCEL_STEPS) {
        float frac = (float)ramp / STEPPER_ACCEL_STEPS;
        s_rate = STEPPER_MAX_RATE_US + (unsigned long)((STEPPER_MIN_RATE_US - STEPPER_MAX_RATE_US) * (1.0f - frac));
    } else {
        s_rate = STEPPER_MAX_RATE_US;
    }
    if (diff > 0) {
        digitalWrite(DIR_PIN, HIGH);
        s_position++;
    } else {
        digitalWrite(DIR_PIN, LOW);
        s_position--;
    }
    s_stepsTaken++;
    if (s_position <= STEPPER_MIN_POSITION || s_position >= STEPPER_MAX_POSITION) {
        s_target = s_position;
    }
    digitalWrite(STEP_PIN, HIGH);
    delayMicroseconds(5);
    digitalWrite(STEP_PIN, LOW);
}
