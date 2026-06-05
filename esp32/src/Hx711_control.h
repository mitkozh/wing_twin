#ifndef HX711_CONTROL_H
#define HX711_CONTROL_H

#include <Arduino.h>

// =====================================================
// HX711 channel count
// 9 active strain channels + 1 dummy gauge
// =====================================================

const int HX711_NUM_ACTIVE = 9;
const int HX711_NUM_CHANNELS = 10;


// =====================================================
// Calibration data per active channel
// Stored in LittleFS so it survives reboots
// =====================================================

struct Hx711Calibration {
    float scale[HX711_NUM_ACTIVE];      // per-channel scale (default 1.0 = ADC counts)
    float offset[HX711_NUM_ACTIVE];     // tare offset (compensated ADC counts)
    bool  valid;                        // true if calibration has been saved
};

bool hx711_load_calibration(Hx711Calibration &cal);
bool hx711_save_calibration(const Hx711Calibration &cal);
bool hx711_auto_tare(Hx711Calibration &cal);


// =====================================================
// Public functions
// =====================================================

void hx711_init();

bool hx711_ready_all();

bool hx711_read_all_channels();

void hx711_compensate_dummy();

long hx711_get_raw(int channelIndex);

long hx711_get_compensated_raw(int activeIndex);

float hx711_get_strain_value(int activeIndex);

const char* hx711_get_channel_name(int channelIndex);

void hx711_print_pin_info();

void hx711_print_latest_values();

void hx711_build_sensor_payload(char* buffer, size_t bufferSize);

int  hx711_get_read_error_count();
void hx711_reset_read_error_count();

#endif