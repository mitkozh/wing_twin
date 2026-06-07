#include "Hx711_control.h"
// #include "Stepper_control.h"
#include <LittleFS.h>

// =====================================================
// HX711 shared SCK + 10 independent DT pins
//
// 10 HX711 modules share one SCK, each has its own DT pin.
// 9 active channels = wing root/middle/tip × (0°/45°/90°)
// Channel 10 = dummy gauge for temperature compensation.
// =====================================================

const int HX711_SCK = 18;  // shared SCK / CLK pin


//
// NOTE: GPIO 34, 35, 36 are input-only pins.
// They have NO internal pullup — you MUST add external 10kΩ
// pull-up resistors on the hardware for TIP_45, TIP_90, DUMMY.
// Without them these channels may never show as "ready".
//
const int DOUT_ROOT_0      = 15;   // moved from GPIO4 (was conflicting with LED1_RED)
const int DOUT_ROOT_45     = 25;
const int DOUT_ROOT_90     = 26;

const int DOUT_MIDDLE_0    = 27;
const int DOUT_MIDDLE_45   = 14;
const int DOUT_MIDDLE_90   = 32;

const int DOUT_TIP_0       = 33;
const int DOUT_TIP_45      = 34;   // input-only — needs external 10kΩ pull-up
const int DOUT_TIP_90      = 35;   // input-only — needs external 10kΩ pull-up

const int DOUT_DUMMY_GAUGE = 36;   // input-only — needs external 10kΩ pull-up

// Saturation limits for 24-bit two's complement HX711 readings
const long HX711_SATURATION_POS =  8388607;   //  0x7FFFFF — positive saturation
const long HX711_SATURATION_NEG = -8388608;   //  0xFF800000 after sign extension — negative saturation

// =====================================================
// [KEEP IN Hx711_control.cpp]
// 正式保留：把所有 DT pins 放进 array
// 顺序必须和 CHANNEL_NAMES 一致
// =====================================================

const int HX711_DT_PINS[HX711_NUM_CHANNELS] = {
    DOUT_ROOT_0,
    DOUT_ROOT_45,
    DOUT_ROOT_90,

    DOUT_MIDDLE_0,
    DOUT_MIDDLE_45,
    DOUT_MIDDLE_90,

    DOUT_TIP_0,
    DOUT_TIP_45,
    DOUT_TIP_90,

    DOUT_DUMMY_GAUGE
};


// =====================================================
// [KEEP IN Hx711_control.cpp]
// 正式保留：channel names
//
// MQTT payload 会使用这些名字。
// =====================================================

const char* CHANNEL_NAMES[HX711_NUM_CHANNELS] = {
    "root_0",
    "root_45",
    "root_90",

    "middle_0",
    "middle_45",
    "middle_90",

    "tip_0",
    "tip_45",
    "tip_90",

    "dummy_gauge"
};


// =====================================================
// raw / compensated / published values
//
// rawValues:     HX711 raw 24-bit ADC count per channel
// compensatedRaw: temperature-compensated (raw - dummy)
// strainValues:  (compensated - offset) * scale
//                With default scale=1.0 this is compensated
//                ADC counts; Python does the ADC->strain conversion.
// =====================================================

long rawValues[HX711_NUM_CHANNELS] = {0};
long compensatedRaw[HX711_NUM_ACTIVE] = {0};
float strainValues[HX711_NUM_ACTIVE] = {0.0};

// Calibration (loaded from / saved to LittleFS)
Hx711Calibration g_hx711_cal = {};

// Error counter — incremented on read failures, cleared on successful read
static int s_readErrorCount = 0;

// =====================================================
// LittleFS helpers for calibration persistence
// =====================================================

static const char* CAL_FILE = "/hx711_cal.txt";

bool hx711_load_calibration(Hx711Calibration &cal) {
    if (!LittleFS.begin(true)) {
        Serial.println("[HX711] LittleFS mount + format failed, cannot load calibration");
        cal.valid = false;
        return false;
    }

    if (!LittleFS.exists(CAL_FILE)) {
        Serial.println("[HX711] No saved calibration found");
        cal.valid = false;
        LittleFS.end();
        return false;
    }

    File f = LittleFS.open(CAL_FILE, "r");
    if (!f) {
        Serial.println("[HX711] Failed to open calibration file");
        cal.valid = false;
        LittleFS.end();
        return false;
    }

    // Text format: one line per active channel:  scale,offset
    int idx = 0;
    while (f.available() && idx < HX711_NUM_ACTIVE) {
        String line = f.readStringUntil('\n');
        line.trim();
        if (line.length() == 0) continue;

        int comma = line.indexOf(',');
        if (comma <= 0) continue;

        float s = line.substring(0, comma).toFloat();
        float o = line.substring(comma + 1).toFloat();
        cal.scale[idx] = s;
        cal.offset[idx] = o;
        idx++;
    }
    f.close();
    LittleFS.end();

    cal.valid = (idx == HX711_NUM_ACTIVE);
    if (cal.valid) {
        for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
            if (cal.scale[i] <= 0.0f || cal.offset[i] <= -1.0f) {
                cal.valid = false;
                Serial.print("[HX711] Invalid calibration at channel ");
                Serial.print(i);
                Serial.print(": scale=");
                Serial.print(cal.scale[i], 6);
                Serial.print(", offset=");
                Serial.println(cal.offset[i], 2);
                break;
            }
        }
    }
    if (cal.valid) {
        Serial.println("[HX711] Calibration loaded from LittleFS");
    } else {
        Serial.println("[HX711] Calibration file invalid — will re-tare");
        LittleFS.remove(CAL_FILE);
    }
    return cal.valid;
}

bool hx711_save_calibration(const Hx711Calibration &cal) {
    if (!LittleFS.begin(false)) {
        LittleFS.format();
        if (!LittleFS.begin(false)) {
            Serial.println("[HX711] LittleFS mount failed, cannot save calibration");
            return false;
        }
    }

    File f = LittleFS.open(CAL_FILE, "w");
    if (!f) {
        Serial.println("[HX711] Failed to open calibration file for writing");
        LittleFS.end();
        return false;
    }

    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        f.print(cal.scale[i], 6);
        f.print(",");
        f.println(cal.offset[i], 2);
    }
    f.close();
    LittleFS.end();
    Serial.println("[HX711] Calibration saved to LittleFS");
    return true;
}

bool hx711_auto_tare(Hx711Calibration &cal) {
    Serial.println("[HX711] Auto-taring active channels (10 samples)...");
    const int TARE_SAMPLES = 10;
    float accum[HX711_NUM_ACTIVE] = {0};
    int validSamples = 0;

    for (int s = 0; s < TARE_SAMPLES; s++) {
        if (hx711_read_all_channels()) {
            long dummy = rawValues[HX711_NUM_CHANNELS - 1];
            for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
                accum[i] += (float)(rawValues[i] - dummy);
            }
            validSamples++;
        }
        delay(50);
    }

    if (validSamples == 0) {
        Serial.println("[HX711] Tare failed — no valid samples");
        return false;
    }

    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        cal.offset[i] = accum[i] / validSamples;
        if (cal.scale[i] <= 0.0f) {
            cal.scale[i] = 1.0f;   // default scale if never set
        }
    }

    cal.valid = true;
    Serial.println("[HX711] Tare complete");
    return true;
}


// =====================================================
// Initialize HX711 pins
// =====================================================

void hx711_init() {
    Serial.println("Initializing 10-channel HX711 array...");

    pinMode(HX711_SCK, OUTPUT);
    digitalWrite(HX711_SCK, LOW);

    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        // GPIO 34, 35, 36 are input-only — cannot use INPUT_PULLUP
        int p = HX711_DT_PINS[i];
        if (p == 34 || p == 35 || p == 36) {
            pinMode(p, INPUT);
            Serial.print("[HX711] Channel ");
            Serial.print(CHANNEL_NAMES[i]);
            Serial.println(" set to INPUT (no pullup — external 10kΩ required)");
        } else {
            pinMode(p, INPUT_PULLUP);
        }
    }

    hx711_print_pin_info();

    // Load saved calibration if available
    if (hx711_load_calibration(g_hx711_cal)) {
        Serial.println("[HX711] Using saved calibration");
    } else {
        Serial.println("[HX711] No saved calibration — will use defaults (scale=1.0)");
        for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
            g_hx711_cal.scale[i] = 1.0f;
            g_hx711_cal.offset[i] = 0.0f;
        }
        g_hx711_cal.valid = false;
    }

    Serial.println("Waiting for HX711 array to become ready...");

    unsigned long startTime = millis();
    unsigned long lastWarnTime = 0;
    while (!hx711_ready_active()) {
        if (millis() - startTime > 30000) {
            Serial.println("HX711 init timeout (active channels 0-8). Proceeding with partial data.");
            return;
        }
        if (millis() - lastWarnTime > 5000) {
            lastWarnTime = millis();
            Serial.print("[HX711] Waiting for ready... ");
            Serial.print((millis() - startTime) / 1000);
            Serial.println("s elapsed");
        }
        delay(200);
    }

    Serial.println("HX711 array ready (all channels).");

    // Perform tare if no saved calibration exists
    if (!g_hx711_cal.valid) {
        bool tareOk = hx711_auto_tare(g_hx711_cal);
        if (tareOk) {
            hx711_save_calibration(g_hx711_cal);
        } else {
            Serial.println("[HX711] Tare failed — calibration not saved");
        }
    }
}


// =====================================================
// [KEEP IN Hx711_control.cpp]
// 正式保留：检查所有 HX711 是否 ready
//
// HX711 rule:
// DT / DOUT LOW  = data ready
// DT / DOUT HIGH = not ready
// =====================================================

bool hx711_ready_all() {
    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        if (digitalRead(HX711_DT_PINS[i]) != LOW) {
            return false;
        }
    }

    return true;
}

bool hx711_ready_active() {
    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        if (digitalRead(HX711_DT_PINS[i]) != LOW) {
            return false;
        }
    }

    return true;
}


// =====================================================
// [KEEP IN Hx711_control.cpp]
// 正式保留：SCK pulse，同时读取所有 DT pins
// =====================================================

void hx711_pulse_sck_read(int bitPosition) {
    digitalWrite(HX711_SCK, HIGH);
    delayMicroseconds(1);

    if (bitPosition >= 0) {
        for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
            if (digitalRead(HX711_DT_PINS[i]) == HIGH) {
                rawValues[i] |= (1L << bitPosition);
            }
        }
    }

    digitalWrite(HX711_SCK, LOW);
    delayMicroseconds(1);
}


// =====================================================
// Read all 10 HX711 channels simultaneously via shared SCK
//
// Why not 10 HX711 library objects? Because the SCK is shared.
// Using scale.read() on one would clock all of them,
// corrupting the other channels' data.
// =====================================================

bool hx711_read_all_channels() {
    unsigned long startTime = millis();

    // Wait for active channels (0..8) to be ready
    // Dummy gauge (index 9) is optional — missing external pull-up on GPIO 36
    // should not block the other 9 channels.
    while (!hx711_ready_active()) {
        if (millis() - startTime > 1000) {
            Serial.println("HX711 read timeout.");
            Serial.print("  Not ready: ");
            bool first = true;
            for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
                if (digitalRead(HX711_DT_PINS[i]) != LOW) {
                    if (!first) Serial.print(", ");
                    Serial.print(CHANNEL_NAMES[i]);
                    first = false;
                }
            }
            Serial.println();
            s_readErrorCount++;
            return false;
        }
    }

    // Check if dummy gauge is also ready
    bool dummyReady = (digitalRead(HX711_DT_PINS[HX711_NUM_CHANNELS - 1]) == LOW);
    if (!dummyReady) {
        static unsigned long lastDummyWarn = 0;
        if (millis() - lastDummyWarn > 10000) {
            Serial.println("[HX711] Dummy gauge not ready — compensation skipped (add 10k\u2126 pull-up on GPIO 36)");
            lastDummyWarn = millis();
        }
    }

    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        rawValues[i] = 0;
    }

    // HX711 outputs 24-bit two's complement data, MSB first
    for (int bit = 23; bit >= 0; bit--) {
        hx711_pulse_sck_read(bit);
    }

    // 25th pulse: set gain = 128 for next conversion
    hx711_pulse_sck_read(-1);

    // Sign extend 24-bit to 32-bit signed long
    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        if (rawValues[i] & 0x800000) {
            rawValues[i] |= 0xFF000000;
        }
    }

    // Detect ADC saturation on raw readings
    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        if (rawValues[i] == HX711_SATURATION_POS) {
            Serial.print("[HX711] SATURATED (+) raw: ");
            Serial.println(CHANNEL_NAMES[i]);
        } else if (rawValues[i] == HX711_SATURATION_NEG) {
            Serial.print("[HX711] SATURATED (-) raw: ");
            Serial.println(CHANNEL_NAMES[i]);
        }
    }

    // Zero out dummy if it wasn't ready (skip compensation)
    if (!dummyReady) {
        rawValues[HX711_NUM_CHANNELS - 1] = 0;
    }

    // Apply dummy compensation and calibration
    hx711_compensate_dummy();

    // Reset error count on successful read
    s_readErrorCount = 0;
    return true;
}

int hx711_get_read_error_count() {
    return s_readErrorCount;
}

void hx711_reset_read_error_count() {
    s_readErrorCount = 0;
}


// =====================================================
// Dummy compensation + per-channel tare
//
// compensated = active channel raw - dummy gauge raw
// published_value = (compensated - offset) * scale
//
// NOTE: With default scale=1.0, the published "strain_vector"
// values are compensated ADC counts (not actual strain).
// The ADC-to-strain conversion (ε = count * 9.31e-10) is
// done on the Python side via CalibrationConfig.adc_to_strain_scale.
// Set scale[i] to non-1.0 ONLY if you want the ESP32 to do
// the conversion itself — but then set Python's
// adc_to_strain_scale to 1.0 to avoid double conversion.
// =====================================================

void hx711_compensate_dummy() {
    long dummy = rawValues[HX711_NUM_CHANNELS - 1];

    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        compensatedRaw[i] = rawValues[i] - dummy;
        strainValues[i] = (compensatedRaw[i] - g_hx711_cal.offset[i]) * g_hx711_cal.scale[i];
    }
}


// =====================================================
// [KEEP IN Hx711_control.cpp]
// 正式保留：给 main / mqtt 使用的 getter functions
// =====================================================

long hx711_get_raw(int channelIndex) {
    if (channelIndex < 0 || channelIndex >= HX711_NUM_CHANNELS) {
        return 0;
    }

    return rawValues[channelIndex];
}

long hx711_get_compensated_raw(int activeIndex) {
    if (activeIndex < 0 || activeIndex >= HX711_NUM_ACTIVE) {
        return 0;
    }

    return compensatedRaw[activeIndex];
}

float hx711_get_strain_value(int activeIndex) {
    if (activeIndex < 0 || activeIndex >= HX711_NUM_ACTIVE) {
        return 0.0;
    }

    return strainValues[activeIndex];
}

const char* hx711_get_channel_name(int channelIndex) {
    if (channelIndex < 0 || channelIndex >= HX711_NUM_CHANNELS) {
        return "invalid";
    }

    return CHANNEL_NAMES[channelIndex];
}


// =====================================================
// [KEEP IN Hx711_control.cpp]
// 正式保留/可选：debug 打印 pin mapping
// =====================================================

void hx711_print_pin_info() {
    Serial.println("HX711 pin mapping:");
    Serial.print("Shared SCK -> GPIO ");
    Serial.println(HX711_SCK);

    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        Serial.print(CHANNEL_NAMES[i]);
        Serial.print(" DT -> GPIO ");
        Serial.println(HX711_DT_PINS[i]);
    }
}


// =====================================================
// [KEEP IN Hx711_control.cpp]
// 正式保留/可选：debug 打印最新数据
// =====================================================

void hx711_print_latest_values() {
    Serial.println("HX711 latest values:");

    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        Serial.print(CHANNEL_NAMES[i]);
        Serial.print(" | raw: ");
        Serial.print(rawValues[i]);
        Serial.print(" | compensated: ");
        Serial.print(compensatedRaw[i]);
        Serial.print(" | strain_value: ");
        Serial.println(strainValues[i], 3);
    }

    Serial.print(CHANNEL_NAMES[HX711_NUM_CHANNELS - 1]);
    Serial.print(" | raw: ");
    Serial.println(rawValues[HX711_NUM_CHANNELS - 1]);
}


// =====================================================
// [KEEP IN Hx711_control.cpp]
// 正式保留：构建 MQTT payload
//
// final demo 中 main.cpp 可以这样用：
// char payload[512];
// hx711_build_sensor_payload(payload, sizeof(payload));
// mqtt_publish_payload(payload);
//
// 如果你的 mqtt_control 目前只有 mqtt_publish_sensor(raw,diff,mV)，
// 后面需要把 MQTT control 扩展成 publish payload/string。
// =====================================================

void hx711_build_sensor_payload(char* buffer, size_t bufferSize) {
    if (bufferSize == 0) {
        return;
    }

    int len = 0;

    // Published values are compensated ADC counts (scale=1.0 by default).
    // Python side converts to strain via CalibrationConfig.adc_to_strain_scale.
    len += snprintf(buffer + len, bufferSize - len,
                    "{\"strain_vector\":[");

    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        len += snprintf(buffer + len, bufferSize - len,
                        "%.3f%s",
                        strainValues[i],
                        (i < HX711_NUM_ACTIVE - 1) ? "," : "");
    }

    len += snprintf(buffer + len, bufferSize - len,
                    "],\"channels\":[");

    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        len += snprintf(buffer + len, bufferSize - len,
                        "\"%s\"%s",
                        CHANNEL_NAMES[i],
                        (i < HX711_NUM_ACTIVE - 1) ? "," : "");
    }

//     len += snprintf(buffer + len, bufferSize - len,
//                     "],\"dummy_raw\":%ld,\"stepper_position\":%ld,\"timestamp\":%lu}",
//                     rawValues[HX711_NUM_CHANNELS - 1],
//                     stepper_get_current_position(),
//                     millis());
// }
    len += snprintf(buffer + len, bufferSize - len,
                    "],\"dummy_raw\":%ld,\"timestamp\":%lu}",
                    rawValues[HX711_NUM_CHANNELS - 1],
                    millis());
}