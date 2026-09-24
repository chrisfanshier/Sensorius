"""
Coring analysis calculations.

Computes various depth-based metrics from weight-stand, release-device,
trigger-core, and piston-position depth profiles around the trip event.

All depths are in **metres**.  Scope and core/trigger-core lengths stored
in CSV metadata are in **feet** and must be converted before being passed
to these functions.

Functions accept plain NumPy arrays and scalar indices so that:
- They are independent of any GUI or SensorData objects.
- Optional Savitzky-Golay smoothing can be applied beforehand.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy import signal as sp_signal


FT_TO_M = 1.0 / 3.28
DEFAULT_WEIGHT_STAND_LENGTH_M = 1.5
DEFAULT_PISTON_OFFSET_M = DEFAULT_WEIGHT_STAND_LENGTH_M - 0.25


def penetration_deficit(
    seafloor_m: float,
    ws_max_depth: float,
    weight_stand_length_m: float,
) -> float:
    """Distance the weight-stand base stopped short of seafloor (metres).

    Positive = barrel stopped short of full penetration; negative = beyond.
    """
    return seafloor_m - (ws_max_depth + weight_stand_length_m)


@dataclass
class CalculationResults:
    """Container for all calculated coring analysis values."""

    # Always computable (need trip_idx)
    recoil_max: Optional[float] = None
    recoil_time_s: Optional[float] = None
    fall_dist: Optional[float] = None

    # Need trip_idx + start_core_idx
    recoil_start: Optional[float] = None
    freefall_start: Optional[float] = None

    # Need trip_idx + 5-second window
    suck_in: Optional[float] = None

    # Needs piston position
    piston_suck: Optional[float] = None

    # Seafloor-dependent (need trigger core sensor)
    seafloor: Optional[float] = None
    piston_alt: Optional[float] = None
    pen_deficit: Optional[float] = None
    freefall_est: Optional[float] = None

    # Trigger line geometry at trip (feet) — needs trip_idx + trigger + weight stand
    eff_trig_line_ft: Optional[float] = None

    # Auxiliary info
    notes: list[str] = field(default_factory=list)


def apply_savgol(
    data: np.ndarray,
    window_length: int = 51,
    polyorder: int = 3,
) -> np.ndarray:
    """Apply Savitzky-Golay smoothing filter.

    Parameters
    ----------
    data : array
        1-D depth array (may contain NaN).
    window_length : int
        Must be odd and > polyorder.
    polyorder : int
        Polynomial order for the filter.

    Returns
    -------
    smoothed : np.ndarray
    """
    arr = np.asarray(data, dtype=float).copy()
    # Interpolate NaNs for filtering
    nans = np.isnan(arr)
    if nans.all():
        return arr
    if nans.any():
        not_nan = ~nans
        arr[nans] = np.interp(
            np.flatnonzero(nans),
            np.flatnonzero(not_nan),
            arr[not_nan],
        )
    # Enforce odd window
    if window_length % 2 == 0:
        window_length += 1
    window_length = max(window_length, polyorder + 2)
    if window_length > len(arr):
        window_length = len(arr) if len(arr) % 2 == 1 else len(arr) - 1
    if window_length <= polyorder:
        return arr
    return sp_signal.savgol_filter(arr, window_length, polyorder)


def _find_idx_at_time_offset(
    timestamps_epoch: np.ndarray,
    ref_idx: int,
    offset_seconds: float,
) -> int:
    """Return the index closest to ``timestamps_epoch[ref_idx] + offset_seconds``."""
    target = timestamps_epoch[ref_idx] + offset_seconds
    return int(np.argmin(np.abs(timestamps_epoch - target)))


def compute_calculations(
    *,
    weight_stand: np.ndarray,
    release: np.ndarray,
    timestamps_epoch: np.ndarray,
    trip_idx: Optional[int] = None,
    start_core_idx: Optional[int] = None,
    piston: Optional[np.ndarray] = None,
    trigger_core: Optional[np.ndarray] = None,
    trigger_core_length_ft: Optional[float] = None,
    trigger_pen: float = 0.0,
    core_length_ft: Optional[float] = None,
    end_pen_idx: Optional[int] = None,
    pullout_idx: Optional[int] = None,
    seafloor_override: Optional[float] = None,
    weight_stand_length_m: float = DEFAULT_WEIGHT_STAND_LENGTH_M,
) -> CalculationResults:
    """Compute coring analysis values.

    Parameters
    ----------
    weight_stand : array
        Weight-stand depth (m).
    release : array
        Release-device depth (m).
    timestamps_epoch : array
        Epoch times aligned with depth arrays.
    trip_idx : int or None
        Index of the trip event.
    start_core_idx : int or None
        Index where coring starts.
    piston : array or None
        Piston-position depth (m), same length as other arrays.
    trigger_core : array or None
        Trigger Core/Weight depth (m).
    trigger_core_length_ft : float or None
        Trigger core barrel length in feet (from header).
    trigger_pen : float
        User-estimated trigger core penetration in metres.
    core_length_ft : float or None
        Core barrel length in feet (from header).
    end_pen_idx : int or None
        User-selected index for end of initial penetration.  When
        ``None``, falls back to trip_idx + 5 seconds.
    pullout_idx : int or None
        User-selected index for pullout (WS starts ascending).
        When ``None``, falls back to global ws_max_idx.

    Returns
    -------
    CalculationResults
    """
    res = CalculationResults()
    n = len(weight_stand)

    # -----------------------------------------------------------------
    # Calculations requiring trip_idx
    # -----------------------------------------------------------------
    if trip_idx is not None and 0 <= trip_idx < n:
        # End-of-penetration index: user-selected or fallback to trip+5s
        if end_pen_idx is not None and 0 <= end_pen_idx < n:
            idx_ep = end_pen_idx
        else:
            idx_ep = _find_idx_at_time_offset(
                timestamps_epoch, trip_idx, 5.0
            )
            idx_ep = min(idx_ep, n - 1)

        # recoil_max:  |release[trip] - min(release[trip : end_pen])|
        window_end = idx_ep + 1
        if window_end > trip_idx:
            recoil_window = release[trip_idx:window_end]
            if np.any(np.isfinite(recoil_window)):
                peak_rel_idx = int(np.nanargmin(recoil_window))
                peak_abs_idx = trip_idx + peak_rel_idx
                min_release_ep = float(recoil_window[peak_rel_idx])
                res.recoil_max = abs(float(release[trip_idx] - min_release_ep))
                dt = float(np.median(np.diff(timestamps_epoch))) if len(timestamps_epoch) > 1 else 0.0
                if dt > 0:
                    res.recoil_time_s = (peak_abs_idx - trip_idx) * dt
            res.notes.append(
                f"recoil_max window: idx {trip_idx}..{idx_ep}"
            )

        # fall_dist: |weight_stand[trip] - weight_stand[end_pen]|
        res.fall_dist = abs(float(weight_stand[trip_idx] - weight_stand[idx_ep]))

        # eff_trig_line_ft: measured trigger line at trip (trigger − WS), in feet
        if trigger_core is not None:
            trig_at_trip = float(trigger_core[trip_idx])
            ws_at_trip = float(weight_stand[trip_idx])
            if np.isfinite(trig_at_trip) and np.isfinite(ws_at_trip):
                res.eff_trig_line_ft = (trig_at_trip - ws_at_trip) / FT_TO_M

        # suck_in: |weight_stand[end_pen] - max(weight_stand)|
        ws_max = np.nanmax(weight_stand)
        res.suck_in = abs(float(weight_stand[idx_ep] - ws_max))

        # -----------------------------------------------------------------
        # Calculations requiring trip_idx AND start_core_idx
        # -----------------------------------------------------------------
        if start_core_idx is not None and 0 <= start_core_idx < n:
            # recoil_start: |release[trip] - release[start_core]|
            res.recoil_start = abs(
                float(release[trip_idx] - release[start_core_idx])
            )

            # freefall_start: |weight_stand[trip] - weight_stand[start_core]|
            res.freefall_start = abs(
                float(weight_stand[trip_idx] - weight_stand[start_core_idx])
            )

        # -----------------------------------------------------------------
        # piston_suck (requires piston, weight_stand, release, start_core)
        # -----------------------------------------------------------------
        if (piston is not None
                and start_core_idx is not None
                and 0 <= start_core_idx < n):
            try:
                # Point A (pullout): user-selected or fallback to
                # ws_max across the whole record.
                if (pullout_idx is not None
                        and 0 <= pullout_idx < n):
                    ws_max_idx = pullout_idx
                else:
                    ws_max_idx = int(np.nanargmax(weight_stand))

                # Point B: first index >= end_pen where release
                #          returns to the depth it was at trip_time.
                #          Search capped at 10 minutes after trip.
                release_at_trip = release[trip_idx]
                search_start = idx_ep
                search_end = _find_idx_at_time_offset(
                    timestamps_epoch, trip_idx, 600.0
                )
                search_end = min(search_end, n - 1)
                diffs = np.abs(release[search_start:search_end] - release_at_trip)
                crossing_candidates = np.where(
                    diffs <= np.nanmin(diffs) + 0.05
                )[0]
                if len(crossing_candidates) > 0:
                    cross_idx = search_start + int(crossing_candidates[0])
                else:
                    cross_idx = None

                if cross_idx is not None and cross_idx <= ws_max_idx:
                    res.piston_suck = float(piston[ws_max_idx] - piston[cross_idx])
                    res.notes.append(
                        f"piston_suck: ws_max_idx={ws_max_idx}, "
                        f"cross_idx={cross_idx}"
                    )
                elif cross_idx is not None and cross_idx > ws_max_idx:
                    res.notes.append(
                        f"piston_suck: N/A (release crossing at {cross_idx} "
                        f"is after pullout at {ws_max_idx})"
                    )
                else:
                    res.notes.append(
                        "piston_suck: could not find release crossing "
                        "after start_core"
                    )
            except Exception as exc:
                res.notes.append(f"piston_suck error: {exc}")

        # -----------------------------------------------------------------
        # Seafloor-dependent calculations
        # -----------------------------------------------------------------
        if seafloor_override is not None:
            sf = float(seafloor_override)
            res.seafloor = sf
            ws_max_depth = float(np.nanmax(weight_stand))
            res.pen_deficit = penetration_deficit(
                sf, ws_max_depth, weight_stand_length_m,
            )
            if (piston is not None
                    and start_core_idx is not None
                    and 0 <= start_core_idx < n):
                res.piston_alt = sf - float(piston[start_core_idx])
            if core_length_ft is not None and core_length_ft > 0:
                core_length_m = core_length_ft * FT_TO_M
                res.freefall_est = abs(
                    float(weight_stand[trip_idx])
                    + weight_stand_length_m
                    + core_length_m
                    - sf
                )
            res.notes.append("Seafloor: manual override")
        elif (trigger_core is not None
                and trigger_core_length_ft is not None
                and trigger_core_length_ft > 0):
            tc_length_m = trigger_core_length_ft * FT_TO_M
            # seafloor = trigger_core[trip] + tc_length_m - trigger_pen
            sf = float(trigger_core[trip_idx]) + tc_length_m - trigger_pen
            res.seafloor = sf

            ws_max_depth = float(np.nanmax(weight_stand))
            res.pen_deficit = penetration_deficit(
                sf, ws_max_depth, weight_stand_length_m,
            )

            # piston_alt = seafloor - piston[start_core]
            if (piston is not None
                    and start_core_idx is not None
                    and 0 <= start_core_idx < n):
                res.piston_alt = sf - float(piston[start_core_idx])

            # freefall_est = |ws[trip] + L_WS + core_length_m - seafloor|
            if core_length_ft is not None and core_length_ft > 0:
                core_length_m = core_length_ft * FT_TO_M
                res.freefall_est = abs(
                    float(weight_stand[trip_idx])
                    + weight_stand_length_m
                    + core_length_m
                    - sf
                )
        else:
            if trigger_core is None:
                res.notes.append(
                    "Seafloor calcs skipped: no Trigger Core/Weight sensor"
                )
            elif trigger_core_length_ft is None or trigger_core_length_ft <= 0:
                res.notes.append(
                    "Seafloor calcs skipped: trigger_core_length not "
                    "available in header metadata"
                )
    else:
        res.notes.append("Trip time not set – most calculations skipped")

    return res


def format_results(res: CalculationResults) -> str:
    """Format calculation results as a human-readable log string."""
    lines = []
    lines.append("=" * 55)
    lines.append("CALCULATION RESULTS")
    lines.append("=" * 55)

    def _fmt(label: str, val: Optional[float], unit: str = "m") -> str:
        if val is None:
            return f"  {label:<25s}  N/A"
        return f"  {label:<25s}  {val:>8.3f} {unit}"

    lines.append("")
    lines.append("--- Basic Metrics ---")
    lines.append(_fmt("Recoil Max:", res.recoil_max))
    lines.append(_fmt("Recoil Time:", res.recoil_time_s, "s"))
    lines.append(_fmt("Fall Distance:", res.fall_dist))
    lines.append(_fmt("Suck-in:", res.suck_in))

    lines.append("")
    lines.append("--- Start-Core Metrics ---")
    lines.append(_fmt("Recoil at Start Core:", res.recoil_start))
    lines.append(_fmt("Freefall at Start Core:", res.freefall_start))

    lines.append("")
    lines.append("--- Piston Metrics ---")
    lines.append(_fmt("Piston Suck:", res.piston_suck))

    lines.append("")
    lines.append("--- Trigger Line ---")
    lines.append(_fmt("Effective Trigger Line:", res.eff_trig_line_ft, "ft"))

    lines.append("")
    lines.append("--- Seafloor Metrics ---")
    if res.seafloor is not None:
        lines.append(f"  {'Seafloor Depth:':<25s}  {res.seafloor:>8.3f} m")
    else:
        lines.append(f"  {'Seafloor Depth:':<25s}  N/A")
    lines.append(_fmt("Piston Altitude:", res.piston_alt))
    lines.append(_fmt("Penetration Deficit:", res.pen_deficit))
    lines.append(_fmt("Freefall Estimate:", res.freefall_est))

    if res.notes:
        lines.append("")
        lines.append("--- Notes ---")
        for note in res.notes:
            lines.append(f"  {note}")

    lines.append("=" * 55)
    return "\n".join(lines)
