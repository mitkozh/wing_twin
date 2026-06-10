import logging

import numpy as np

logger = logging.getLogger(__name__)


def detect_bad_channels(strain_vec: np.ndarray, threshold: float) -> list[int]:
    return sorted(np.where(np.abs(strain_vec) > threshold)[0].tolist())


def impute_channels(
    strain_vec: np.ndarray,
    bad_indices: list[int],
    H: np.ndarray,
) -> np.ndarray:
    result = strain_vec.copy()
    if not bad_indices:
        return result

    mask = np.ones(H.shape[0], dtype=bool)
    for k in bad_indices:
        mask[k] = False

    H_reduced = H[mask, :]
    strain_reduced = strain_vec[mask]

    if H_reduced.shape[0] < H_reduced.shape[1]:
        logger.warning(
            "Underdetermined system: %d gauges remain for %d force modes",
            H_reduced.shape[0], H_reduced.shape[1],
        )

    F, _, _, _ = np.linalg.lstsq(H_reduced, strain_reduced, rcond=None)

    for k in bad_indices:
        result[k] = float(H[k, :] @ F)

    return result


class ChannelHealthTracker:
    """Tracks sensor channel health for telemetry."""

    def __init__(self, channel_names: list[str]):
        self._channel_names = list(channel_names)
        self._previously_bad: set[int] = set()

    def update(self, bad_indices: list[int]) -> list[dict]:
        """Compare current bad set with previous and return event dicts.

        Returns a list of event dicts for each state change.
        """
        current_bad = set(bad_indices)
        entered = current_bad - self._previously_bad
        recovered = self._previously_bad - current_bad
        events = []

        for i in sorted(entered):
            name = self._channel_names[i] if i < len(self._channel_names) else str(i)
            events.append({"channel": i, "name": name, "type": "bad"})

        for i in sorted(recovered):
            name = self._channel_names[i] if i < len(self._channel_names) else str(i)
            events.append({"channel": i, "name": name, "type": "recovered"})

        self._previously_bad = current_bad
        return events

    @property
    def bad_channels(self) -> set[int]:
        return set(self._previously_bad)
