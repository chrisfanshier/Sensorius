"""
SensorData - Core domain model wrapping a DataFrame with sensor metadata.

This is the single source of truth for all sensor data in the application.
It tracks which corrections have been applied and provides access to the
underlying data in a controlled manner.

Depth columns keep their **original names** from the source CSV throughout
the entire application - no renaming to Sensor_A/B/C/D ever occurs.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CorrectionRecord:
    """Record of a correction applied to the data."""
    correction_type: str          # 'depth_calibration', 'depth_manual', 'time_shift'
    sensor_column: str            # Which depth column was modified
    description: str              # Human-readable description
    parameters: dict = field(default_factory=dict)


class SensorData:
    """
    Wraps a pandas DataFrame containing sensor depth measurements.

    The DataFrame is expected to have:
      - A datetime column (default name: 'datetime')
      - One or more depth columns (original names from CSV)

    Depth columns retain their original CSV column names throughout.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        datetime_col: str = 'datetime',
        depth_columns: Optional[list[str]] = None,
        source_file: str = '',
        core_title: str = '',
        metadata: Optional[dict] = None,
    ):
        self._df = df.copy()
        self.datetime_col = datetime_col
        self.source_file = source_file
        self.core_title = core_title
        self.corrections: list[CorrectionRecord] = []
        self.metadata: dict = dict(metadata or {})

        if depth_columns is not None:
            self.depth_columns = list(depth_columns)
        else:
            self.depth_columns = self._detect_depth_columns()

        if self.datetime_col in self._df.columns:
            if not pd.api.types.is_datetime64_any_dtype(self._df[self.datetime_col]):
                self._df[self.datetime_col] = pd.to_datetime(
                    self._df[self.datetime_col], errors='coerce'
                )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def df(self) -> pd.DataFrame:
        return self._df

    @property
    def num_sensors(self) -> int:
        return len(self.depth_columns)

    @property
    def row_count(self) -> int:
        return len(self._df)

    @property
    def time_range(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        if self.datetime_col not in self._df.columns or self._df.empty:
            return None
        return (self._df[self.datetime_col].min(), self._df[self.datetime_col].max())

    @property
    def depth_range(self) -> tuple[float, float] | None:
        cols = [c for c in self.depth_columns if c in self._df.columns]
        if not cols or self._df.empty:
            return None
        min_val = self._df[cols].min().min()
        max_val = self._df[cols].max().max()
        return (float(min_val), float(max_val))

    # ------------------------------------------------------------------
    # Display-name helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_short_name(col: str) -> str:
        """Short display name, e.g. 'Weight Stand (230406)'."""
        parts = col.split('_')
        location = parts[0]
        if len(parts) > 1:
            serial = parts[1].removesuffix('.rsk')
            return f"{location} ({serial})"
        return location

    @staticmethod
    def get_full_label(col: str) -> str:
        """Full label showing filename and location, e.g. '230405.rsk (Weight Stand)'."""
        parts = col.split('_')
        location = parts[0] if parts else col
        filename = parts[1] if len(parts) > 1 else ''
        if filename:
            return f"{filename} ({location})"
        return location

    @staticmethod
    def get_location_name(col: str) -> str:
        """Just the location part, e.g. 'Weight Stand'."""
        return col.split('_')[0]

    def find_column_by_location(self, keyword: str) -> Optional[str]:
        """Find a depth column whose location contains *keyword* (case-insensitive)."""
        kw = keyword.lower()
        for col in self.depth_columns:
            loc = self.get_location_name(col).lower()
            if kw in loc:
                return col
        return None

    # ------------------------------------------------------------------
    # Data access helpers
    # ------------------------------------------------------------------

    def get_depth_series(self, col: str) -> pd.Series:
        if col not in self._df.columns:
            raise KeyError(f"No depth column found: {col}")
        return self._df[col]

    def get_timestamps(self) -> pd.Series:
        return self._df[self.datetime_col]

    def get_timestamps_epoch(self) -> np.ndarray:
        vals = self._df[self.datetime_col].values.astype('datetime64[ns]')
        return vals.view('int64') / 1e9

    def slice_by_index(self, start: int, end: int) -> 'SensorData':
        sliced_df = self._df.iloc[start:end + 1].copy().reset_index(drop=True)
        new_data = SensorData(
            df=sliced_df,
            datetime_col=self.datetime_col,
            depth_columns=list(self.depth_columns),
            source_file=self.source_file,
            core_title=self.core_title,
            metadata=dict(self.metadata),
        )
        new_data.corrections = list(self.corrections)
        return new_data

    def copy(self) -> 'SensorData':
        new_data = SensorData(
            df=self._df.copy(),
            datetime_col=self.datetime_col,
            depth_columns=list(self.depth_columns),
            source_file=self.source_file,
            core_title=self.core_title,
            metadata=dict(self.metadata),
        )
        new_data.corrections = list(self.corrections)
        return new_data

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def update_depth_column(self, col: str, values: np.ndarray | pd.Series):
        self._df[col] = values

    def update_dataframe(self, df: pd.DataFrame):
        self._df = df

    def add_correction(self, record: CorrectionRecord):
        self.corrections.append(record)

    # ------------------------------------------------------------------
    # Difference calculations
    # ------------------------------------------------------------------

    def compute_pairwise_differences(self) -> dict[tuple[str, str], pd.Series]:
        diffs = {}
        for i, col_i in enumerate(self.depth_columns):
            if col_i not in self._df.columns:
                continue
            for j in range(i + 1, len(self.depth_columns)):
                col_j = self.depth_columns[j]
                if col_j not in self._df.columns:
                    continue
                diffs[(col_j, col_i)] = self._df[col_j] - self._df[col_i]
        return diffs

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_depth_columns(self) -> list[str]:
        return [col for col in self._df.columns if 'Depth' in col]

    def __repr__(self) -> str:
        tr = self.time_range
        time_str = f"{tr[0]} to {tr[1]}" if tr else "N/A"
        return (
            f"SensorData(sensors={len(self.depth_columns)}, rows={self.row_count}, "
            f"time={time_str}, source='{self.source_file}')"
        )
