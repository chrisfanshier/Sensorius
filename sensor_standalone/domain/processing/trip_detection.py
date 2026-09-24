"""
TripDetectionProcessor - Detect the trip point where sensors diverge.

Uses Savitzky-Golay filtered derivatives and cross-sensor divergence
(standard deviation) to detect the moment of trip.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import signal


@dataclass
class TripDetectionResult:
    """Result of trip detection analysis."""
    trip_index: int
    trip_datetime: object  # pd.Timestamp
    confidence: float
    derivative_order: int
    derivative_label: str
    threshold: float
    derivative_profiles: dict[str, np.ndarray]   # depth_column -> savgol derivative
    divergence: np.ndarray                        # std across sensors
    depth_columns: list[str]                      # depth column names used

    @property
    def summary(self) -> str:
        return (
            f"Trip Time: {self.trip_datetime}\n"
            f"Trip Index: {self.trip_index}\n"
            f"Confidence: {self.confidence:.0%}\n"
            f"Method: {self.derivative_label}"
        )


DERIVATIVE_LABELS = {
    0: "Smoothed Depth",
    1: "Velocity (1st derivative)",
    2: "Acceleration (2nd derivative)",
    3: "Jerk (3rd derivative)",
}


class TripDetectionProcessor:
    """Detects sensor trip point using Savitzky-Golay divergence."""

    @staticmethod
    def detect_trip(
        depths: dict[str, np.ndarray],
        timestamps,
        *,
        sg_window: int = 51,
        sg_poly: int = 3,
        derivative_order: int = 1,
        std_threshold: float = 0.5,
        sampling_rate: float = 32.0,
        edge_buffer: int = 500,
    ) -> TripDetectionResult:
        """
        Detect the trip point where sensor derivatives diverge.

        Args:
            depths: Dict mapping depth_column_name -> depth array.
            timestamps: Datetime series aligned with depth arrays.
            sg_window: Savitzky-Golay window length (must be odd).
            sg_poly: Savitzky-Golay polynomial order.
            derivative_order: 0=depth, 1=velocity, 2=acceleration, 3=jerk.
            std_threshold: Divergence threshold for trip detection.
            sampling_rate: Data sampling rate in Hz.
            edge_buffer: Samples to exclude from edges.

        Returns:
            TripDetectionResult with trip index, profiles, and divergence.
        """
        dt = 1.0 / sampling_rate
        columns = list(depths.keys())
        depth_arrays = np.array([depths[col] for col in columns])

        d_depths = np.array([
            signal.savgol_filter(
                d,
                window_length=sg_window,
                polyorder=sg_poly,
                deriv=derivative_order,
                delta=dt,
            )
            for d in depth_arrays
        ])

        profiles = {col: d_depths[i] for i, col in enumerate(columns)}

        divergence = np.std(d_depths, axis=0)

        div_masked = divergence.copy()
        div_masked[:edge_buffer] = 0
        div_masked[-edge_buffer:] = 0

        above = np.where(div_masked > std_threshold)[0]
        if len(above) > 0:
            trip_idx = int(above[0])
            confidence = 0.8
        else:
            trip_idx = int(np.argmax(div_masked))
            confidence = 0.5

        deriv_label = DERIVATIVE_LABELS.get(derivative_order, f"Derivative order {derivative_order}")

        return TripDetectionResult(
            trip_index=trip_idx,
            trip_datetime=timestamps.iloc[trip_idx] if hasattr(timestamps, 'iloc') else timestamps[trip_idx],
            confidence=confidence,
            derivative_order=derivative_order,
            derivative_label=deriv_label,
            threshold=std_threshold,
            derivative_profiles=profiles,
            divergence=divergence,
            depth_columns=columns,
        )
