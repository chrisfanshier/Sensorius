"""
Recoil calibration IO - load/save recoil prediction calibration JSON files.
"""
from __future__ import annotations

from pathlib import Path

from ..domain.models.recoil_calibration import RecoilCalibration


class RecoilCalibrationIO:
    @staticmethod
    def load(file_path: str | Path) -> RecoilCalibration:
        return RecoilCalibration.load_json(file_path)

    @staticmethod
    def save(calibration: RecoilCalibration, file_path: str | Path) -> None:
        calibration.save_json(file_path)
