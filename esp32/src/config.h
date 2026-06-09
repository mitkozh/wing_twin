#ifndef CONFIG_H
#define CONFIG_H

// Stepper motor
#define STEPPER_MAX_RATE_US      1000
#define STEPPER_MIN_RATE_US      2000
#define STEPPER_ACCEL_STEPS      200
#define STEPPER_POSITION_TOLERANCE 5
#define STEPPER_MIN_POSITION     -500
#define STEPPER_MAX_POSITION     2720

// HX711
#define HX711_NUM_ACTIVE         9
#define HX711_NUM_CHANNELS       10
#define HX711_READ_TIMEOUT_MS    1000

// Zero calibration
#define ZERO_NUM_SAMPLES         10
#define ZERO_STRAIN_THRESHOLD    0.005f
#define ZERO_SLACK_SAFE_MARGIN   100
#define ZERO_MAX_FORWARD_ITER    50
#define ZERO_MOVE_TIMEOUT_MS     5000
#define ZERO_FORWARD_TIMEOUT_MS  500

// WiFi
#define WIFI_TIMEOUT_MS          15000
#define WIFI_CONNECT_COOLDOWN_MS 2000

// MQTT
#define MQTT_MAX_RETRY_MS        60000
#define MQTT_RETRY_BASE_MS        2000
#define MQTT_POSITION_TIMEOUT_MS  5000

// Watchdog
#define WATCHDOG_TIMEOUT_S       5

// Sensor publish
#define PUBLISH_INTERVAL_MS      1000

#endif
