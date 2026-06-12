"""
Unity heatmap colour gradient for LED feedback.
"""

# Gradient from TwinScene.unity (8 stops, linear blend)
# (t, R, G, B)  —  t = normalized stress/damage 0..1
_UNITY_GRADIENT = [
    (0.000, 0.0, 0.0, 1.0),        # Blue
    (0.125, 0.0, 0.698, 1.0),      # Light Blue
    (0.250, 0.0, 1.0, 0.935),      # Cyan
    (0.375, 0.0, 1.0, 0.297),      # Green
    (0.500, 0.698, 1.0, 0.0),      # Yellow-Green
    (0.625, 1.0, 1.0, 0.0),        # Yellow
    (0.750, 1.0, 0.698, 0.0),      # Orange
    (1.000, 1.0, 0.0, 0.0),        # Red
]


def heatmap_color(t: float) -> tuple[float, float, float]:
    t = max(0.0, min(1.0, t))
    for i in range(len(_UNITY_GRADIENT) - 1):
        t0, r0, g0, b0 = _UNITY_GRADIENT[i]
        t1, r1, g1, b1 = _UNITY_GRADIENT[i + 1]
        if t0 <= t <= t1:
            frac = (t - t0) / (t1 - t0)
            return (
                round(r0 + (r1 - r0) * frac, 3),
                round(g0 + (g1 - g0) * frac, 3),
                round(b0 + (b1 - b0) * frac, 3),
            )
    return (1.0, 0.0, 0.0)
