"""
WinchTripDetection — detect trip from a rapid drop in a winch telemetry series.

Uses adjacent-sample finite differences within a user-defined time search
window and edge buffers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class WinchTripResult:
    """Result of winch trip detection on a single column."""
    trip_index: int
    trip_datetime: object  # pd.Timestamp
    drop_magnitude: float
    column: str

    @property
    def summary(self) -> str:
        return (
            f"Winch trip at index {self.trip_index}: {self.trip_datetime}\n"
            f"Drop magnitude: {self.drop_magnitude:.1f}"
        )


class WinchTripDetectionProcessor:
    """Detect winch trip from the first large negative step in a series."""

    @staticmethod
    def detect_trip(
        values: np.ndarray,
        timestamps: pd.Series,
        column: str,
        *,
        edge_buffer: int = 500,
        drop_threshold: float = 1000.0,
        search_start: Optional[pd.Timestamp] = None,
        search_end: Optional[pd.Timestamp] = None,
    ) -> Optional[WinchTripResult]:
        """
        Find the first index where the prior sample minus current sample
        exceeds *drop_threshold*.

        Parameters
        ----------
        values
            Winch parameter values (e.g. tension).
        timestamps
            Datetime series aligned with *values*.
        column
            Column name (for the result object).
        edge_buffer
            Samples excluded from each end of the series.
        drop_threshold
            Minimum drop ``values[i - 1] - values[i]`` to qualify.
        search_start, search_end
            Optional datetime window restricting the search.

        Returns
        -------
        WinchTripResult or None if no qualifying drop is found.
        """
        n = len(values)
        if n < 2:
            return None

        edge_buffer = max(0, int(edge_buffer))
        lo = edge_buffer
        hi = n - edge_buffer - 1
        if lo >= hi:
            return None

        ts = pd.to_datetime(timestamps)

        for i in range(max(lo, 1), hi + 1):
            t_i = ts.iloc[i]
            if search_start is not None and t_i < search_start:
                continue
            if search_end is not None and t_i > search_end:
                continue

            v_prev = values[i - 1]
            v_curr = values[i]
            if not np.isfinite(v_prev) or not np.isfinite(v_curr):
                continue

            drop = float(v_prev - v_curr)
            if drop >= drop_threshold:
                return WinchTripResult(
                    trip_index=i,
                    trip_datetime=ts.iloc[i],
                    drop_magnitude=drop,
                    column=column,
                )

        return None
