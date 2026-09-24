"""
Analysis result domain models.

Pure data containers for results computed by processing modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StatisticsResult:
    """Result of computing statistics on a selected range of sensor data."""
    range_description: str
    n_points: int
    mean_depth_all_sensors: float
    column_means: dict[str, float] = field(default_factory=dict)
    difference_means: dict[tuple[str, str], float] = field(default_factory=dict)
    source_file: str = ''

    def to_flat_dict(self) -> dict:
        """Convert to a flat dict for table display / DataFrame row."""
        d = {
            'range': self.range_description,
            'n_points': self.n_points,
        }
        # Differences
        for (j, i), val in self.difference_means.items():
            d[f'{j}_minus_{i}_mean'] = val
        d['mean_depth_all_sensors'] = self.mean_depth_all_sensors
        # Column means
        for col, val in self.column_means.items():
            d[f'{col}_mean'] = val
        d['source_file'] = self.source_file
        return d


@dataclass
class TimeOffsetResult:
    """Result of time offset calculation for one sensor."""
    sensor_column: str
    offset_seconds: float
    rms_value: float = 0.0
    is_reference: bool = False

    def __repr__(self) -> str:
        if self.is_reference:
            return f"TimeOffset({self.sensor_column}: reference)"
        return f"TimeOffset({self.sensor_column}: {self.offset_seconds:+.3f}s, RMS={self.rms_value:.6f})"
