#ifndef RGB_H
#define RGB_H

#include <Arduino.h>

void rgb_init(void);
void rgb_set_all(const float led1[3], const float led2[3], const float led3[3]);
void rgb_all_off(void);


#endif
