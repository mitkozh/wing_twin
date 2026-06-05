#include "Stepper_control.h"

// =====================================================
// GPIO pin assignments
// =====================================================
const int STEP_PIN    = 17;
const int DIR_PIN     = 21;
const int ENABLE_PIN  = 23;

// =====================================================
// Stepper parameters
// =====================================================
const unsigned long MAX_STEP_RATE_US = 200;       // 5 kHz max step rate
const unsigned long MIN_STEP_RATE_US = 2000;      // 500 Hz min step rate
const unsigned long ACCEL_STEPS      = 200;       // steps to accelerate/decelerate
const long          POSITION_TOLERANCE = 5;       // acceptable error (steps)

// =====================================================
// State
// =====================================================
static long s_currentPosition = 0;
static long s_targetPosition  = 0;
static unsigned long s_lastStepTime = 0;
static unsigned long s_currentStepRate = MAX_STEP_RATE_US;
static bool s_enabled = true;

// =====================================================
// Initialize GPIOs
// =====================================================
void stepper_init() {
    pinMode(STEP_PIN, OUTPUT);
    pinMode(DIR_PIN, OUTPUT);
    pinMode(ENABLE_PIN, OUTPUT);

    digitalWrite(STEP_PIN, LOW);
    digitalWrite(DIR_PIN, LOW);
    digitalWrite(ENABLE_PIN, LOW);    // enable (active low on many drivers)

    s_currentPosition = 0;
    s_targetPosition = 0;
    s_lastStepTime = micros();
    s_currentStepRate = MAX_STEP_RATE_US;

    Serial.println("[STEPPER] Initialized (STEP=GPIO17, DIR=GPIO21, EN=GPIO23)");
}

// =====================================================
// Set a new target position (called from MQTT callback)
// =====================================================
void stepper_set_target(long targetSteps) {
    s_targetPosition = targetSteps;
}

long stepper_get_current_position() {
    return s_currentPosition;
}

bool stepper_is_moving() {
    return abs(s_currentPosition - s_targetPosition) > POSITION_TOLERANCE;
}

// =====================================================
// Must be called frequently from loop()
// Moves one step if enough time has elapsed
// =====================================================
void stepper_loop() {
    if (!s_enabled) {
        return;
    }

    long diff = s_targetPosition - s_currentPosition;
    if (abs(diff) <= POSITION_TOLERANCE) {
        // Reached target — coast to max speed for next move
        s_currentStepRate = MAX_STEP_RATE_US;
        return;
    }

    unsigned long now = micros();
    if (now - s_lastStepTime < s_currentStepRate) {
        return;   // not time for next step yet
    }
    s_lastStepTime = now;

    // --- Acceleration/deceleration ---
    long distRemaining = abs(diff);
    long distFromStart = abs(s_targetPosition - s_currentPosition - diff);
    long rampDist = min(distFromStart, distRemaining);

    if (rampDist < ACCEL_STEPS) {
        // Ramping
        float frac = (float)rampDist / ACCEL_STEPS;
        s_currentStepRate = MAX_STEP_RATE_US + (unsigned long)((MIN_STEP_RATE_US - MAX_STEP_RATE_US) * (1.0f - frac));
    } else {
        s_currentStepRate = MAX_STEP_RATE_US;
    }

    // --- Direction ---
    if (diff > 0) {
        digitalWrite(DIR_PIN, HIGH);
        s_currentPosition++;
    } else {
        digitalWrite(DIR_PIN, LOW);
        s_currentPosition--;
    }

    // --- Step pulse ---
    digitalWrite(STEP_PIN, HIGH);
    delayMicroseconds(5);
    digitalWrite(STEP_PIN, LOW);
}