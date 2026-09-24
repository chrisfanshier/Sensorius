"""
RecoilCalibration - population regression artifact for forward recoil prediction.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class RecoilCalibration:
    """Wrapper around the calibration dict produced by regenerate_recoil_calibration.py."""

    calibration: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def body(self) -> dict[str, Any]:
        """Inner calibration dict consumed by predict_recoil_parameters."""
        return self.calibration

    def to_dict(self) -> dict:
        return {
            "calibration": self.calibration,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RecoilCalibration:
        if "calibration" in data:
            return cls(
                calibration=data["calibration"],
                metadata=data.get("metadata") or {},
            )
        return cls(calibration=data, metadata={})

    def save_json(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load_json(cls, path: str | Path) -> RecoilCalibration:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def summary_lines(self) -> list[str]:
        meta = self.metadata or {}
        lines = []
        if meta.get("generated_at"):
            lines.append(f"Generated: {meta['generated_at']}")
        if meta.get("source_row_count_working") is not None:
            lines.append(
                f"Working rows: {meta['source_row_count_working']} "
                f"(raw {meta.get('source_row_count_raw', '?')})"
            )
        cal = self.calibration
        if cal.get("row_count_working") is not None:
            lines.append(f"Calibration rows: {cal['row_count_working']}")
        if cal.get("low_quality_cores"):
            lines.append(f"Excluded cores: {cal['low_quality_cores']}")
        return lines or ["Calibration loaded."]
