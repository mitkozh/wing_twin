#include "stepper.h"
#include "../pins.h"
#include "../config.h"
#include <AccelStepper.h>
#include <LittleFS.h>

static AccelStepper s_stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);
static long s_target = 0;
static bool s_enabled = true;
static bool s_pos_saved = false;

static const char* STEPPER_STATE_FILE = "/stepper_pos.txt";

void stepper_init(void) {
    pinMode(ENABLE_PIN, OUTPUT);
    digitalWrite(ENABLE_PIN, LOW);
    s_stepper.setMaxSpeed(STEPPER_MAX_SPEED);
    s_stepper.setAcceleration(STEPPER_ACCELERATION);
    s_stepper.setCurrentPosition(0);
    s_target = 0;
    Serial.println("[STEPPER] init done");
}

void stepper_set_target(long steps) {
    if (steps < STEPPER_MIN_POSITION) steps = STEPPER_MIN_POSITION;
    if (steps > STEPPER_MAX_POSITION) steps = STEPPER_MAX_POSITION;
    s_target = steps;
    s_stepper.moveTo(steps);
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
        s_stepper.moveTo(pos);
        s_target = pos;
    }

    // Persist position when idle at target
    if (!stepper_is_moving() && !s_pos_saved) {
        stepper_save_position();
        s_pos_saved = true;
    } else if (stepper_is_moving()) {
        s_pos_saved = false;
    }
}

bool stepper_save_position(void) {
    if (!LittleFS.begin(false)) return false;
    File f = LittleFS.open(STEPPER_STATE_FILE, "w");
    if (!f) { LittleFS.end(); return false; }
    f.println(s_stepper.currentPosition());
    f.close();
    LittleFS.end();
    return true;
}

bool stepper_load_position(long* out_pos) {
    if (!LittleFS.begin(false)) return false;
    if (!LittleFS.exists(STEPPER_STATE_FILE)) { LittleFS.end(); return false; }
    File f = LittleFS.open(STEPPER_STATE_FILE, "r");
    if (!f) { LittleFS.end(); return false; }
    String line = f.readStringUntil('\n'); line.trim();
    f.close(); LittleFS.end();
    if (line.length() == 0) return false;
    *out_pos = line.toInt();
    return true;
}
