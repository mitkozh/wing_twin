#include "stepper.h"
#include "../pins.h"
#include "../config.h"
#include <AccelStepper.h>
#include <Preferences.h>

static AccelStepper s_stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);
static long s_target = 0;
static bool s_enabled = true;
static bool s_pos_saved = false;
static unsigned long s_last_move_save = 0;

static const char* PREFS_NS = "stepper";

void stepper_init(void) {
    pinMode(ENABLE_PIN, OUTPUT);
    digitalWrite(ENABLE_PIN, HIGH);          // start disabled - let driver supply stabilize
    delay(100);                              // brief settling window
    s_stepper.setMaxSpeed(STEPPER_MAX_SPEED);
    s_stepper.setAcceleration(STEPPER_ACCELERATION);
    s_stepper.setCurrentPosition(0);
    s_target = 0;
    digitalWrite(ENABLE_PIN, LOW);            // enable driver now
    Serial.println("[STEPPER] init done");
}

void stepper_set_target(long steps) {
    if (steps < STEPPER_MIN_POSITION) steps = STEPPER_MIN_POSITION;
    if (steps > STEPPER_MAX_POSITION) steps = STEPPER_MAX_POSITION;
    s_target = steps;
    s_stepper.moveTo(steps);
    stepper_set_dirty(true);
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

void stepper_loop(void) {
    if (!s_enabled) return;
    s_stepper.run();
    long pos = s_stepper.currentPosition();

    // Clamp at limits
    if (pos <= STEPPER_MIN_POSITION || pos >= STEPPER_MAX_POSITION) {
        long clamped = constrain(pos, STEPPER_MIN_POSITION, STEPPER_MAX_POSITION);
        s_stepper.moveTo(clamped);
        s_target = clamped;
    }

    // Periodic save during motion (every 500ms)
    if (stepper_is_moving()) {
        s_pos_saved = false;
        if (millis() - s_last_move_save > 500) {
            stepper_save_position();
            s_last_move_save = millis();
        }
        return;
    }

    // Persist position when idle at target
    if (!s_pos_saved) {
        stepper_save_position();
        stepper_set_dirty(false);
        s_pos_saved = true;
    }
}

bool stepper_save_position(void) {
    Preferences prefs;
    if (!prefs.begin(PREFS_NS, false)) return false;
    bool ok = prefs.putLong("pos", s_stepper.currentPosition());
    prefs.end();
    return ok;
}

bool stepper_load_position(long* out_pos) {
    Preferences prefs;
    if (!prefs.begin(PREFS_NS, true)) return false;
    long val = prefs.getLong("pos", 0);
    bool found = prefs.isKey("pos");
    prefs.end();
    if (!found) return false;
    *out_pos = val;
    return true;
}

void stepper_set_dirty(bool dirty) {
    Preferences prefs;
    if (!prefs.begin(PREFS_NS, false)) return;
    prefs.putBool("dirty", dirty);
    prefs.end();
}

bool stepper_was_mid_move(void) {
    Preferences prefs;
    if (!prefs.begin(PREFS_NS, true)) return false;
    bool dirty = prefs.getBool("dirty", false);
    prefs.end();
    return dirty;
}
