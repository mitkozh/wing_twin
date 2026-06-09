#ifndef PINS_H
#define PINS_H

// Stepper motor
#define STEP_PIN      13
#define DIR_PIN       21
#define ENABLE_PIN    23

// HX711 strain gauges - shared SCK + 10 independent DT pins
#define HX711_SCK          18

#define DOUT_ROOT_0        15
#define DOUT_ROOT_45       25
#define DOUT_ROOT_90       26

#define DOUT_MIDDLE_0      27
#define DOUT_MIDDLE_45     14
#define DOUT_MIDDLE_90     32

#define DOUT_TIP_0         33
#define DOUT_TIP_45        34
#define DOUT_TIP_90        35

#define DOUT_DUMMY_GAUGE   36

// RGB feedback LEDs - 3 LEDs × red+green channels
#define LED1_STATUS_GREEN  16
#define LED1_STATUS_RED     4

#define LED2_STATUS_RED     5
#define LED2_STATUS_GREEN  19

#define LED3_STATUS_GREEN  17
#define LED3_STATUS_RED    22

#endif
