#ifndef CONFIG_H
#define CONFIG_H

#define STEPPER_MAX_SPEED        4000.0f
#define STEPPER_ACCELERATION     3000.0f
#define STEPPER_POSITION_TOLERANCE 3
#define STEPPER_MIN_POSITION         0
#define STEPPER_MAX_POSITION         1503   /* safe wing limit (1.8 N × 834.96 steps/N), adjustable at runtime */
#define STEPPER_ABSOLUTE_MAX_POSITION 4456  /* physical motor limit from calibration, hard hardware stop */

#define WIFI_TIMEOUT_MS          15000
#define WIFI_CONNECT_COOLDOWN_MS 500
#define WIFI_MAX_RETRY_MS        5000

#define MQTT_MAX_RETRY_MS        5000U
#define MQTT_RETRY_BASE_MS        200U

#define WATCHDOG_TIMEOUT_S       5

#define STATUS_PUBLISH_INTERVAL_MS 50

#endif
