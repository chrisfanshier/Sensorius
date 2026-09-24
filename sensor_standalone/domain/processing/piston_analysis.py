"""
Piston Analysis processing.

Computes per-sample piston behaviour from start_core (first moment of
core opening / freefall) through pullout.

X-axis is *core depth* — the distance the weight-stand has descended
relative to its position at the start-of-penetration moment (start_pen):

    core_depth[i] = weight_stand[i] - weight_stand[start_pen_idx]

for i in [start_core_idx, pullout_idx].

Samples before start_pen have negative core_depth (weight stand above
the sediment entry point); samples at and after start_pen are >= 0.
Zero marks the instant of first sediment penetration.

The Savitzky-Golay derivative is used to estimate velocity (m/s).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.signal import savgol_filter


@dataclass
class PistonAnalysisResult:
    """Results from a single piston analysis run."""

    # Core depth axis (m), length = pullout_idx - start_core_idx + 1.
    # Zero is at start_pen; samples before start_pen are negative.
    core_depth: np.ndarray

    # Absolute piston depth trace over the penetration phase (m)
    piston_depth: np.ndarray

    # Absolute weight-stand depth trace over the penetration phase (m)
    ws_depth: np.ndarray

    # Weight-stand velocity (m/s), same length
    ws_velocity: np.ndarray

    # Piston velocity (m/s), same length
    piston_velocity: np.ndarray

    # Seafloor depth if available (m), otherwise None
    seafloor: Optional[float]

    # SG parameters used
    sg_window: int
    sg_polyorder: int

    # x-coordinate of the start-penetration event (0.0 by construction —
    # core_depth is referenced to start_pen, so the marker is always at zero)
    start_pen_core_depth_m: float = 0.0


class PistonAnalysisProcessor:
    """Static methods for piston analysis computation."""

    @staticmethod
    def _sg_velocity(
        values: np.ndarray,
        timestamps_epoch: np.ndarray,
        window: int,
        polyorder: int,
    ) -> np.ndarray:
        """Compute velocity via Savitzky-Golay derivative.

        Uses the *deriv=1* option of savgol_filter with the median
        sample interval as *delta* so the result is in m/s.

        Parameters
        ----------
        values : (N,) float array
            Depth values in metres.
        timestamps_epoch : (N,) float array
            Unix timestamps (seconds).
        window : int
            SG window length (will be forced odd and >= polyorder+2).
        polyorder : int
            SG polynomial order.

        Returns
        -------
        velocity : (N,) float array in m/s.
        """
        arr = np.asarray(values, dtype=float).copy()
        n = len(arr)

        # Interpolate NaNs
        nans = np.isnan(arr)
        if nans.any() and not nans.all():
            not_nan = ~nans
            arr[nans] = np.interp(
                np.flatnonzero(nans),
                np.flatnonzero(not_nan),
                arr[not_nan],
            )

        # Median sample interval as delta
        dt = float(np.median(np.diff(timestamps_epoch)))
        if dt <= 0:
            dt = 1.0

        # Enforce constraints
        w = int(window)
        if w % 2 == 0:
            w += 1
        w = max(w, polyorder + 2)
        if w > n:
            w = n if n % 2 == 1 else max(n - 1, 3)
        if w <= polyorder or n < w:
            return np.zeros(n, dtype=float)

        return savgol_filter(arr, w, polyorder, deriv=1, delta=dt)

    @staticmethod
    def compute_analysis(
        ws_vals: np.ndarray,
        piston_vals: np.ndarray,
        timestamps_epoch: np.ndarray,
        start_pen_idx: int,
        pullout_idx: int,
        start_core_idx: Optional[int] = None,
        sg_window: int = 51,
        sg_polyorder: int = 3,
        seafloor: Optional[float] = None,
    ) -> PistonAnalysisResult:
        """Compute piston analysis over the core-opening interval.

        Parameters
        ----------
        ws_vals : (N,) array
            Full weight-stand depth series in metres.
        piston_vals : (N,) array
            Full piston depth series in metres.
        timestamps_epoch : (N,) array
            Unix timestamps corresponding to ws/piston.
        start_pen_idx : int
            Index of the start-of-penetration event.  Defines x = 0 on
            the core-depth axis; samples before this point have x < 0.
        pullout_idx : int
            Index of pullout event (inclusive upper bound).
        start_core_idx : int or None
            Index at which to begin the analysis window (start of core
            opening).  When None, defaults to ``start_pen_idx``
            (backward-compatible behaviour — no pre-penetration samples).
        sg_window : int
            Savitzky-Golay window length.
        sg_polyorder : int
            Savitzky-Golay polynomial order.
        seafloor : float or None
            Seafloor depth in metres.

        Returns
        -------
        PistonAnalysisResult
        """
        # Analysis window: start_core (or start_pen as fallback) through pullout
        lo = int(start_core_idx) if start_core_idx is not None else int(start_pen_idx)
        hi = int(pullout_idx) + 1  # inclusive

        ws_seg = np.asarray(ws_vals, dtype=float)[lo:hi]
        piston_seg = np.asarray(piston_vals, dtype=float)[lo:hi]
        ts_seg = np.asarray(timestamps_epoch, dtype=float)[lo:hi]

        # Core depth axis: distance WS has descended since start_pen.
        # Samples before start_pen have negative core_depth.
        pen_offset = int(start_pen_idx) - lo
        ws_at_start_pen = float(ws_seg[pen_offset])
        core_depth = ws_seg - ws_at_start_pen

        # Velocities
        ws_vel = PistonAnalysisProcessor._sg_velocity(
            ws_seg, ts_seg, sg_window, sg_polyorder
        )
        piston_vel = PistonAnalysisProcessor._sg_velocity(
            piston_seg, ts_seg, sg_window, sg_polyorder
        )

        return PistonAnalysisResult(
            core_depth=core_depth,
            piston_depth=piston_seg,
            ws_depth=ws_seg,
            ws_velocity=ws_vel,
            piston_velocity=piston_vel,
            seafloor=seafloor,
            sg_window=sg_window,
            sg_polyorder=sg_polyorder,
            start_pen_core_depth_m=0.0,
        )
