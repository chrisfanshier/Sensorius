"""Load sensor files from a project folder into SensorData."""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from ..domain.models.sensor_data import SensorData
from . import file_parsers as fp
from .project import ProjectStore

_INCLUDE_KEYWORDS = {"depth", "pressure", "acceleration", "g", "tilt"}


def _should_include(col: str) -> bool:
    low = col.lower()
    return any(kw in low for kw in _INCLUDE_KEYWORDS)


class ProjectDataLoader:
    """Project-backed replacement for sensor_tool DatabaseLoader."""

    def __init__(self, store: ProjectStore):
        self.store = store

    @staticmethod
    def fetch_cruises(store: ProjectStore) -> list[dict]:
        cruises = store.fetch_cruises()
        return [
            {
                "cruise_id": c["cruise_id"],
                "cruise_name": c["cruise_name"],
                "vessel_name": c.get("vessel_name") or "",
            }
            for c in cruises
        ]

    @staticmethod
    def fetch_cores_for_cruise(store: ProjectStore, cruise_id: int) -> list[dict]:
        return store.fetch_cores_with_sensor_files(cruise_id)

    @staticmethod
    def fetch_cores_for_cruise_all_types(store: ProjectStore, cruise_id: int) -> list[dict]:
        return store.fetch_cores_with_sensor_files(cruise_id)

    def load_core_sensor_data(self, core_id: int, core_info: dict) -> SensorData:
        sensor_files = self.store.fetch_sensor_files(core_id)
        if not sensor_files:
            raise ValueError(
                f"No sensor files found for core {core_info.get('core_name', core_id)}"
            )

        export_frames: list[pd.DataFrame] = []
        for sf in sensor_files:
            full = self.store.full_path(sf["rel_path"], sf["file_name"])
            df = fp.parse_sensor_file(full, sf.get("sensor_type") or "")
            if df is None:
                continue

            cols = [c for c in df.columns if c != "datetime" and _should_include(c)]
            if not cols:
                continue

            loc = sf.get("sensor_location") or ""
            fname = sf.get("file_name") or ""
            prefix = f"{loc}_{fname}" if loc else fname

            for col in cols:
                if col in df.columns and not df[col].isna().all():
                    series_df = df[["datetime", col]].copy()
                    series_df.rename(columns={col: f"{prefix}_{col}"}, inplace=True)
                    export_frames.append(series_df)

        if not export_frames:
            raise ValueError(
                f"No usable sensor data for core {core_info.get('core_name', core_id)}"
            )

        merged = export_frames[0]
        for nxt in export_frames[1:]:
            merged = pd.merge(merged, nxt, on="datetime", how="outer")
        merged.sort_values("datetime", inplace=True)
        merged.reset_index(drop=True, inplace=True)
        merged["datetime"] = merged["datetime"].astype("datetime64[ns]")

        metadata: dict = {}
        if core_info.get("core_type_name") or core_info.get("core_type"):
            metadata["core_type"] = core_info.get("core_type_name") or core_info.get("core_type")

        for key in (
            "core_length", "trigger_core_length", "trigger_line_length", "scope",
        ):
            val = core_info.get(key)
            if val is not None:
                try:
                    metadata[key] = float(val)
                except (TypeError, ValueError):
                    pass

        depth_cols = [c for c in merged.columns if "Depth" in c]
        if not depth_cols:
            raise ValueError(
                "No Depth columns found in merged sensor data for core "
                f"{core_info.get('core_name', core_id)}"
            )

        return SensorData(
            df=merged,
            datetime_col="datetime",
            depth_columns=depth_cols,
            source_file=f"Project:{core_info.get('core_name', str(core_id))}",
            core_title=core_info.get("core_name", ""),
            metadata=metadata,
        )
