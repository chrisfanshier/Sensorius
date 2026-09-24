"""
Statistics computation - pure business logic, no Qt dependencies.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..models.sensor_data import SensorData
from ..models.analysis_result import StatisticsResult


def compute_statistics(
    sensor_data: SensorData,
    start_idx: int | None = None,
    end_idx: int | None = None,
) -> StatisticsResult:
    """
    Compute pairwise statistics for sensor depth data.

    Args:
        sensor_data: The SensorData instance.
        start_idx: Start index of selection (None for full range).
        end_idx: End index of selection (None for full range).

    Returns:
        StatisticsResult with all computed statistics.
    """
    df = sensor_data.df
    depth_cols = sensor_data.depth_columns

    if start_idx is not None and end_idx is not None:
        df_calc = df.iloc[start_idx:end_idx + 1]
        range_desc = f"Selected range: rows {start_idx}-{end_idx} ({len(df_calc)} points)"
    else:
        df_calc = df
        range_desc = "Full dataset (no selection)"

    existing_cols = [c for c in depth_cols if c in df_calc.columns]
    mean_depth_all = float(df_calc[existing_cols].mean(axis=1).mean())

    # Per-column means
    column_means = {}
    for col in existing_cols:
        column_means[col] = float(df_calc[col].mean())

    # Pairwise difference means keyed by (col_j, col_i)
    diff_means = {}
    for i, col_i in enumerate(existing_cols):
        for j in range(i + 1, len(existing_cols)):
            col_j = existing_cols[j]
            diff_means[(col_j, col_i)] = float(
                (df_calc[col_j] - df_calc[col_i]).mean()
            )

    return StatisticsResult(
        range_description=range_desc,
        n_points=len(df_calc),
        mean_depth_all_sensors=mean_depth_all,
        column_means=column_means,
        difference_means=diff_means,
        source_file=sensor_data.source_file,
    )
