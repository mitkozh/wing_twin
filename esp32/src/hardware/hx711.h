#ifndef HX711_H
#define HX711_H

#include <Arduino.h>
#include "../config.h"

extern const int HX711_DT_PINS[];

void   hx711_init(void);
bool   hx711_read_all(void);
int    hx711_get_error_count(void);
void   hx711_reset_error_count(void);

float  hx711_get_strain(int active_index);
long   hx711_get_raw(int channel_index);
long   hx711_get_compensated_raw(int active_index);
float  hx711_get_offset(int active_index);
const char* hx711_get_channel_name(int channel_index);

bool   hx711_tare(void);
bool   hx711_save_calibration(void);
bool   hx711_load_calibration(void);

bool   hx711_get_saturated(int active_index);

#endif
