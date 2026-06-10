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

// Average per-channel baselines across multiple reads, skipping saturated channels
static void sample_baselines(float* out, int num_samples) {
    double accum[HX711_NUM_ACTIVE] = {0};
    int count[HX711_NUM_ACTIVE] = {0};
    for (int s = 0; s < num_samples; s++) {
        hx711_read_all();
        for (int ch = 0; ch < HX711_NUM_ACTIVE; ch++) {
            if (hx711_get_saturated(ch)) continue;
            accum[ch] += s_cbs.read_strain(ch);
            count[ch]++;
        }
        delay(25);
    }
    for (int ch = 0; ch < HX711_NUM_ACTIVE; ch++) {
        out[ch] = (count[ch] > 0) ? (float)(accum[ch] / count[ch]) : 0.0f;
    }
}

// Compute max|delta| from per-channel baselines, skipping saturated channels.
// Returns true if at least one channel was valid.
static bool compute_max_delta(const float* baseline, float* maxDelta) {
    *maxDelta = 0.0f;
    bool valid = false;
    for (int ch = 0; ch < HX711_NUM_ACTIVE; ch++) {
        if (hx711_get_saturated(ch)) continue;
        float d = fabs(s_cbs.read_strain(ch) - baseline[ch]);
        if (d > *maxDelta) *maxDelta = d;
        valid = true;
    }
    return valid;
}

bool zero_run(void) {
    if (!s_initialized || !s_cbs.read_strain || !s_cbs.move_to || !s_cbs.get_position) {
        Serial.println("[ZERO] not initialized - skipping");
        return false;
    }
    Serial.println("[ZERO] starting calibration...");

    // 1. Retract until strain stabilises between consecutive reads.
    float prev[HX711_NUM_ACTIVE];
    sample_baselines(prev, ZERO_NUM_SAMPLES);
    const long RETRACT_STEP = 50;
    for (int i = 0; i < 20; i++) {
        long pos = s_cbs.get_position() - RETRACT_STEP;
        if (pos < STEPPER_MIN_POSITION) pos = STEPPER_MIN_POSITION;
        s_cbs.move_to(pos);
        if (s_cbs.wait_for_motor) s_cbs.wait_for_motor(ZERO_MOVE_TIMEOUT_MS);
        float curr[HX711_NUM_ACTIVE];
        sample_baselines(curr, 3);
        float maxChange = 0.0f;
        for (int ch = 0; ch < HX711_NUM_ACTIVE; ch++) {
            float d = fabs(curr[ch] - prev[ch]);
            if (d > maxChange) maxChange = d;
            prev[ch] = curr[ch];
        }
        Serial.printf("[ZERO] retracting: pos=%ld change=%.4f\n", pos, maxChange);
        if (maxChange < ZERO_SLACK_STABLE_THRESHOLD || pos == STEPPER_MIN_POSITION) {
            if (maxChange < ZERO_SLACK_STABLE_THRESHOLD)
                Serial.printf("[ZERO] slack confirmed at %ld\n", pos);
            break;
        }
    }

    // 2. Sample clean baseline at confirmed slack position
    float baseline[HX711_NUM_ACTIVE];
    sample_baselines(baseline, ZERO_NUM_SAMPLES);

    int saturatedCount = 0;
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        if (hx711_get_saturated(i)) {
            saturatedCount++;
            Serial.printf("[ZERO] channel %d saturated at baseline\n", i);
        }
    }
    if (saturatedCount == HX711_NUM_ACTIVE) {
        Serial.println("[ZERO] ERROR: all channels saturated, aborting");
        return false;
    }

    // 3. Step forward until strain exceeds threshold (contact)
    long contactPos = 0;
    bool contactDetected = false;
    int contactConfirm = 0;

    for (int i = 0; i < ZERO_MAX_FORWARD_ITER; i++) {
        long pos = s_cbs.get_position() + 1;
        s_cbs.move_to(pos);
        if (s_cbs.wait_for_motor) s_cbs.wait_for_motor(ZERO_FORWARD_TIMEOUT_MS);
        hx711_read_all();

        float maxDelta;
        if (!compute_max_delta(baseline, &maxDelta)) {
            Serial.printf("[ZERO] all channels saturated at step %d, aborting\n", i);
            return false;
        }

        if (maxDelta > ZERO_STRAIN_THRESHOLD) {
            contactConfirm++;
            if (contactConfirm >= CONTACT_CONFIRM_NEEDED) {
                contactPos = pos;
                contactDetected = true;
                Serial.printf("[ZERO] contact at %ld (confirm=%d, delta=%.4f)\n", pos, contactConfirm, maxDelta);
                break;
            }
        } else {
            contactConfirm = 0;
        }
    }

    if (!contactDetected) {
        Serial.printf("[ZERO] no contact within %d steps, aborting\n", ZERO_MAX_FORWARD_ITER);
        return false;
    }

    // 4. Back off one step at a time until strain drops below threshold.
    long zeroPos = contactPos;
    for (long pos = contactPos - 1; pos >= STEPPER_MIN_POSITION; pos--) {
        s_cbs.move_to(pos);
        if (s_cbs.wait_for_motor) s_cbs.wait_for_motor(ZERO_FORWARD_TIMEOUT_MS);
        hx711_read_all();

        float maxDelta;
        if (!compute_max_delta(baseline, &maxDelta)) {
            Serial.println("[ZERO] all channels saturated during backoff, aborting");
            return false;
        }

        if (maxDelta <= ZERO_STRAIN_THRESHOLD) {
            zeroPos = pos;
            Serial.printf("[ZERO] zero edge at %ld (delta=%.4f)\n", pos, maxDelta);
            break;
        }
    }

    // 5. Command stepper to zero position and record offset
    s_cbs.move_to(zeroPos);
    if (s_cbs.wait_for_motor) s_cbs.wait_for_motor(ZERO_MOVE_TIMEOUT_MS);
    s_homeOffset = zeroPos;
    Serial.printf("[ZERO] done: contact at %ld, zero at %ld\n", contactPos, zeroPos);
    return true;
}
