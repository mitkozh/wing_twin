#include "hx711.h"
#include "../pins.h"
#include <LittleFS.h>
#include <stdlib.h>
#include <math.h>

// Shared SCK + 10 independent DT pins - all 10 HX711 modules share one SCK.
// 9 active channels = wing root/middle/tip × (0°/45°/90°)
// Channel 10 = dummy gauge for temperature compensation.

const int HX711_DT_PINS[HX711_NUM_CHANNELS] = {
    DOUT_ROOT_0,    DOUT_ROOT_45,   DOUT_ROOT_90,
    DOUT_MIDDLE_0,  DOUT_MIDDLE_45, DOUT_MIDDLE_90,
    DOUT_TIP_0,     DOUT_TIP_45,    DOUT_TIP_90,
    DOUT_DUMMY_GAUGE
};

static const char* CHANNEL_NAMES[HX711_NUM_CHANNELS] = {
    "root_0",   "root_45",  "root_90",
    "middle_0", "middle_45","middle_90",
    "tip_0",    "tip_45",   "tip_90",
    "dummy_gauge"
};

// Raw / compensated / strain values
static long   rawValues[HX711_NUM_CHANNELS] = {0};
static long   compensatedRaw[HX711_NUM_ACTIVE] = {0};
static float  strainValues[HX711_NUM_ACTIVE] = {0.0};
static bool   s_saturated[HX711_NUM_ACTIVE] = {false};
static int    s_readErrorCount = 0;
static long   s_lastDummy = 0;
static bool   s_lastDummyValid = false;
static unsigned long s_lastDummyTime = 0;

// Drift tracking state
static float  s_baseline[HX711_NUM_ACTIVE] = {0.0f};
static float  s_baselineVar[HX711_NUM_ACTIVE] = {0.0f};
static int    s_idleCount = 0;
static bool   s_driftCorrecting = false;

// Dummy gauge baseline for smoother fallback
static long   s_dummyBaseline = 0;
static bool   s_dummyBaselineValid = false;

// Calibration storage
typedef struct {
    float scale[HX711_NUM_ACTIVE];
    float offset[HX711_NUM_ACTIVE];
    bool  valid;
} Hx711Calibration;

static Hx711Calibration g_cal = {};
static const char* CAL_FILE = "/hx711_cal.txt";

bool hx711_load_calibration(void) {
    if (!LittleFS.exists(CAL_FILE)) {
        Serial.println("[HX711] No saved calibration");
        g_cal.valid = false; return false;
    }
    File f = LittleFS.open(CAL_FILE, "r");
    if (!f) { g_cal.valid = false; return false; }
    int idx = 0;
    while (f.available() && idx < HX711_NUM_ACTIVE) {
        String line = f.readStringUntil('\n'); line.trim();
        if (line.length() == 0) continue;
        int comma = line.indexOf(',');
        if (comma <= 0) continue;
        float s = line.substring(0, comma).toFloat();
        float o = line.substring(comma + 1).toFloat();
        if (isnan(s) || isinf(s) || isnan(o) || isinf(o)) continue;
        g_cal.scale[idx]  = s;
        g_cal.offset[idx] = o;
        idx++;
    }
    f.close();
    g_cal.valid = (idx == HX711_NUM_ACTIVE);
    if (g_cal.valid) Serial.println("[HX711] Calibration loaded");
    return g_cal.valid;
}

bool hx711_save_calibration(void) {
    File f = LittleFS.open(CAL_FILE, "w");
    if (!f) return false;
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        f.print(g_cal.scale[i], 6); f.print(","); f.println(g_cal.offset[i], 2);
    }
    f.close();
    Serial.println("[HX711] Calibration saved");
    return true;
}

// ---------------------------------------------------------------------------
// Tare helpers
// ---------------------------------------------------------------------------
static int sort_compare_f(const void* a, const void* b) {
    float fa = *(const float*)a;
    float fb = *(const float*)b;
    return (fa > fb) - (fa < fb);
}

static float median_of(float* arr, int n) {
    if (n <= 0) return 0.0f;
    qsort(arr, n, sizeof(float), sort_compare_f);
    return arr[n / 2];
}

bool hx711_tare(void) {
    Serial.println("[HX711] Taring...");

    // Collect TARE_GROUPS groups of TARE_SAMPLES_PER_GROUP samples each
    float groupMeans[HX711_NUM_ACTIVE][TARE_GROUPS];
    int   groupCounts[TARE_GROUPS] = {0};
    for (int g = 0; g < TARE_GROUPS; g++) {
        float accum[HX711_NUM_ACTIVE] = {0};
        int valid = 0;
        for (int s = 0; s < TARE_SAMPLES_PER_GROUP; s++) {
            if (hx711_read_all()) {
                long dummy = rawValues[HX711_NUM_CHANNELS - 1];
                for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
                    if (!s_saturated[i]) {
                        accum[i] += (float)(rawValues[i] - dummy);
                    }
                }
                valid++;
            }
            delay(50);
        }
        if (valid > 0) {
            for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
                groupMeans[i][g] = accum[i] / valid;
            }
            groupCounts[g] = valid;
        }
        // Extra delay between groups
        delay(100);
    }

    // Check variance within each channel across groups
    int totalValidGroups = 0;
    for (int g = 0; g < TARE_GROUPS; g++) {
        if (groupCounts[g] > 0) totalValidGroups++;
    }
    if (totalValidGroups == 0) {
        Serial.println("[HX711] Tare failed - no valid reads");
        return false;
    }

    // Compute per-channel offset as median of group means
    float tmp[TARE_GROUPS];
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        int n = 0;
        for (int g = 0; g < TARE_GROUPS; g++) {
            if (groupCounts[g] > 0) {
                // NaN / Inf guard
                float v = groupMeans[i][g];
                if (!isnan(v) && !isinf(v)) {
                    tmp[n++] = v;
                }
            }
        }
        if (n > 0) {
            g_cal.offset[i] = median_of(tmp, n);
        } else {
            g_cal.offset[i] = 0.0f;
            Serial.printf("[HX711] WARNING: channel %d saturated - offset set to 0\n", i);
        }
        if (g_cal.scale[i] <= 0.0f) g_cal.scale[i] = 1.0f;
    }

    // Reset drift tracking after fresh tare
    hx711_reset_baseline();
    g_cal.valid = true;
    Serial.println("[HX711] Tare complete");
    return true;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
void hx711_init(void) {
    pinMode(HX711_SCK, OUTPUT);
    digitalWrite(HX711_SCK, LOW);
    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        int p = HX711_DT_PINS[i];
        if (p == 34 || p == 35 || p == 36)
            pinMode(p, INPUT);
        else
            pinMode(p, INPUT_PULLUP);
    }
    if (!hx711_load_calibration()) {
        for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
            g_cal.scale[i] = 1.0f;
            g_cal.offset[i] = 0.0f;
        }
        g_cal.valid = false;
    }
    unsigned long start = millis();
    while (!hx711_read_all()) {
        if (millis() - start > 10000) {
            Serial.println("[HX711] Init timeout - continuing");
            return;
        }
        delay(200);
    }
    if (!g_cal.valid) { hx711_tare(); hx711_save_calibration(); }

    // Seed baselines with current offsets so drift correction converges quickly
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        if (!s_saturated[i]) {
            s_baseline[i] = g_cal.offset[i];
        }
    }
}

// ---------------------------------------------------------------------------
// Read all channels
// ---------------------------------------------------------------------------
static bool hx711_all_ready(void) {
    for (int i = 0; i < HX711_NUM_CHANNELS; i++)
        if (digitalRead(HX711_DT_PINS[i]) != LOW) return false;
    return true;
}

bool hx711_read_all(void) {
    unsigned long start = millis();
    while (!hx711_all_ready()) {
        if (millis() - start > HX711_READ_TIMEOUT_MS) {
            s_readErrorCount++;
            for (int i = 0; i < HX711_NUM_CHANNELS; i++)
                if (digitalRead(HX711_DT_PINS[i]) != LOW)
                    Serial.printf("[HX711] channel %d not ready\n", i);
            return false;
        }
        delay(1);
    }
    for (int i = 0; i < HX711_NUM_CHANNELS; i++) rawValues[i] = 0;
    // Keep interrupts enabled for GPIO writes; only mask them during the
    // brief digitalRead window so WiFi / FreeRTOS tasks are not starved.
    for (int bit = 23; bit >= 0; bit--) {
        digitalWrite(HX711_SCK, HIGH); delayMicroseconds(1);
        noInterrupts();
        for (int i = 0; i < HX711_NUM_CHANNELS; i++)
            if (digitalRead(HX711_DT_PINS[i]) == HIGH)
                rawValues[i] |= (1L << bit);
        interrupts();
        digitalWrite(HX711_SCK, LOW);  delayMicroseconds(1);
    }
    digitalWrite(HX711_SCK, HIGH); delayMicroseconds(1);
    digitalWrite(HX711_SCK, LOW);  delayMicroseconds(1);
    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        if (rawValues[i] & 0x800000) rawValues[i] |= 0xFF000000;
    }
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        s_saturated[i] = (rawValues[i] >= 8388607) || (rawValues[i] <= -8388608);
    }

    long dummyRaw = rawValues[HX711_NUM_CHANNELS - 1];
    bool dummyStuck = (dummyRaw == 0) || (dummyRaw >= 8388607) || (dummyRaw <= -8388608);
    if (dummyStuck) {
        // Hold last known good dummy value indefinitely.
        if (!s_lastDummyValid) {
            if (s_dummyBaselineValid) {
                dummyRaw = s_dummyBaseline;
            } else {
                dummyRaw = 0;
            }
        } else {
            dummyRaw = s_lastDummy;
        }
    } else {
        if (!s_lastDummyValid) {
            Serial.println("[HX711] dummy recovered");
            // Reset baselines when dummy recovers to avoid stale offsets
            hx711_reset_baseline();
        }
        s_lastDummy = dummyRaw;
        s_lastDummyValid = true;
        s_lastDummyTime = millis();
        // Update slow dummy baseline for fallback use
        if (!s_dummyBaselineValid) {
            s_dummyBaseline = dummyRaw;
            s_dummyBaselineValid = true;
        } else {
            s_dummyBaseline += (long)(0.01f * (dummyRaw - s_dummyBaseline));
        }
    }
    long dummy = dummyRaw;
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        if (s_saturated[i]) {
            compensatedRaw[i] = 0;
            strainValues[i] = 0.0f;
        } else {
            compensatedRaw[i] = rawValues[i] - dummy;
            strainValues[i] = (compensatedRaw[i] - g_cal.offset[i]) * g_cal.scale[i];
        }
    }

    // ------------------------------------------------------------------
    // Drift tracking: update slow baseline and variance per channel
    // ------------------------------------------------------------------
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        if (s_saturated[i]) continue;
        float cur = (float)compensatedRaw[i];
        // Slow exponential moving average (baseline)
        s_baseline[i] += DRIFT_EMA_ALPHA * (cur - s_baseline[i]);
        // Absolute deviation for variance estimate
        float dev = fabsf(cur - s_baseline[i]);
        s_baselineVar[i] += DRIFT_VAR_ALPHA * (dev - s_baselineVar[i]);
    }

    return true;
}

int  hx711_get_error_count(void)      { return s_readErrorCount; }
void hx711_reset_error_count(void)    { s_readErrorCount = 0; }

float hx711_get_strain(int i) {
    if (i < 0 || i >= HX711_NUM_ACTIVE) return 0.0f;
    return strainValues[i];
}

long hx711_get_raw(int i) {
    if (i < 0 || i >= HX711_NUM_CHANNELS) return 0;
    return rawValues[i];
}

long hx711_get_compensated_raw(int i) {
    if (i < 0 || i >= HX711_NUM_ACTIVE) return 0;
    return compensatedRaw[i];
}

bool hx711_get_saturated(int i) {
    if (i < 0 || i >= HX711_NUM_ACTIVE) return false;
    return s_saturated[i];
}

float hx711_get_offset(int i) {
    if (i < 0 || i >= HX711_NUM_ACTIVE) return 0.0f;
    return g_cal.offset[i];
}

const char* hx711_get_channel_name(int i) {
    if (i < 0 || i >= HX711_NUM_CHANNELS) return "invalid";
    return CHANNEL_NAMES[i];
}

// ---------------------------------------------------------------------------
// Drift correction
// ---------------------------------------------------------------------------
void hx711_update_drift(void) {
    if (!g_cal.valid) return;

    // Check if all active (non-saturated) channels are stable
    bool allStable = true;
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        if (s_saturated[i]) continue;
        if (s_baselineVar[i] > DRIFT_STABLE_VAR) {
            allStable = false;
            break;
        }
    }

    if (allStable) {
        s_idleCount++;
        if (s_idleCount >= DRIFT_IDLE_MIN_CYCLES) {
            // Slowly correct offsets toward current baseline
            bool anyCorrected = false;
            for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
                if (s_saturated[i]) continue;
                float target = s_baseline[i];
                float delta  = target - g_cal.offset[i];
                if (fabsf(delta) >= DRIFT_CORRECT_MIN_DELTA) {
                    g_cal.offset[i] += DRIFT_CORRECT_RATE * delta;
                    anyCorrected = true;
                }
            }
            if (anyCorrected) {
                s_driftCorrecting = true;
                // Reset idle counter to prevent overcorrection in one burst
                s_idleCount = DRIFT_IDLE_MIN_CYCLES / 2;
            }
        }
    } else {
        s_idleCount = 0;
        s_driftCorrecting = false;
    }
}

void hx711_reset_baseline(void) {
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        s_baseline[i] = 0.0f;
        s_baselineVar[i] = 0.0f;
    }
    s_idleCount = 0;
    s_driftCorrecting = false;
}

float hx711_get_baseline(int i) {
    if (i < 0 || i >= HX711_NUM_ACTIVE) return 0.0f;
    return s_baseline[i];
}

bool hx711_is_drift_correcting(void) {
    return s_driftCorrecting;
}


