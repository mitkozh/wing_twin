#ifndef HX711_CONTROL_H
#define HX711_CONTROL_H

#include <Arduino.h>

// =====================================================
// [KEEP IN Hx711_control.h]
// 正式保留：HX711 channel 数量定义
// 9 active strain channels + 1 dummy gauge
// =====================================================

const int HX711_NUM_ACTIVE = 9;
const int HX711_NUM_CHANNELS = 10;


// =====================================================
// [KEEP IN Hx711_control.h]
// 正式保留：HX711 模块对 main.cpp 暴露的函数
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


// =====================================================
// [KEEP IN Hx711_control.h]
// 正式保留：给 MQTT final demo 使用
//
// final 里可以用这个函数把 9 个 active channels
// 打包成 JSON payload，然后通过 MQTT 发出去。
// =====================================================

void hx711_build_sensor_payload(char* buffer, size_t bufferSize);

#endif