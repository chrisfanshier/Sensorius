"""Build time-relative actual sensor traces for Predict-mode overlay."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .calculations import FT_TO_M


@dataclass
class ActualOverlay:
    """Actual depth traces aligned to trip time for overlay on model bands."""

    time: np.ndarray
    corer_rel: np.ndarray
    release_rel: np.ndarray
    trigger_rel: Optional[np.ndarray]
    piston_rel: Optional[np.ndarray]
    trip_index: int
    effective_trigger_line_ft: Optional[float]
    planned_trigger_line_ft: Optional[float]


def effective_trigger_line_ft(
    weight_stand: np.ndarray,
    trigger_core: np.ndarray,
    trip_idx: int,
) -> Optional[float]:
    """Measured trigger line at trip in feet, or None if not computable."""
    if trip_idx < 0 or trip_idx >= len(weight_stand):
        return None
    ws = float(weight_stand[trip_idx])
    trig = float(trigger_core[trip_idx])
    if not (np.isfinite(ws) and np.isfinite(trig)):
        return None
    return (trig - ws) / FT_TO_M


def _resample_to_grid(
    t_actual: np.ndarray,
    y_actual: np.ndarray,
    t_grid: np.ndarray,
) -> np.ndarray:
    out = np.full_like(t_grid, np.nan, dtype=float)
    valid = np.isfinite(t_actual) & np.isfinite(y_actual)
    if valid.sum() < 2:
        return out
    t_v = t_actual[valid]
    y_v = y_actual[valid]
    order = np.argsort(t_v)
    t_v = t_v[order]
    y_v = y_v[order]
    in_range = (t_grid >= t_v[0]) & (t_grid <= t_v[-1])
    if not np.any(in_range):
        return out
    out[in_range] = np.interp(t_grid[in_range], t_v, y_v)
    return out


def build_actual_overlay(
    *,
    weight_stand: np.ndarray,
    release: np.ndarray,
    timestamps_epoch: np.ndarray,
    trip_idx: int,
    time_grid: np.ndarray,
    release_above_corer_m: float,
    piston: Optional[np.ndarray] = None,
    trigger_core: Optional[np.ndarray] = None,
    planned_trigger_line_ft: Optional[float] = None,
) -> ActualOverlay:
    """
    Convert corrected sensor depths to trip-relative time and model-relative depth.

    Depth reference matches ``run_prediction``:
    - corer (weight stand): 0 at trip
    - release: ``-release_above_corer_m`` at trip
    - piston: same corer reference when available
    """
    n = len(weight_stand)
    if trip_idx < 0 or trip_idx >= n:
        raise ValueError(f"trip_idx {trip_idx} out of range for {n} samples")

    t_rel = timestamps_epoch - float(timestamps_epoch[trip_idx])
    ws_trip = float(weight_stand[trip_idx])
    rel_trip = float(release[trip_idx])

    corer_rel = weight_stand - ws_trip
    release_rel = (release - rel_trip) - release_above_corer_m
    trigger_rel = None
    if trigger_core is not None and len(trigger_core) == n:
        trigger_rel = trigger_core - ws_trip
    piston_rel = None
    if piston is not None and len(piston) == n:
        piston_rel = piston - ws_trip

    eff_ft = None
    if trigger_core is not None and len(trigger_core) == n:
        eff_ft = effective_trigger_line_ft(weight_stand, trigger_core, trip_idx)

    return ActualOverlay(
        time=time_grid.copy(),
        corer_rel=_resample_to_grid(t_rel, corer_rel, time_grid),
        release_rel=_resample_to_grid(t_rel, release_rel, time_grid),
        trigger_rel=(
            _resample_to_grid(t_rel, trigger_rel, time_grid)
            if trigger_rel is not None else None
        ),
        piston_rel=(
            _resample_to_grid(t_rel, piston_rel, time_grid)
            if piston_rel is not None else None
        ),
        trip_index=trip_idx,
        effective_trigger_line_ft=eff_ft,
        planned_trigger_line_ft=planned_trigger_line_ft,
    )
