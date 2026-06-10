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


def log_imputed_channels(
    strain_vec: np.ndarray,
    imputed_vec: np.ndarray,
    bad_indices: list[int],
    channel_names: list[str],
) -> None:
    if not bad_indices:
        return

    for k in bad_indices:
        raw_val = strain_vec[k]
        imputed_val = imputed_vec[k] if k < len(imputed_vec) else float("nan")
        delta = abs(raw_val - imputed_val) if k < len(imputed_vec) else float("nan")
        name = channel_names[k] if k < len(channel_names) else str(k)
        if delta > 1e-8:
            logger.warning(
                "Imputed channel %s: %.6f -> %.6f (delta=%.6f)",
                name, raw_val, imputed_val, delta,
            )
