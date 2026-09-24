"""
Calibration IO - load/save DepthCalibration JSON files.
"""
from __future__ import annotations

from pathlib import Path

from ..domain.models.calibration import DepthCalibration


class CalibrationIO:
    """Thin wrapper around DepthCalibration serialization."""

    @staticmethod
    def load(file_path: str | Path) -> DepthCalibration:
        """Load a DepthCalibration from a JSON file."""
        return DepthCalibration.load_json(file_path)

    @staticmethod
    def save(calibration: DepthCalibration, file_path: str | Path):
        """Save a DepthCalibration to a JSON file."""
        calibration.save_json(file_path)
