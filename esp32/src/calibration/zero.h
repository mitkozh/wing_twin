#ifndef ZERO_H
#define ZERO_H

#include <Arduino.h>

void zero_init(void);
bool zero_run(void);
long zero_get_offset(void);
void zero_update_stepper_state(long position, bool moving, bool online);
bool zero_is_stepper_ready(void);

#endif
