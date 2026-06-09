#ifndef ZERO_H
#define ZERO_H

typedef float (*zero_strain_reader_t)(int channel);
typedef void   (*zero_stepper_mover_t)(long target);
typedef long   (*zero_position_getter_t)(void);
typedef void   (*zero_wait_fn_t)(unsigned long timeout_ms);

typedef struct {
    zero_strain_reader_t   read_strain;
    zero_stepper_mover_t   move_to;
    zero_position_getter_t get_position;
    zero_wait_fn_t         wait_for_motor;
} zero_callbacks_t;

void zero_init(zero_callbacks_t cbs);
bool zero_run(void);
long zero_get_offset(void);

#endif
