# Calibration & Hardware Tests

This directory contains calibration and test scripts for the physical
wing rig. Scripts that communicate with the ESP32 via MQTT require
interactive physical setup (hanging weights, disconnecting the stepper, etc.).

---

## Test Order

### Phase 0 — Prerequisites

- MQTT broker running (Mosquitto on port 1883)
- ESP32 powered, connected to WiFi and MQTT
- ESP32 publishing `wing/sensors`, subscribing `wing/control`

### 1. Strain Gauge Calibration (recommended before stepper tests)

Scripts in `calibration/strain/`. Calibrate ADC-to-strain conversion factors.

```bash
python -m calibration.strain.collect       # collect data with known weights
python -m calibration.strain.analyze       # save per-channel calibration
```

You will need: a set of known weights (e.g. 0g, 100g, 200g, 500g, 1000g).

### 2. Stepper Range — motor physical limits

**Setup:** Stepper disconnected from wing (no mechanical load).

Two methods — one requires no hardware:

| Method | Script | Requires | Saves to |
|---|---|---|---|
| **Model** | `python -m calibration.stepper.range_model` | Nothing (pure geometry) | `stepper_calibration_model.json` |
| **Empirical** | `python -m calibration.stepper.range_test` | MQTT + ESP32 + ruler | `stepper_calibration_empirical.json` |

Drive system: **direct-drive winch** — motor shaft has a stepped drum
(16/26/40 mm), fishing wire wraps directly around it. No belts, no gears.

**Model method:** geometry only — `--drum-diameter 26 --travel 140`:
```
steps per rev    = 200 × microstep
wire per rev     = π × drum_diameter
steps per mm     = steps per rev / wire per rev
max steps        = travel × steps per mm
```

**Empirical method:** command known steps (e.g. 1000), measure actual
wire travel with a ruler, then measure total travel. Accounts for wire
layers on the drum.

#### Firmware update

Update `esp32_stepper/src/config.h` after any geometry change:
```c
#define STEPPER_ABSOLUTE_MAX_POSITION 2742  /* physical motor limit — update when drum/travel changes */
#define STEPPER_MIN_POSITION             0
```

`STEPPER_MAX_POSITION` (the safe wing limit) is set at firmware startup and
adjustable at runtime via MQTT: `{"max_position": <steps>}`.
The engine sets it automatically; calibration scripts raise it temporarily.

### 3. Stepper Max Frequency — reliable step rate

**Setup:** Stepper still disconnected from wing.

```bash
python -m calibration.stepper.max_frequency
```

Commands rapid back-and-forth moves; operator presses `p` (pass) or `f`
(fail) at each speed. Last passing speed is saved to
`stepper_calibration_empirical.json`.

### 4. Steps-per-Newton — force vs steps

**Setup:** Reconnect stepper to wing. No weights needed.

Two methods:

| Method | Script | Requires | Saves to |
|---|---|---|---|
| **Model** | `python -m calibration.stepper.steps_per_newton_model` | FEA matrices (`transfer_matrices/`) | `stepper_calibration_model.json` |
| **Empirical** | `python -m calibration.stepper.steps_per_newton` | MQTT + calibrated strain gauges | `stepper_calibration_empirical.json` |

**Model method:** derives `steps_per_newton` from the FEA U matrix and
geometry. Run `range_model` first so `steps_per_mm` is available, or
pass `--steps-per-mm` explicitly:
```
steps_per_newton = steps_per_mm × tip_deformation_mm_per_N
```
```bash
python -m calibration.stepper.steps_per_newton_model --max-newtons 1.75
```

**Empirical method:** commands stepper through a range of positions,
records strain at each position, converts strain → force via the FEA H
matrix, then regresses position vs force:
```bash
python -m calibration.stepper.steps_per_newton --max-newtons 1.75
```

Re-analysis of existing CSV data is supported:
```bash
python -m calibration.stepper.steps_per_newton \
    --analyze-only calibration/stepper/data/steps_per_newton_<ts>.csv \
    --max-newtons 5.0
```

**Prerequisite (empirical only):** Strain calibration must exist at
`calibration/strain/calibration_data.json`.

### Done

Restart the engine (`wing-real-run` or `wing-demo-run`). On startup,
`CalibrationConfig.__post_init__()` loads `stepper_calibration_empirical.json`
first; if all values are null (placeholder) it falls back to
`stepper_calibration_model.json`.

---

## Calibration Files

Two JSON files coexist in `calibration/stepper/`:

| File | Source | When active |
|---|---|---|
| `stepper_calibration_empirical.json` | Hardware runs (`range_test`, `max_frequency`, `steps_per_newton`) | Preferred — overrides model when values are non-null |
| `stepper_calibration_model.json` | FEA/geometry (`range_model`, `steps_per_newton_model`) | Active fallback — used when empirical is empty |

| Field | Model Source | Empirical Source | Description |
|---|---|---|---|
| `steps_per_newton` | `steps_per_newton_model` | `steps_per_newton` | Steps per Newton of force |
| `stepper_motor_max_steps` | `range_model` | `range_test` | Physical max steps (fully wound) |
| `stepper_motor_min_steps` | `range_model` | `range_test` | Physical min (always 0 for winch) |
| `stepper_wing_safe_limit` | `steps_per_newton_model` | `steps_per_newton` | Hard limit to protect wing (≤ motor max) |
| `stepper_max_frequency` | — | `max_frequency` | Max reliable step rate in Hz |
| `steps_per_mm` | `range_model` | `range_test` | Calculated steps-per-mm |
| `drum_diameter_mm` | `range_model` | `range_test` | Drum diameter for reference |
| `microstepping` | `range_model` | `range_test` | TB6600 microstepping setting |
| `linear_travel_mm` | `range_model` | `range_test` | Measured linear travel |

---

## Recovery

### Test interrupted mid-run
Re-run the test. Partial CSVs in `calibration/stepper/data/` can be
deleted.

### MQTT connection failed
- Verify Mosquitto: `netstat -an | findstr 1883`
- Check ESP32 LEDs
- Verify `mosquitto_project.conf` matches scripts (default 1883)
- Try: `python -c "import paho.mqtt.client as mqtt; c=mqtt.Client(); c.connect('localhost',1883,60)"`

### No sensor data during collection
- Check ESP32 publishing `wing/sensors` with MQTT Explorer
- Verify topic strings match config
- Check ESP32 MQTT connection (green LEDs)

### Calibration file corrupt
Delete the offending `.json`. The engine falls back to the other file,
then to hardcoded defaults. Re-run scripts to regenerate:
```bash
python -m calibration.stepper.range_model --drum-diameter 26 --travel 140
python -m calibration.stepper.steps_per_newton_model --max-newtons 1.75
python -m calibration.stepper.max_frequency  # if hardware available
```

### Strain calibration file corrupt
Delete `calibration/strain/calibration_data.json`. Engine falls back to
global ADC-to-strain scale. Re-run `collect` and `analyze`.

### Steps-per-newton data looks wrong
Re-analyze existing CSV data:
```bash
python -m calibration.stepper.steps_per_newton \
    --analyze-only calibration/stepper/data/steps_per_newton_<ts>.csv \
    --max-newtons 5.0
```

---

## Quick Reference

```bash
# Model-based (no hardware) — run anytime
python -m calibration.stepper.range_model --drum-diameter 26 --travel 140
python -m calibration.stepper.steps_per_newton_model --max-newtons 1.75

# Empirical (needs hardware) — recommended order
python -m calibration.strain.collect
python -m calibration.strain.analyze
python -m calibration.stepper.range_test           # disconnect wing
python -m calibration.stepper.max_frequency         # still disconnected
python -m calibration.stepper.steps_per_newton      # reconnect wing

# Restart engine
```
