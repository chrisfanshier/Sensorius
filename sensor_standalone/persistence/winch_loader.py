"""Project-backed winch loading (ported from sensor_tool winch_loader)."""
from __future__ import annotations

import json
import os
from typing import Optional

import pandas as pd

from . import file_parsers as fp
from .project import ProjectStore

_EXCLUDE_PARAM_COLS = frozenset({
    "index", "datetime", "date", "time",
    "year", "month", "day", "hour", "minute", "second",
})


def _strip_tz(dt_val) -> pd.Timestamp:
    dt = pd.to_datetime(dt_val, errors="coerce")
    if dt is not pd.NaT and hasattr(dt, "tz") and dt.tz is not None:
        return dt.tz_localize(None)
    return dt


def _parsing_settings_from_row(settings_raw, file_name: str) -> dict:
    try:
        settings = json.loads(settings_raw) if settings_raw else {}
    except (json.JSONDecodeError, TypeError):
        settings = {}

    if settings:
        parsing = {
            "delimiter": settings.get("delimiter", ","),
            "header_lines": settings.get("header_lines", 0),
            "columns": settings.get("columns", []),
            "datetime_code": settings.get(
                "datetime_code", "pd.to_datetime(df['datetime'])"
            ),
        }
        if "numeric_columns" in settings:
            parsing["numeric_columns"] = settings["numeric_columns"]
        return parsing

    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext == ".dat":
        return {
            "delimiter": r"\s+",
            "header_lines": 0,
            "datetime_code": (
                "pd.to_datetime(df[['year', 'month', 'day', "
                "'hour', 'minute', 'second']])"
            ),
        }
    return {
        "delimiter": ",",
        "header_lines": 0,
        "datetime_code": "pd.to_datetime(df['datetime'])",
    }


def get_winch_parameters(df: Optional[pd.DataFrame]) -> list[str]:
    if df is None or df.empty:
        return []
    numeric_cols = [
        col for col in df.select_dtypes(include="number").columns
        if col.lower() not in _EXCLUDE_PARAM_COLS
    ]
    return sorted(numeric_cols)


def datetime_to_epoch(df: pd.DataFrame) -> pd.Series:
    s = pd.to_datetime(df["datetime"], utc=False)
    if getattr(s.dt, "tz", None) is not None:
        s = s.dt.tz_convert("UTC").dt.tz_localize(None)
    vals = s.values.astype("datetime64[ns]")
    return pd.Series(vals.view("int64") / 1e9, index=df.index)


def timestamp_to_epoch(dt) -> float:
    ts = pd.Timestamp(dt)
    if ts.tz is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return float(ts.value / 1e9)


class WinchLoader:
    """Load winch telemetry from a project store."""

    def __init__(self, store: ProjectStore):
        self.store = store

    def _parse_winch_row(self, rel_path: str, file_name: str, settings_raw) -> Optional[pd.DataFrame]:
        full_path = self.store.full_path(rel_path, file_name)
        parsing_settings = _parsing_settings_from_row(settings_raw, file_name)
        try:
            df = fp.parse_winch_dat(full_path, parsing_settings)
            if df is not None and "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"]).dt.tz_localize(None)
                return df
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ Could not load winch file {file_name}: {exc}")
        return None

    def fetch_winch_files_for_cruise(self, cruise_id: int) -> list[dict]:
        rows = self.store.fetch_winch_files(cruise_id)
        return [
            {
                "winch_file_id": r["winch_file_id"],
                "file_name": r["file_name"],
                "file_path": r["rel_path"],
                "start_time": _strip_tz(r["start_time"]),
                "end_time": _strip_tz(r["end_time"]),
                "settings": r["settings"],
            }
            for r in rows
        ]

    def load_winch_file(self, winch_file_id: int) -> tuple[Optional[pd.DataFrame], str]:
        rows = [r for r in self._all_winch_rows() if r["winch_file_id"] == winch_file_id]
        if not rows:
            return None, ""
        row = rows[0]
        df = self._parse_winch_row(row["rel_path"], row["file_name"], row["settings"])
        return df, row["file_name"]

    def _all_winch_rows(self) -> list[dict]:
        out = []
        for cruise in self.store.fetch_cruises():
            out.extend(self.store.fetch_winch_files(cruise["cruise_id"]))
        return out

    def load_winch_files_concat(
        self, winch_file_ids: list[int],
    ) -> tuple[Optional[pd.DataFrame], list[str]]:
        if not winch_file_ids:
            return None, []

        dfs: list[pd.DataFrame] = []
        names: list[str] = []
        for wid in winch_file_ids:
            df, name = self.load_winch_file(wid)
            if df is not None and not df.empty:
                dfs.append(df)
                names.append(name)

        if not dfs:
            return None, names

        combined = (
            pd.concat(dfs, ignore_index=True)
            .sort_values("datetime")
            .reset_index(drop=True)
        )
        return combined, names

    def load_core_winch_data(
        self, core_id: int, cruise_id: int,
    ) -> tuple[Optional[pd.DataFrame], list[str], list[int]]:
        core = self.store.get_core(core_id)
        winch_files = self.store.fetch_winch_files(cruise_id)

        if core is None or not winch_files:
            return None, [], []

        window = self._core_deployment_window(core)
        if window is None:
            return None, [], []

        core_start, core_end = window
        winch_dfs: list[pd.DataFrame] = []
        file_names: list[str] = []
        file_ids: list[int] = []

        for wrow in winch_files:
            start_t = _strip_tz(wrow["start_time"])
            end_t = _strip_tz(wrow["end_time"])
            if start_t is pd.NaT or end_t is pd.NaT:
                continue
            if start_t > core_end or end_t < core_start:
                continue

            df = self._parse_winch_row(wrow["rel_path"], wrow["file_name"], wrow["settings"])
            if df is not None:
                winch_dfs.append(df)
                file_names.append(wrow["file_name"])
                file_ids.append(int(wrow["winch_file_id"]))

        if not winch_dfs:
            return None, file_names, file_ids

        all_winch = (
            pd.concat(winch_dfs, ignore_index=True)
            .sort_values("datetime")
            .reset_index(drop=True)
        )
        trim_mask = (
            (all_winch["datetime"] >= core_start)
            & (all_winch["datetime"] <= core_end)
        )
        trimmed = all_winch[trim_mask].copy().reset_index(drop=True)
        if trimmed.empty:
            return None, file_names, file_ids
        return trimmed, file_names, file_ids

    @staticmethod
    def _core_deployment_window(core: dict) -> Optional[tuple[pd.Timestamp, pd.Timestamp]]:
        start = core.get("start_datetime")
        end = core.get("end_datetime")
        if not start or not end:
            return None
        core_start = pd.to_datetime(start, errors="coerce")
        core_end = pd.to_datetime(end, errors="coerce")
        if pd.isna(core_start) or pd.isna(core_end):
            return None
        if core_end < core_start:
            core_end += pd.Timedelta(days=1)
        return core_start, core_end
