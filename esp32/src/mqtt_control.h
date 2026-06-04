#ifndef MQTT_CONTROL_H
#define MQTT_CONTROL_H

#include <Arduino.h>

// =====================================================
// [KEEP IN mqtt_control.h]
// 正式保留：MQTT module public interface
// main.cpp / mqtt_test.cpp 会调用这些函数
// =====================================================


// =====================================================
// [KEEP]
// 初始化 WiFi + MQTT server + MQTT callback
// =====================================================
void mqtt_init();


// =====================================================
// [KEEP]
// 在 main loop 中持续调用
// 作用：
// 1. 保持 MQTT 连接
// 2. 接收 server 发来的 wing/control 指令
// =====================================================
void mqtt_loop();


// =====================================================
// [KEEP]
// 测试用/单通道用 publish function
// mqtt_test.cpp 可以用 fake raw/diff/mV 测试 MQTT
// =====================================================
void mqtt_publish_sensor(long raw, long diff, float voltage_mV);


// =====================================================
// [KEEP]
// final demo 用 publish function
// Hx711_control.cpp 先 build 完整 JSON payload
// main.cpp 再调用这个函数发送
// =====================================================
void mqtt_publish_payload(const char* payload);

#endif