#include "rgb.h"
#include "../pins.h"

// 3 feedback LEDs with full RGB PWM control.
// LED1 = tip, LED2 = span, LED3 = root.
// Input: float[3] {R, G, B} each 0.0 - 1.0

#define PWM_FREQ      5000
#define PWM_RES       8       // 8-bit -> duty 0-255

// LEDC channel assignment (ESP32 has 16 channels)
#define CH_RED_1   0
#define CH_GREEN_1 1
#define CH_BLUE_1  2
#define CH_RED_2   3
#define CH_GREEN_2 4
#define CH_BLUE_2  5
#define CH_RED_3   6
#define CH_GREEN_3 7
#define CH_BLUE_3  8

static void led_pwm_init(int ch, int pin) {
    ledcSetup(ch, PWM_FREQ, PWM_RES);
    ledcAttachPin(pin, ch);
}

static void led_pwm_set(int ch, float val) {
    if (val < 0.0f) val = 0.0f;
    if (val > 1.0f) val = 1.0f;
    ledcWrite(ch, (int)(val * 255.0f));
}

void rgb_init(void) {
    led_pwm_init(CH_RED_1,   LED1_STATUS_RED);
    led_pwm_init(CH_GREEN_1, LED1_STATUS_GREEN);
    led_pwm_init(CH_BLUE_1,  LED1_STATUS_BLUE);

    led_pwm_init(CH_RED_2,   LED2_STATUS_RED);
    led_pwm_init(CH_GREEN_2, LED2_STATUS_GREEN);
    led_pwm_init(CH_BLUE_2,  LED2_STATUS_BLUE);

    led_pwm_init(CH_RED_3,   LED3_STATUS_RED);
    led_pwm_init(CH_GREEN_3, LED3_STATUS_GREEN);
    led_pwm_init(CH_BLUE_3,  LED3_STATUS_BLUE);

    rgb_all_off();
}

void rgb_all_off(void) {
    for (int ch = 0; ch <= 8; ch++) ledcWrite(ch, 0);
}

void rgb_set_all(const float led1[3], const float led2[3], const float led3[3]) {
    led_pwm_set(CH_RED_1,   led1[0]); led_pwm_set(CH_GREEN_1, led1[1]); led_pwm_set(CH_BLUE_1, led1[2]);
    led_pwm_set(CH_RED_2,   led2[0]); led_pwm_set(CH_GREEN_2, led2[1]); led_pwm_set(CH_BLUE_2, led2[2]);
    led_pwm_set(CH_RED_3,   led3[0]); led_pwm_set(CH_GREEN_3, led3[1]); led_pwm_set(CH_BLUE_3, led3[2]);
    Serial.printf("[RGB] (%.2f,%.2f,%.2f) (%.2f,%.2f,%.2f) (%.2f,%.2f,%.2f)\n",
        led1[0], led1[1], led1[2],
        led2[0], led2[1], led2[2],
        led3[0], led3[1], led3[2]);
}


