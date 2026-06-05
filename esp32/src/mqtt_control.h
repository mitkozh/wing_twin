#ifndef MQTT_CONTROL_H
#define MQTT_CONTROL_H

#include <Arduino.h>

// =====================================================
// MQTT module public interface
// =====================================================

void mqtt_init();
void mqtt_loop();
bool mqtt_is_connected();

void mqtt_publish_sensor(long raw, long diff, float voltage_mV);
void mqtt_publish_payload(const char* payload);

#endif