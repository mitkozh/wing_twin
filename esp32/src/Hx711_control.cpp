#include "Hx711_control.h"

// =====================================================
// [KEEP IN Hx711_control.cpp]
// 正式保留：HX711 shared SCK + 10 independent DT pins
//
// 设计逻辑：
// - 10 个 HX711 共用一个 SCK
// - 每个 HX711 有自己的 DT / DOUT pin
// - 9 个 active channels 对应 wing root/middle/tip + 0/45/90
// - 第 10 个 channel 是 dummy gauge，用于 temperature compensation
// =====================================================


// =====================================================
// [COPY / MODIFY HERE]
// 这里是你之后最需要根据实际接线修改的地方。
// SCK 必须是可输出 GPIO，不能用 GPIO34/35/36/39。
// =====================================================

const int HX711_SCK = 18;  // shared SCK / CLK pin, D18 / GPIO18


// =====================================================
// [COPY / MODIFY HERE]
// 10 个 DT / DOUT pins
//
// 注意：下面 pin 是模板，你需要根据实际接线修改。
// 不要和 RGB、MQTT 无关，但不要和 LED pin 冲突。
// 如果某个 pin 已经被 RGB 用了，就换掉。
// =====================================================

const int DOUT_ROOT_0      = 4;
const int DOUT_ROOT_45     = 25;
const int DOUT_ROOT_90     = 26;

const int DOUT_MIDDLE_0    = 27;
const int DOUT_MIDDLE_45   = 14;
const int DOUT_MIDDLE_90   = 32;

const int DOUT_TIP_0       = 33;
const int DOUT_TIP_45      = 34;
const int DOUT_TIP_90      = 35;

const int DOUT_DUMMY_GAUGE = 36;


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
// [KEEP IN Hx711_control.cpp]
// 正式保留：raw / compensated / strain values
// =====================================================

long rawValues[HX711_NUM_CHANNELS] = {0};

long compensatedRaw[HX711_NUM_ACTIVE] = {0};

float strainValues[HX711_NUM_ACTIVE] = {0.0};

float strainOffset[HX711_NUM_ACTIVE] = {0.0};

// 当前先用 raw count 作为 strain value。
// 之后标定后改这个 scale。
float strainScale = 1.0;


// =====================================================
// [KEEP IN Hx711_control.cpp]
// 正式保留：初始化 HX711 pins
// =====================================================

void hx711_init() {
    Serial.println("Initializing 10-channel HX711 array...");

    pinMode(HX711_SCK, OUTPUT);
    digitalWrite(HX711_SCK, LOW);

    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        pinMode(HX711_DT_PINS[i], INPUT_PULLUP);
    }

    hx711_print_pin_info();

    Serial.println("Waiting for HX711 array to become ready...");

    unsigned long startTime = millis();
    while (!hx711_ready_all()) {
        Serial.println("HX711 array not ready. Check DT/SCK/VCC/GND wiring.");
        delay(500);

        // 防止 final demo 永久卡死
        if (millis() - startTime > 10000) {
            Serial.println("HX711 init timeout. Continue anyway for debugging.");
            return;
        }
    }

    Serial.println("HX711 array ready.");

    // Tare / zero offset
    Serial.println("Taring active channels...");
    const int TARE_SAMPLES = 10;

    long accum[HX711_NUM_ACTIVE] = {0};
    int validSamples = 0;

    for (int s = 0; s < TARE_SAMPLES; s++) {
        if (hx711_read_all_channels()) {
            long dummy = rawValues[HX711_NUM_CHANNELS - 1];

            for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
                accum[i] += rawValues[i] - dummy;
            }

            validSamples++;
        }

        delay(50);
    }

    if (validSamples > 0) {
        for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
            strainOffset[i] = (float)accum[i] / validSamples;
        }

        Serial.println("Tare complete.");
    }
    else {
        Serial.println("Tare failed. No valid HX711 samples.");
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
// [KEEP IN Hx711_control.cpp]
// 正式保留：一次性读取 10 个 HX711
//
// 为什么不用 10 个 HX711 library object？
// 因为你是 shared SCK。
// 如果逐个 scale.read()，读第一个时会把所有 HX711 都 clock 掉，
// 其他 channel 的数据会被破坏。
// 所以 final 版本必须同时读取所有 DT。
// =====================================================

bool hx711_read_all_channels() {
    unsigned long startTime = millis();

    while (!hx711_ready_all()) {
        if (millis() - startTime > 1000) {
            Serial.println("HX711 read timeout.");
            return false;
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

    hx711_compensate_dummy();

    return true;
}


// =====================================================
// [KEEP IN Hx711_control.cpp]
// 正式保留：dummy compensation
//
// compensated = active channel raw - dummy gauge raw
// strainValue = (compensated - zero offset) * scale
// =====================================================

void hx711_compensate_dummy() {
    long dummy = rawValues[HX711_NUM_CHANNELS - 1];

    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        compensatedRaw[i] = rawValues[i] - dummy;
        strainValues[i] = (compensatedRaw[i] - strainOffset[i]) * strainScale;
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

    len += snprintf(buffer + len, bufferSize - len,
                    "],\"dummy_raw\":%ld,\"timestamp\":%lu}",
                    rawValues[HX711_NUM_CHANNELS - 1],
                    millis());
}