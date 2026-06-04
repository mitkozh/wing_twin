#ifndef RGB_CONTROL_H
#define RGB_CONTROL_H

#include <Arduino.h>

// =====================================================
// [KEEP IN RGB_control.h]
// 正式保留：RGB 模块对外提供的函数声明
// main.cpp 和 mqtt_control.cpp 之后都会调用这些函数
// =====================================================


void rgb_init();
void all_leds_off();
void set_leds(String command);
void print_rgb_pin_info();

#endif