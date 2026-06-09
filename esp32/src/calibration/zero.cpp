#include "zero.h"
#include "../config.h"
#include <Arduino.h>

static zero_callbacks_t s_cbs;
static long s_homeOffset = 0;
static bool s_initialized = false;

void zero_init(zero_callbacks_t cbs) {
    s_cbs = cbs;
    s_initialized = true;
}

long zero_get_offset(void) {
    return s_homeOffset;
}

bool zero_run(void) {
    if (!s_initialized || !s_cbs.read_strain || !s_cbs.move_to || !s_cbs.get_position) {
        Serial.println("[ZERO] not initialized - skipping");
        return false;
    }
    Serial.println("[ZERO] starting calibration...");

    // 1. Sample baseline
    float baseline[HX711_NUM_ACTIVE] = {0};
    int valid = 0;
    for (int s = 0; s < ZERO_NUM_SAMPLES; s++) {
        for (int i = 0; i < HX711_NUM_ACTIVE; i++)
            baseline[i] += s_cbs.read_strain(i);
        valid++;
        delay(25);
    }
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) baseline[i] /= valid;

    // 2. Retract to guaranteed-safe negative position (handles squished string)
    long pos = s_cbs.get_position();
    long slackTarget = -ZERO_SLACK_SAFE_MARGIN;
    if (pos <= slackTarget) slackTarget = pos - 50;
    s_cbs.move_to(slackTarget);
    if (s_cbs.wait_for_motor) s_cbs.wait_for_motor(ZERO_MOVE_TIMEOUT_MS);

    // 3. Verify strain plateau at slack position
    float maxDelta = 0;
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        float d = fabs(s_cbs.read_strain(i) - baseline[i]);
        if (d > maxDelta) maxDelta = d;
    }
    if (maxDelta > ZERO_STRAIN_THRESHOLD * 3)
        Serial.printf("[ZERO] warning: strain elevated (%.4f) after retract\n", maxDelta);

    // Refresh baseline at slack position
    for (int i = 0; i < HX711_NUM_ACTIVE; i++)
        baseline[i] = s_cbs.read_strain(i);

    // 4. Step forward until first contact detected
    long contactPos = slackTarget;
    bool contactDetected = false;
    for (int i = 0; i < ZERO_MAX_FORWARD_ITER; i++) {
        long t = s_cbs.get_position() + 1;
        s_cbs.move_to(t);
        if (s_cbs.wait_for_motor) s_cbs.wait_for_motor(ZERO_FORWARD_TIMEOUT_MS);
        maxDelta = 0;
        for (int ch = 0; ch < HX711_NUM_ACTIVE; ch++) {
            float d = fabs(s_cbs.read_strain(ch) - baseline[ch]);
            if (d > maxDelta) maxDelta = d;
        }
        if (maxDelta > ZERO_STRAIN_THRESHOLD) {
            Serial.printf("[ZERO] contact at %ld (delta=%.4f)\n", t, maxDelta);
            contactDetected = true;
            break;
        }
        contactPos = t;
    }

    // 5. Report offset only - main.cpp handles resetting the stepper position.
    //    After this returns, main.cpp calls stepper_reset_position(0) so the
    //    current physical position (contact point) becomes software zero.
    s_homeOffset = s_cbs.get_position();
    if (!contactDetected) {
        Serial.printf("[ZERO] no contact within %d steps, offset=%ld\n", ZERO_MAX_FORWARD_ITER, s_homeOffset);
        return false;
    }
    Serial.printf("[ZERO] done: contact at %ld, offset=%ld\n", contactPos, s_homeOffset);
    return true;
}
