# Calibration & Hardware Tests

This directory contains calibration and test scripts for the physical
wing rig. All scripts communicate with the ESP32 via MQTT and most
require interactive physical setup (hanging weights, disconnecting
the stepper, etc.).

---

## Test Order

### Phase 0 — Prerequisites

Before running any tests:
- MQTT broker must be running (Mosquitto on port 1883, or as configured)
- ESP32 must be powered, connected to WiFi and MQTT
- ESP32 must be responsive (`wing/sensors` publishing, `wing/control` subscribing)

### 1. Strain Gauge Calibration (recommended before stepper tests)

These scripts are in `calibration/strain/`. They calibrate the ADC-to-strain
conversion factors used by the engine.

```bash
# Collect sensor data with known weights at the wing tip
python -m calibration.strain.collect

# Analyze data and save per-channel calibration
python -m calibration.strain.analyze
```

You will need: a set of known weights (e.g. 0g, 100g, 200g, 500g, 1000g).

### 2. Stepper Range Test — motor physical limits

**Setup:** Disconnect the stepper cable from the wing (no load).

```bash
python -m calibration.stepper.range_test
```

This sweeps the stepper through its full range (min to max) and records
commanded vs actual positions. Saves `stepper_motor_max_steps` and
`stepper_motor_min_steps` to `stepper_calibration.json`.

### 3. Stepper Max Frequency Test — reliable step rate

**Setup:** Stepper still disconnected from the wing.

```bash
python -m calibration.stepper.max_frequency
```

Commands rapid back-and-forth moves and measures the actual achieved
step rate from MQTT position data. Saves `stepper_max_frequency` to
`stepper_calibration.json`.

### 4. Steps-per-Newton Calibration — force vs steps

**Setup:** Reconnect the stepper to the wing. No weights needed.

```bash
python -m calibration.stepper.steps_per_newton
```

- Commands the stepper through a range of positions
- At each position, records strain from the calibrated strain gauges
- Converts strain -> force using the FEA H matrix (no weights required)
- Linear regression: stepper_position = steps_per_newton × force
- Saves `steps_per_newton` to `stepper_calibration.json`
- Prompts for **max Newtons** the wing should experience
- Calculates and saves `stepper_wing_safe_limit` (= steps_per_newton × max Newtons)

**Prerequisite:** Strain calibration must exist at `calibration/strain/calibration_data.json`.

### Done

Restart the engine (`wing-real-run` or `wing-demo-run`). On startup,
`CalibrationConfig.__post_init__()` auto-loads all values from
`calibration/stepper/stepper_calibration.json`.

---

## Calibration File: `stepper_calibration.json`

Each stepper test script reads the existing file, updates its field(s),
and writes it back. The file lives at `calibration/stepper/stepper_calibration.json`.

| Field | Source Test | Description |
|---|---|---|
| `steps_per_newton` | `steps_per_newton.py` | Steps per Newton of aerodynamic force |
| `stepper_motor_max_steps` | `range_test.py` | Physical max steps the motor can reach |
| `stepper_motor_min_steps` | `range_test.py` | Physical min steps the motor can reach |
| `stepper_wing_safe_limit` | `steps_per_newton.py` | Hard limit to protect the wing (≤ motor max) |
| `stepper_max_frequency` | `max_frequency.py` | Max reliable step rate in Hz |

---

## Recovery

### Test was interrupted mid-run
Re-run the test. Data from the interrupted run may be in
`calibration/stepper/data/` and can be ignored or deleted.

### MQTT connection failed
- Verify Mosquitto is running: `netstat -an | findstr 1883`
- Check ESP32 is powered and LEDs show green
- Verify `mosquitto_project.conf` matches port in scripts (default 1883)
- Try: `python -c "import paho.mqtt.client as mqtt; c=mqtt.Client(); c.connect('localhost',1883,60)"`

### No sensor data received during collection
- Check ESP32 is publishing to `wing/sensors` (use MQTT Explorer or `mosquitto_sub -t wing/sensors -v`)
- Verify ESP32 is connected to MQTT (LEDs should be green)
- Check the sensor topic string in the scripts matches your config

### Calibration file (`stepper_calibration.json`) is corrupt
Delete it. The engine will use hardcoded defaults (steps_per_newton=204,
stepper_wing_safe_limit=2500, stepper_max_frequency=1000).
Re-run the three stepper tests to regenerate.

### Strain calibration file (`calibration/strain/calibration_data.json`) is corrupt
Delete it. The engine falls back to a global ADC-to-strain scale.
Re-run `calibration/strain/collect.py` and `calibration/strain/analyze.py`.

### Steps-per-newton data looks wrong or wing safe limit needs changing
Re-analyze existing CSV data with the `--analyze-only` flag.
Use `--max-newtons` to skip the prompt:

```bash
# Re-analyze (will prompt for max Newtons)
python -m calibration.stepper.steps_per_newton \
    --analyze-only calibration/stepper/data/steps_per_newton_<timestamp>.csv

# Re-analyze with a specific max Newtons (no prompt)
python -m calibration.stepper.steps_per_newton \
    --analyze-only calibration/stepper/data/steps_per_newton_<timestamp>.csv \
    --max-newtons 5.0
```

---

## Quick Reference

```bash
# Full calibration pipeline (recommended order)

# 1. Strain calibration (wing + weights)
python -m calibration.strain.collect
python -m calibration.strain.analyze

# 2. Stepper range (disconnect wing)
python -m calibration.stepper.range_test

# 3. Stepper max frequency (still disconnected)
python -m calibration.stepper.max_frequency

# 4. Steps-per-newton (reconnect wing, no weights)
python -m calibration.stepper.steps_per_newton

# 5. Restart engine
```
