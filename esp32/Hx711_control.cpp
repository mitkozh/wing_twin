#include "Hx711_control.h"

const int HX711_SCK = 27;

const int DOUT_ROOT_0      = 14;
const int DOUT_ROOT_45     = 12;
const int DOUT_ROOT_90     = 26;

const int DOUT_MIDDLE_0    = 25;
const int DOUT_MIDDLE_45   = 33;
const int DOUT_MIDDLE_90   = 18;

const int DOUT_TIP_0       = 22;
const int DOUT_TIP_45      = 23; // These serial ports may change depending on the actual setup.
const int DOUT_TIP_90      = 4;

const int DOUT_DUMMY_GAUGE = 15;

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

long rawValues[HX711_NUM_CHANNELS] = {0};
long compensatedRaw[HX711_NUM_ACTIVE] = {0};
float strainValues[HX711_NUM_ACTIVE] = {0.0};
float strainOffset[HX711_NUM_ACTIVE] = {0.0};

float strainScale = 1.0;

void hx711_init() {
    Serial.println("Initializing HX711 array...");

    pinMode(HX711_SCK, OUTPUT);
    digitalWrite(HX711_SCK, LOW);

    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        pinMode(HX711_DT_PINS[i], INPUT_PULLUP);
    }

    hx711_print_pin_info();

    unsigned long startTime = millis();

    while (!hx711_ready_all()) {
        Serial.println("HX711 array not ready.");
        delay(500);

        if (millis() - startTime > 10000) {
            Serial.println("HX711 init timeout. Continue for debugging.");
            return;
        }
    }

    Serial.println("HX711 array ready.");
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
    } else {
        Serial.println("Tare failed.");
    }
}

bool hx711_ready_all() {
    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        if (digitalRead(HX711_DT_PINS[i]) != LOW) {
            return false;
        }
    }

    return true;
}

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

    for (int bit = 23; bit >= 0; bit--) {
        hx711_pulse_sck_read(bit);
    }

    hx711_pulse_sck_read(-1);

    for (int i = 0; i < HX711_NUM_CHANNELS; i++) {
        if (rawValues[i] & 0x800000) {
            rawValues[i] |= 0xFF000000;
        }
    }

    hx711_compensate_dummy();

    return true;
}

void hx711_compensate_dummy() {
    long dummy = rawValues[HX711_NUM_CHANNELS - 1];

    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        compensatedRaw[i] = rawValues[i] - dummy;
        strainValues[i] = (compensatedRaw[i] - strainOffset[i]) * strainScale;
    }
}

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

void hx711_build_sensor_payload(char* buffer, size_t bufferSize) {
    if (bufferSize == 0) {
        return;
    }

    int len = 0;

    len += snprintf(buffer + len, bufferSize - len, "{\"strain_vector\":[");

    for (int i = 0; i < HX711_NUM_ACTIVE; i++) {
        len += snprintf(buffer + len, bufferSize - len,
                        "%.3f%s",
                        strainValues[i],
                        (i < HX711_NUM_ACTIVE - 1) ? "," : "");
    }

    len += snprintf(buffer + len, bufferSize - len, "],\"channels\":[");

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
