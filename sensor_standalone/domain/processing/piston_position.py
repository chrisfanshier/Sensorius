"""
Piston position estimation.

Calculates an estimated piston position depth trace from weight-stand
and release-device depth series, scope, and core length.

All internal calculations are in **meters**.  The scope and core_length
parameters stored in CSV metadata are in **feet**; they are converted
here using the constant ``FT_TO_M = 1 / 3.28``.

The detection algorithm mirrors the reference implementation:

1. **Before trip_time** the piston position is always computed from the
   weight-stand sensor.
2. **After trip_time** it continues using the weight-stand formula
   *until* ``abs(release - weight_stand) > scope``.  At that point
   (``start_core``) it switches to the release-based formula.
"""
from __future__ import annotations

import numpy as np

from .calculations import DEFAULT_PISTON_OFFSET_M

FT_TO_M = 1.0 / 3.28


def compute_piston_position(
    weight_stand: np.ndarray,
    release: np.ndarray,
    scope_ft: float,
    core_length_ft: float,
    start_core_idx: int,
    offset_constant: float = 1.25,  # default = weight stand length − 0.25 m
) -> np.ndarray:
    """Return the estimated piston position depth (metres).

    Parameters
    ----------
    weight_stand : array-like
        Weight-stand depth in metres (same length as *release*).
    release : array-like
        Release-device depth in metres.
    scope_ft : float
        Scope in feet.
    core_length_ft : float
        Core barrel length in feet.
    start_core_idx : int
        Index where coring starts.  Before this index the formula uses
        the weight-stand depth; from this index onward it uses the
        release depth.
    offset_constant : float
        Fixed vertical offset in metres (default 1.25 m).

    Returns
    -------
    piston : np.ndarray
        Estimated piston depth in metres (same length as inputs).
    """
    ws = np.asarray(weight_stand, dtype=float)
    rel = np.asarray(release, dtype=float)

    scope_m = scope_ft * FT_TO_M
    barrel_m = core_length_ft * FT_TO_M

    piston = np.empty_like(ws)

    # Before start_core: piston = weight_stand + offset + barrel_length
    piston[:start_core_idx] = ws[:start_core_idx] + offset_constant + barrel_m

    # After start_core: piston = release + scope + barrel_length + offset
    piston[start_core_idx:] = (
        rel[start_core_idx:] + scope_m + barrel_m + offset_constant
    )

    return piston


def detect_start_core(
    weight_stand: np.ndarray,
    release: np.ndarray,
    scope_ft: float,
    trip_idx: int = 0,
) -> int:
    """Estimate the initial ``start_core`` index.

    Detection begins at *trip_idx* (the known trip event).  ``start_core``
    is the first sample **at or after** trip_idx where
    ``abs(release - weight_stand) > scope`` (both in metres).

    This mirrors the reference implementation: before the trip the piston
    always tracks the weight stand, and only after the trip do we look for
    the release separation that signals the start of coring.

    Parameters
    ----------
    weight_stand, release : array-like
        Depth series in metres.
    scope_ft : float
        Scope in feet.
    trip_idx : int
        Index of the trip event.  Search begins here.

    Returns
    -------
    int
        Index of the detected start-core point, or ``len(weight_stand) - 1``
        if no crossing is found after trip_idx.
    """
    ws = np.asarray(weight_stand, dtype=float)
    rel = np.asarray(release, dtype=float)
    n = len(ws)
    trip_idx = max(0, min(trip_idx, n - 1))

    diff = np.abs(rel[trip_idx:] - ws[trip_idx:])
    threshold = scope_ft * FT_TO_M
    crossings = np.where(diff > threshold)[0]
    if len(crossings) > 0:
        return trip_idx + int(crossings[0])
    return n - 1
