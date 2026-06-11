#include "zero.h"
#include "../config.h"
#include "../hardware/hx711.h"
#include "../comms/mqtt.h"
#include "../comms/wifi_mgr.h"
#include "../utils/watchdog.h"

static long s_homeOffset = 0;
static bool s_initialized = false;

void zero_init(void) {
    s_initialized = true;
}

long zero_get_offset(void) {
    return s_homeOffset;
}

// Stepper state tracked from MQTT status messages
static long   s_stepperPos   = 0;
static bool   s_stepperMoving = false;
static bool   s_stepperOnline = false;

void zero_update_stepper_state(long position, bool moving, bool online) {
    s_stepperPos = position;
    s_stepperMoving = moving;
    s_stepperOnline = online;
}

bool zero_is_stepper_ready(void) {
    return s_stepperOnline;
}

// Send a move command and wait for stepper to reach position
static bool mqtt_move_and_wait(long target, unsigned long timeout_ms) {
    char buf[64];
    snprintf(buf, sizeof(buf), "{\"position\":%ld}", target);
    mqtt_publish(STEPPER_COMMAND_TOPIC, buf);

    unsigned long start = millis();
    while (millis() - start < timeout_ms) {
        watchdog_feed();
        wifi_mgr_loop();
        mqtt_loop();
        if (!s_stepperMoving && s_stepperPos == target) return true;
        delay(STEPPER_MQTT_POLL_MS);
    }
    Serial.printf("[ZERO] timeout waiting for position %ld (now %ld, moving=%d)\n",
                  target, s_stepperPos, s_stepperMoving);
    return false;
}

// Wait for stepper to stop moving
static bool mqtt_wait_for_idle(unsigned long timeout_ms) {
    unsigned long start = millis();
    while (millis() - start < timeout_ms) {
        watchdog_feed();
        wifi_mgr_loop();
        mqtt_loop();
        if (!s_stepperMoving) return true;
        delay(STEPPER_MQTT_POLL_MS);
    }
    Serial.printf("[ZERO] timeout waiting for idle (pos=%ld, moving=%d)\n",
                  s_stepperPos, s_stepperMoving);
    return false;
}

// Average per-channel baselines across multiple reads
static void sample_baselines(float* out, int num_samples) {
    double accum[HX711_NUM_ACTIVE] = {0};
    int count[HX711_NUM_ACTIVE] = {0};
    for (int s = 0; s < num_samples; s++) {
        watchdog_feed();
        hx711_read_all();
        for (int ch = 0; ch < HX711_NUM_ACTIVE; ch++) {
            if (hx711_get_saturated(ch)) continue;
            accum[ch] += hx711_get_strain(ch);
            count[ch]++;
        }
        wifi_mgr_loop();
        mqtt_loop();
        delay(25);
    }
    for (int ch = 0; ch < HX711_NUM_ACTIVE; ch++) {
        out[ch] = (count[ch] > 0) ? (float)(accum[ch] / count[ch]) : 0.0f;
    }
}

// Compute max|delta| from per-channel baselines
static bool compute_max_delta(const float* baseline, float* maxDelta) {
    *maxDelta = 0.0f;
    bool valid = false;
    for (int ch = 0; ch < HX711_NUM_ACTIVE; ch++) {
        if (hx711_get_saturated(ch)) continue;
        float d = fabs(hx711_get_strain(ch) - baseline[ch]);
        if (d > *maxDelta) *maxDelta = d;
        valid = true;
    }
    return valid;
}

bool zero_run(void) {
    if (!s_initialized) {
        Serial.println("[ZERO] not initialized - skipping");
        return false;
    }
    if (!s_stepperOnline) {
        Serial.println("[ZERO] stepper not online - skipping");
        return false;
    }
    Serial.println("[ZERO] starting calibration over MQTT...");

    // Ensure stepper is idle first
    mqtt_wait_for_idle(ZERO_MOVE_TIMEOUT_MS);

    // 1. Retract until strain stabilises
    float prev[HX711_NUM_ACTIVE];
    sample_baselines(prev, ZERO_NUM_SAMPLES);
    const long RETRACT_STEP = 50;

    for (int i = 0; i < 20; i++) {
        long pos = s_stepperPos - RETRACT_STEP;
        if (pos < STEPPER_MIN_POSITION) pos = STEPPER_MIN_POSITION;

        if (!mqtt_move_and_wait(pos, ZERO_MOVE_TIMEOUT_MS)) return false;

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
        if (hx711_get_saturated(i)) saturatedCount++;
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
        long pos = s_stepperPos + 1;
        if (!mqtt_move_and_wait(pos, ZERO_FORWARD_TIMEOUT_MS)) return false;
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

    // 4. Back off one step at a time until strain drops below threshold
    long zeroPos = contactPos;
    for (long pos = contactPos - 1; pos >= STEPPER_MIN_POSITION; pos--) {
        if (!mqtt_move_and_wait(pos, ZERO_FORWARD_TIMEOUT_MS)) return false;
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

    // 5. Move to zero position and send reset_position to stepper ESP
    if (!mqtt_move_and_wait(zeroPos, ZERO_MOVE_TIMEOUT_MS)) return false;

    char buf[64];
    snprintf(buf, sizeof(buf), "{\"reset_position\":0}");
    mqtt_publish(STEPPER_COMMAND_TOPIC, buf);
    mqtt_wait_for_idle(1000);
    s_stepperPos = 0;
    s_stepperMoving = false;

    s_homeOffset = zeroPos;
    Serial.printf("[ZERO] done: contact at %ld, zero at %ld, offset=%ld\n", contactPos, zeroPos, s_homeOffset);
    return true;
}
