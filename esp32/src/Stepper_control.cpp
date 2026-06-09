// TODO: Uncomment the HX711 include when stepper motor hardware is installed.
//       This module is ready and tested for strain-guided zero calibration.
//       Enable steps:
//         1. Uncomment #include "Hx711_control.h" below
//         2. main.cpp: uncomment stepper init/homing/loop
//         3. mqtt_control.cpp: uncomment stepper position handling

#include "Stepper_control.h"
// #include "Hx711_control.h"

// =====================================================
// GPIO pin assignments
// =====================================================
const int STEP_PIN    = 17;
const int DIR_PIN     = 21;
const int ENABLE_PIN  = 23;

// =====================================================
// Stepper parameters
// =====================================================
const unsigned long MAX_STEP_RATE_US = 1000;      // 1 kHz max step rate
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
static long s_homeOffset = 0;

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

long stepper_get_home_offset() {
    return s_homeOffset;
}

static void _wait_for_motor(unsigned long timeout_ms) {
    unsigned long start = millis();
    while (stepper_is_moving() && millis() - start < timeout_ms) {
        stepper_loop();
        delay(1);
    }
}

void stepper_zero_with_feedback() {
    const int   NUM_SAMPLES        = 10;
    const float STRAIN_THRESHOLD   = 0.005f;  // per-channel, tune empirically
    const int   SLACK_SAFE_MARGIN  = 100;     // steps below expected zero to guarantee slack
    const int   MAX_FORWARD_ITER   = 50;

    Serial.println("[STEPPER] Zero calibration starting (strain feedback)...");

    // 1. Sample current strain baseline across all active channels
    float baseline[HX711_NUM_ACTIVE] = {0};
    int validSamples = 0;
    for (int s = 0; s < NUM_SAMPLES; s++) {
        if (hx711_read_all_channels()) {
            for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
                baseline[i] += hx711_get_strain_value(i);
            }
            validSamples++;
        }
        delay(25);
    }
    if (validSamples == 0) {
        Serial.println("[STEPPER] WARNING: No HX711 samples, fallback to software zero");
        s_homeOffset = s_currentPosition;
        s_currentPosition = 0;
        s_targetPosition = 0;
        return;
    }
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        baseline[i] /= validSamples;
    }

    long slackTarget = -SLACK_SAFE_MARGIN;
    if (s_currentPosition > -SLACK_SAFE_MARGIN) {
        slackTarget = -SLACK_SAFE_MARGIN;
    } else {
        // Already past safe margin, back off a bit more
        slackTarget = s_currentPosition - 50;
    }
    stepper_set_target(slackTarget);
    _wait_for_motor(5000);
    Serial.printf("[STEPPER] Retracted to slack position %ld\n", slackTarget);

    hx711_read_all_channels();
    float maxStrainDelta = 0;
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        float d = fabs(hx711_get_strain_value(i) - baseline[i]);
        if (d > maxStrainDelta) maxStrainDelta = d;
    }
    if (maxStrainDelta > STRAIN_THRESHOLD * 3) {
        Serial.printf("[STEPPER] WARNING: Strain still elevated (%.4f) after retraction — "
                      "string may be jammed\n", maxStrainDelta);
    }

    // Refresh baseline from the guaranteed-slack position
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        baseline[i] = hx711_get_strain_value(i);
    }

    // 4. Step forward +1 at a time until strain changes (contact point = true zero)
    long contactPos = slackTarget;
    for (int iter = 0; iter < MAX_FORWARD_ITER; iter++) {
        long newTarget = s_currentPosition + 1;
        stepper_set_target(newTarget);
        _wait_for_motor(500);

        if (!hx711_read_all_channels()) {
            contactPos = newTarget;
            continue;
        }

        float maxDelta = 0;
        for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
            float d = fabs(hx711_get_strain_value(i) - baseline[i]);
            if (d > maxDelta) maxDelta = d;
        }

        if (maxDelta > STRAIN_THRESHOLD) {
            // String just contacted — zero is the previous position
            Serial.printf("[STEPPER] Contact at step %ld (delta=%.4f)\n", newTarget, maxDelta);
            break;
        }
        contactPos = newTarget;
    }

    // 5. Move to contact position (true zero) and calibrate
    stepper_set_target(contactPos);
    _wait_for_motor(2000);

    s_homeOffset = s_currentPosition;
    s_currentPosition = 0;
    s_targetPosition = 0;

    Serial.printf("[STEPPER] Zero calibrated: physical zero at raw step %ld, offset=%ld\n",
                  contactPos, s_homeOffset);
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