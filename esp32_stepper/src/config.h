#ifndef CONFIG_H
#define CONFIG_H

#define STEPPER_MAX_SPEED        1000.0f
#define STEPPER_ACCELERATION     600.0f
#define STEPPER_POSITION_TOLERANCE 5
#define STEPPER_MIN_POSITION     0      /* update after running `range_test.py` (winch: always 0) */
#define STEPPER_MAX_POSITION     2720   /* update after running `range_test.py` */

#define WIFI_TIMEOUT_MS          15000
#define WIFI_CONNECT_COOLDOWN_MS 500
#define WIFI_MAX_RETRY_MS        5000

#define MQTT_MAX_RETRY_MS        5000U
#define MQTT_RETRY_BASE_MS        200U

#define WATCHDOG_TIMEOUT_S       5

#define STATUS_PUBLISH_INTERVAL_MS 100

#endif
