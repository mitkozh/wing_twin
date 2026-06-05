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
long stepper_get_current_position();
bool stepper_is_moving();

#endif