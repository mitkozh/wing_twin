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
bool stepper_is_enabled(void);
bool stepper_save_position(void);
bool stepper_load_position(long* out_pos);
void stepper_set_dirty(bool dirty);
bool stepper_was_mid_move(void);

#endif
