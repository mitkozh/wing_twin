#ifndef CONFIG_H
#define CONFIG_H

// Stepper motor
#define STEPPER_MAX_SPEED        1000.0f   // steps/sec
#define STEPPER_ACCELERATION     600.0f    // steps/sec^2
#define STEPPER_POSITION_TOLERANCE 5
#define STEPPER_MIN_POSITION     -500
#define STEPPER_MAX_POSITION     2720

// HX711
#define HX711_NUM_ACTIVE         9
#define HX711_NUM_CHANNELS       10
#define HX711_READ_TIMEOUT_MS    100

// Zero calibration
#define ZERO_NUM_SAMPLES         10
#define ZERO_STRAIN_THRESHOLD    5000.0f
#define ZERO_SLACK_STABLE_THRESHOLD 500.0f
#define ZERO_MAX_FORWARD_ITER    300
#define ZERO_MOVE_TIMEOUT_MS     5000
#define ZERO_FORWARD_TIMEOUT_MS  500
#define CONTACT_CONFIRM_NEEDED   3

// WiFi
#define WIFI_TIMEOUT_MS          15000
#define WIFI_CONNECT_COOLDOWN_MS 500
#define WIFI_MAX_RETRY_MS        5000

// MQTT
#define MQTT_MAX_RETRY_MS        5000U
#define MQTT_RETRY_BASE_MS        200U
#define MQTT_POSITION_TIMEOUT_MS  30000

// Watchdog
#define WATCHDOG_TIMEOUT_S       5

// Drift correction for strain gauges
#define DRIFT_EMA_ALPHA             0.001f    // ~100s baseline tracking time constant at 100ms
#define DRIFT_VAR_ALPHA             0.01f     // ~10s variance tracking
#define DRIFT_STABLE_VAR            3.0f      // Max compensatedRaw variance for idle detection
#define DRIFT_IDLE_MIN_CYCLES       300       // ~30s idle before correction starts
#define DRIFT_CORRECT_RATE          0.0001f   // ~16min full correction
#define DRIFT_CORRECT_MIN_DELTA     1.0f      // Minimum offset change to bother applying

// Tare
#define TARE_GROUPS                 5
#define TARE_SAMPLES_PER_GROUP      10
#define TARE_TOTAL_SAMPLES          (TARE_GROUPS * TARE_SAMPLES_PER_GROUP)

// Sensor publish
#define PUBLISH_INTERVAL_MS      100

#endif
