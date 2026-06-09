// TODO: This module is ready for when the stepper motor hardware is installed.
//       The strain-guided zero calibration (stepper_zero_with_feedback()) uses
//       HX711 readings to find the true zero position when the pull-string goes
//       slack, correcting for any lost steps.
//
// To enable:
//   1. main.cpp:      uncomment #include "Stepper_control.h", stepper_init(),
//                     stepper_zero_with_feedback(), and stepper_loop()
//   2. mqtt_control.cpp: uncomment the "Stepper position" block in mqtt_callback()
//   3. Hx711_control.cpp: uncomment stepper payload fields

#ifndef STEPPER_CONTROL_H
#define STEPPER_CONTROL_H

#include <Arduino.h>

// =====================================================
// Stepper motor interface
//
// Uses STEP + DIR + ENABLE pins.
// Receives target position from MQTT and moves toward it
// with a simple acceleration ramp in stepper_loop().
// =====================================================

void stepper_init();
void stepper_loop();
void stepper_set_target(long targetSteps);
void stepper_zero_with_feedback();
long stepper_get_current_position();
long stepper_get_home_offset();
bool stepper_is_moving();

#endif