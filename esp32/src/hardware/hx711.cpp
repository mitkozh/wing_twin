#include "hx711.h"
#include "../pins.h"
#include <LittleFS.h>

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

// Calibration storage
typedef struct {
    float scale[HX711_NUM_ACTIVE];
    float offset[HX711_NUM_ACTIVE];
    bool  valid;
} Hx711Calibration;

static Hx711Calibration g_cal = {};
static const char* CAL_FILE = "/hx711_cal.txt";

// ---------------------------------------------------------------------------
// LittleFS helpers
// ---------------------------------------------------------------------------
static bool mount_littlefs(void) {
    if (!LittleFS.begin(false)) {
        Serial.println("[HX711] LittleFS mount failed, trying format...");
        if (!LittleFS.begin(true)) {
            Serial.println("[HX711] LittleFS mount + format failed");
            return false;
        }
    }
    return true;
}

static void unmount_littlefs(void) {
    LittleFS.end();
}

bool hx711_load_calibration(void) {
    if (!mount_littlefs()) { g_cal.valid = false; return false; }
    if (!LittleFS.exists(CAL_FILE)) {
        Serial.println("[HX711] No saved calibration");
        unmount_littlefs(); g_cal.valid = false; return false;
    }
    File f = LittleFS.open(CAL_FILE, "r");
    if (!f) { unmount_littlefs(); g_cal.valid = false; return false; }
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
    f.close(); unmount_littlefs();
    g_cal.valid = (idx == HX711_NUM_ACTIVE);
    if (g_cal.valid) Serial.println("[HX711] Calibration loaded");
    return g_cal.valid;
}

bool hx711_save_calibration(void) {
    if (!mount_littlefs()) return false;
    File f = LittleFS.open(CAL_FILE, "w");
    if (!f) { unmount_littlefs(); return false; }
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        f.print(g_cal.scale[i], 6); f.print(","); f.println(g_cal.offset[i], 2);
    }
    f.close(); unmount_littlefs();
    Serial.println("[HX711] Calibration saved");
    return true;
}

// ---------------------------------------------------------------------------
// Tare
// ---------------------------------------------------------------------------
bool hx711_tare(void) {
    Serial.println("[HX711] Taring...");
    const int TARE_SAMPLES = 10;
    float accum[HX711_NUM_ACTIVE] = {0};
    int perChannelValid[HX711_NUM_ACTIVE] = {0};
    int totalValid = 0;
    for (int s = 0; s < TARE_SAMPLES; s++) {
        if (hx711_read_all()) {
            long dummy = rawValues[HX711_NUM_CHANNELS - 1];
            for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
                if (!s_saturated[i]) {
                    accum[i] += (float)(rawValues[i] - dummy);
                    perChannelValid[i]++;
                }
            }
            totalValid++;
        }
        delay(50);
    }
    if (totalValid == 0) { Serial.println("[HX711] Tare failed"); return false; }
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        if (perChannelValid[i] > 0) {
            g_cal.offset[i] = accum[i] / perChannelValid[i];
        } else {
            g_cal.offset[i] = 0.0f;
            Serial.printf("[HX711] WARNING: channel %d saturated - offset set to 0, strain=comp\n", i);
        }
        if (g_cal.scale[i] <= 0.0f) g_cal.scale[i] = 1.0f;
    }
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
    noInterrupts();
    for (int bit = 23; bit >= 0; bit--) {
        digitalWrite(HX711_SCK, HIGH); delayMicroseconds(1);
        for (int i = 0; i < HX711_NUM_CHANNELS; i++)
            if (digitalRead(HX711_DT_PINS[i]) == HIGH)
                rawValues[i] |= (1L << bit);
        digitalWrite(HX711_SCK, LOW);  delayMicroseconds(1);
    }
    digitalWrite(HX711_SCK, HIGH); delayMicroseconds(1);
    digitalWrite(HX711_SCK, LOW);  delayMicroseconds(1);
    interrupts();
    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        if (rawValues[i] & 0x800000) rawValues[i] |= 0xFF000000;
    }
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        s_saturated[i] = (rawValues[i] >= 8388607) || (rawValues[i] <= -8388608);
    }
    if (digitalRead(HX711_DT_PINS[HX711_NUM_CHANNELS - 1]) != HIGH) {
        Serial.println("[HX711] WARNING: dummy gauge stuck / not ready after read — temp compensation disabled");
        rawValues[HX711_NUM_CHANNELS - 1] = 0;
    }
    long dummy = rawValues[HX711_NUM_CHANNELS - 1];
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        compensatedRaw[i] = rawValues[i] - dummy;
        strainValues[i] = (compensatedRaw[i] - g_cal.offset[i]) * g_cal.scale[i];
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

void hx711_print_values(void) {
    Serial.println("HX711:");
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        Serial.printf("  %s | raw=%ld comp=%ld strain=%.3f\n",
                      CHANNEL_NAMES[i], rawValues[i], compensatedRaw[i], strainValues[i]);
    }
    Serial.printf("  %s | raw=%ld\n", CHANNEL_NAMES[HX711_NUM_CHANNELS - 1],
                  rawValues[HX711_NUM_CHANNELS - 1]);
}

void hx711_print_pin_info(void) {
    Serial.println("HX711 pins:");
    Serial.printf("  SCK -> GPIO %d\n", HX711_SCK);
    for (int i = 0; i < HX711_NUM_CHANNELS; i++)
        Serial.printf("  %s DT -> GPIO %d\n", CHANNEL_NAMES[i], HX711_DT_PINS[i]);
}
