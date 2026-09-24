"""
DepthCalibration - Domain model for depth-dependent calibration data.

Stores the regression parameters (slope, intercept, R², etc.) generated
from multi-cast calibration workflows.  Used by depth_correction processing
to compute offsets at arbitrary depths.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Optional


@dataclass
class RegressionEntry:
    """One linear regression between two sensor labels."""
    sensor_i: str          # e.g. 'A'
    sensor_j: str          # e.g. 'B'
    slope: float
    intercept: float
    r_squared: float
    p_value: float = 0.0

    def predict_offset(self, depth: float) -> float:
        """Return the predicted offset (j - i) at a given depth."""
        return self.slope * depth + self.intercept

    def to_dict(self) -> dict:
        return {
            'sensor_i': self.sensor_i,
            'sensor_j': self.sensor_j,
            'slope': self.slope,
            'intercept': self.intercept,
            'r_squared': self.r_squared,
            'p_value': self.p_value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'RegressionEntry':
        return cls(
            sensor_i=d['sensor_i'],
            sensor_j=d['sensor_j'],
            slope=d['slope'],
            intercept=d['intercept'],
            r_squared=d['r_squared'],
            p_value=d.get('p_value', 0.0),
        )


@dataclass
class DepthCalibration:
    """
    A collection of linear regressions describing depth-dependent
    offsets between sensor pairs.
    """
    num_sensors: int
    sensor_labels: list[str]
    regressions: list[RegressionEntry] = field(default_factory=list)

    def find_regression(self, sensor_i: str, sensor_j: str) -> Optional[RegressionEntry]:
        """Find regression for a specific sensor pair (order-sensitive)."""
        for reg in self.regressions:
            if reg.sensor_i == sensor_i and reg.sensor_j == sensor_j:
                return reg
        return None

    def find_regressions_involving(self, label: str) -> list[RegressionEntry]:
        """Find all regressions involving a given sensor label."""
        return [r for r in self.regressions
                if r.sensor_i == label or r.sensor_j == label]

    def get_applicable_corrections(self, ref_sensor: str) -> list[dict]:
        """
        Given a reference sensor, return the corrections that should be applied
        to the other sensors.
        
        Returns a list of dicts: {target, regression, sign, reg}
        where sign indicates whether to add (+1) or subtract (-1) the offset.
        """
        applicable = []
        for reg in self.regressions:
            if reg.sensor_i == ref_sensor:
                # Regression is (j - ref), correct j by subtracting
                applicable.append({
                    'target': reg.sensor_j,
                    'regression': f"{reg.sensor_j} - {reg.sensor_i}",
                    'sign': -1,
                    'reg': reg,
                })
            elif reg.sensor_j == ref_sensor:
                # Regression is (ref - i), correct i by adding
                applicable.append({
                    'target': reg.sensor_i,
                    'regression': f"{reg.sensor_j} - {reg.sensor_i}",
                    'sign': 1,
                    'reg': reg,
                })
        return applicable

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            'num_sensors': self.num_sensors,
            'sensor_labels': self.sensor_labels,
            'regressions': [r.to_dict() for r in self.regressions],
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'DepthCalibration':
        return cls(
            num_sensors=d['num_sensors'],
            sensor_labels=d['sensor_labels'],
            regressions=[RegressionEntry.from_dict(r) for r in d.get('regressions', [])],
        )

    def save_json(self, path: str | Path):
        """Save calibration to a JSON file."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load_json(cls, path: str | Path) -> 'DepthCalibration':
        """Load calibration from a JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)
        return cls.from_dict(data)
