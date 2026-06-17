#include "stepper.h"
#include "../pins.h"
#include "../config.h"
#include <AccelStepper.h>
#include <Preferences.h>

static AccelStepper s_stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);
static long s_target = 0;
static bool s_enabled = true;
static bool s_pos_saved = false;
static long s_effective_max_pos = STEPPER_MAX_POSITION;

static const char* PREFS_NS = "stepper";
static Preferences s_prefs;
static bool s_prefs_open = false;

void stepper_init(void) {
    pinMode(ENABLE_PIN, OUTPUT);
    digitalWrite(ENABLE_PIN, HIGH);
    delay(100);
    s_prefs_open = s_prefs.begin(PREFS_NS, false);
    s_stepper.setMaxSpeed(STEPPER_MAX_SPEED);
    s_stepper.setAcceleration(STEPPER_ACCELERATION);
    s_stepper.setCurrentPosition(0);
    s_target = 0;
    digitalWrite(ENABLE_PIN, LOW);
    Serial.println("[STEPPER] init done");
}

void stepper_set_target(long steps) {
    if (steps < STEPPER_MIN_POSITION) steps = STEPPER_MIN_POSITION;
    if (steps > s_effective_max_pos) steps = s_effective_max_pos;
    s_target = steps;
    s_stepper.moveTo(steps);
    stepper_set_dirty(true);
}

void stepper_set_max_position(long pos) {
    if (pos < STEPPER_MIN_POSITION) pos = STEPPER_MIN_POSITION;
    if (pos > STEPPER_ABSOLUTE_MAX_POSITION) pos = STEPPER_ABSOLUTE_MAX_POSITION;
    s_effective_max_pos = pos;
    Serial.printf("[STEPPER] max position set to %ld\n", pos);
}

long stepper_get_max_position(void) {
    return s_effective_max_pos;
}

long stepper_get_absolute_max_position(void) {
    return STEPPER_ABSOLUTE_MAX_POSITION;
}

void stepper_set_max_speed(float steps_per_sec) {
    s_stepper.setMaxSpeed(steps_per_sec);
}

void stepper_set_acceleration(float steps_per_sec2) {
    s_stepper.setAcceleration(steps_per_sec2);
}


void stepper_reset_position(long pos) {
    s_stepper.setCurrentPosition(pos);
    s_target = pos;
}

long stepper_get_position(void) {
    return s_stepper.currentPosition();
}

long stepper_get_target(void) {
    return s_target;
}

bool stepper_is_moving(void) {
    return abs(s_stepper.currentPosition() - s_target) > STEPPER_POSITION_TOLERANCE;
}

void stepper_enable(bool on) {
    s_enabled = on;
    digitalWrite(ENABLE_PIN, on ? LOW : HIGH);
}

bool stepper_is_enabled(void) {
    return s_enabled;
}

void stepper_loop(void) {
    if (!s_enabled) return;
    s_stepper.run();
    long pos = s_stepper.currentPosition();

    if (pos <= STEPPER_MIN_POSITION || pos >= STEPPER_ABSOLUTE_MAX_POSITION) {
        long clamped = constrain(pos, STEPPER_MIN_POSITION, STEPPER_ABSOLUTE_MAX_POSITION);
        s_stepper.moveTo(clamped);
        s_target = clamped;
    }

    if (stepper_is_moving()) {
        stepper_set_dirty(true);
        s_pos_saved = false;
        return;
    }

    if (!s_pos_saved) {
        stepper_save_position();
        stepper_set_dirty(false);
        s_pos_saved = true;
    }
}

bool stepper_save_position(void) {
    if (!s_prefs_open) return false;
    return s_prefs.putLong("pos", s_stepper.currentPosition());
}

bool stepper_load_position(long* out_pos) {
    if (!s_prefs_open) return false;
    *out_pos = s_prefs.getLong("pos", 0);
    return s_prefs.isKey("pos");
}

void stepper_set_dirty(bool dirty) {
    if (!s_prefs_open) return;
    s_prefs.putBool("dirty", dirty);
}

bool stepper_was_mid_move(void) {
    if (!s_prefs_open) return false;
    return s_prefs.getBool("dirty", false);
}
