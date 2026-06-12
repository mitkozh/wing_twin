import time
from typing import Optional

import numpy as np

from wing_twin.config import MqttConfig
from wing_twin.config.calibration import CalibrationConfig
from wing_twin.io.mqtt import MqttHandler, MqttPublisher
from wing_twin.io.logger import get_logger

logger = get_logger(__name__)


def _wait_for_stepper_idle(
    handler: MqttHandler,
    timeout_s: float,
    poll_s: float,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not handler.latest_stepper.moving:
            return True
        time.sleep(poll_s)
    return False


def _read_strain_sample(handler: MqttHandler) -> Optional[np.ndarray]:
    buffers = handler.sensor_buffers
    if "esp32" not in buffers or not buffers["esp32"]:
        return None
    raw_vals, offset_vals, dummy_raw, saturated, ts = buffers["esp32"][-1]
    return raw_vals.astype(np.float64)


def _sample_baseline(
    handler: MqttHandler,
    num_samples: int,
    num_channels: int,
) -> Optional[np.ndarray]:
    accum = np.zeros(num_channels, dtype=np.float64)
    count = 0
    for _ in range(num_samples * 2):
        sample = _read_strain_sample(handler)
        if sample is not None:
            accum += sample - np.mean(sample)
            count += 1
            if count >= num_samples:
                break
        time.sleep(0.025)
    if count == 0:
        return None
    return accum / count


def _max_delta(sample: np.ndarray, baseline: np.ndarray) -> float:
    return float(np.max(np.abs(sample - baseline)))


def calibrate_stepper(
    mqtt_publisher: MqttPublisher,
    mqtt_handler: MqttHandler,
    mqtt_config: MqttConfig,
    calib_config: CalibrationConfig,
) -> bool:
    if not mqtt_handler.latest_stepper:
        logger.error("No stepper state available - aborting calibration")
        return False

    if not mqtt_handler.latest_stepper.mid_move:
        logger.info("Stepper was not mid-move - skipping calibration")
        return False

    logger.info("Starting stepper calibration (binary search)...")

    min_pos = calib_config.stepper_min_position
    max_pos = calib_config.stepper_motor_max_steps
    coarse = calib_config.stepper_coarse_step
    threshold = calib_config.stepper_strain_threshold
    num_samples = calib_config.stepper_calibration_num_samples
    poll_s = calib_config.stepper_calibration_poll_s
    move_to = calib_config.stepper_calibration_move_timeout_s
    retract_to = calib_config.stepper_calibration_retract_timeout_s
    num_channels = len(calib_config.channel_names)

    # 1. Retract fully to slack position
    logger.info("Retracting to min position %d...", min_pos)
    mqtt_publisher.publish(mqtt_config.stepper_command_topic, {"position": min_pos})
    if not _wait_for_stepper_idle(mqtt_handler, retract_to, poll_s):
        logger.error("Retract timeout")
        return False

    # 2. Sample baseline strain at slack
    baseline = _sample_baseline(mqtt_handler, num_samples, num_channels)
    if baseline is None:
        logger.error("Failed to read baseline strain")
        return False
    logger.info("Baseline acquired")

    # 3. Coarse search forward in coarse-step increments
    contact_pos = None
    for pos in range(min_pos, max_pos + 1, coarse):
        mqtt_publisher.publish(mqtt_config.stepper_command_topic, {"position": pos})
        if not _wait_for_stepper_idle(mqtt_handler, move_to, poll_s):
            logger.warning("Move timeout at position %d", pos)
            return False

        sample = _read_strain_sample(mqtt_handler)
        if sample is None:
            continue

        delta = _max_delta(sample, baseline)
        logger.debug("  pos=%d delta=%.1f", pos, delta)

        if delta > threshold:
            contact_pos = pos
            logger.info("Contact detected at %d (delta=%.1f)", pos, delta)
            break

    if contact_pos is None:
        logger.error("No contact found within range")
        return False

    # 4. Binary search backwards to find exact contact edge
    low = max(contact_pos - coarse, min_pos)
    high = contact_pos

    for _ in range(10):
        mid = (low + high) // 2
        if mid == low:
            break

        mqtt_publisher.publish(mqtt_config.stepper_command_topic, {"position": mid})
        if not _wait_for_stepper_idle(mqtt_handler, move_to, poll_s):
            return False

        sample = _read_strain_sample(mqtt_handler)
        if sample is None:
            continue

        delta = _max_delta(sample, baseline)
        logger.debug("  binary: mid=%d delta=%.1f (low=%d high=%d)", mid, delta, low, high)

        if delta > threshold:
            high = mid
        else:
            low = mid

    # 5. Move to zero position and reset counter
    zero_pos = low
    logger.info("Zero position found at %d", zero_pos)

    mqtt_publisher.publish(mqtt_config.stepper_command_topic, {"position": zero_pos})
    _wait_for_stepper_idle(mqtt_handler, move_to, poll_s)

    mqtt_publisher.publish(mqtt_config.stepper_command_topic, {"reset_position": 0})
    time.sleep(0.5)
    logger.info("Calibration complete - stepper zero set")
    return True
