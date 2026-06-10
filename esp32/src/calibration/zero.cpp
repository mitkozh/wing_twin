#include "zero.h"
#include "../config.h"
#include "../hardware/hx711.h"
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

// Accumulate baseline for one channel, skipping saturated reads
static float sample_baseline_channel(int ch, int num_samples) {
    double accum = 0.0;
    int count = 0;
    for (int s = 0; s < num_samples; s++) {
        hx711_read_all();
        if (hx711_get_saturated(ch)) continue;
        accum += s_cbs.read_strain(ch);
        count++;
        delay(25);
    }
    if (count == 0) return 0.0f;
    return (float)(accum / count);
}

// Compute max delta from baseline using only non-saturated channels.
// Returns true if at least one channel was valid; maxDelta is set.
static bool compute_max_delta(float* baseline, float* maxDelta, int* validOut) {
    *maxDelta = 0.0f;
    int valid = 0;
    for (int ch = 0; ch < HX711_NUM_ACTIVE; ch++) {
        if (hx711_get_saturated(ch)) continue;
        float d = fabs(s_cbs.read_strain(ch) - baseline[ch]);
        if (d > *maxDelta) *maxDelta = d;
        valid++;
    }
    if (validOut) *validOut = valid;
    return valid > 0;
}

bool zero_run(void) {
    if (!s_initialized || !s_cbs.read_strain || !s_cbs.move_to || !s_cbs.get_position) {
        Serial.println("[ZERO] not initialized - skipping");
        return false;
    }
    Serial.println("[ZERO] starting calibration...");

    // 1. Sample per-channel baseline (skip saturated channels)
    float baseline[HX711_NUM_ACTIVE] = {0};
    int saturatedCount = 0;
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        baseline[i] = sample_baseline_channel(i, ZERO_NUM_SAMPLES);
        if (hx711_get_saturated(i)) {
            saturatedCount++;
            Serial.printf("[ZERO] channel %d saturated at baseline\n", i);
        }
    }
    if (saturatedCount == HX711_NUM_ACTIVE) {
        Serial.println("[ZERO] ERROR: all channels saturated, aborting");
        return false;
    }

    // 2. Retract to guaranteed-safe negative position
    long pos = s_cbs.get_position();
    long slackTarget = -ZERO_SLACK_SAFE_MARGIN;
    if (pos <= slackTarget) slackTarget = pos - 50;
    s_cbs.move_to(slackTarget);
    if (s_cbs.wait_for_motor) s_cbs.wait_for_motor(ZERO_MOVE_TIMEOUT_MS);

    // 3. Verify strain plateau at slack position
    hx711_read_all();
    float maxDelta = 0;
    int validCh = 0;
    if (!compute_max_delta(baseline, &maxDelta, &validCh)) {
        Serial.println("[ZERO] ERROR: all channels saturated after retract, aborting");
        return false;
    }
    if (maxDelta > ZERO_STRAIN_THRESHOLD * 3)
        Serial.printf("[ZERO] warning: strain elevated (%.4f) after retract\n", maxDelta);

    // Refresh baseline at slack position
    for (int i = 0; i < HX711_NUM_ACTIVE; i++)
        baseline[i] = sample_baseline_channel(i, 1);

    // 4. Step forward with multi-sample contact confirmation
    long contactPos = slackTarget;
    bool contactDetected = false;
    int contactConfirm = 0;

    for (int i = 0; i < ZERO_MAX_FORWARD_ITER; i++) {
        long t = s_cbs.get_position() + 1;
        s_cbs.move_to(t);
        if (s_cbs.wait_for_motor) s_cbs.wait_for_motor(ZERO_FORWARD_TIMEOUT_MS);
        hx711_read_all();

        if (!compute_max_delta(baseline, &maxDelta, &validCh)) {
            Serial.printf("[ZERO] all channels saturated at step %d, aborting\n", i);
            return false;
        }

        if (maxDelta > ZERO_STRAIN_THRESHOLD) {
            contactConfirm++;
            if (contactConfirm >= CONTACT_CONFIRM_NEEDED) {
                Serial.printf("[ZERO] contact at %ld (confirm=%d, delta=%.4f)\n", t, contactConfirm, maxDelta);
                contactDetected = true;
                break;
            }
        } else {
            contactConfirm = 0;
        }
        contactPos = t;
    }

    // 5. Report offset only - main.cpp handles resetting the stepper position.
    s_homeOffset = s_cbs.get_position();
    if (!contactDetected) {
        Serial.printf("[ZERO] no contact within %d steps, offset=%ld\n", ZERO_MAX_FORWARD_ITER, s_homeOffset);
        return false;
    }
    Serial.printf("[ZERO] done: contact at %ld, offset=%ld\n", contactPos, s_homeOffset);
    return true;
}
