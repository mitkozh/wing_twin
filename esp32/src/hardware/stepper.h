#ifndef STEPPER_H
#define STEPPER_H

void stepper_init(void);
void stepper_loop(void);
void stepper_set_target(long steps);
void stepper_reset_position(long pos);
long stepper_get_position(void);
long stepper_get_target(void);
bool stepper_is_moving(void);
void stepper_enable(bool on);

#endif
