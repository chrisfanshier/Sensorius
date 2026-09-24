"""
Calibration builder - generates DepthCalibration from collected statistics.

Pure business logic, no Qt dependencies.

The calibration file format uses labels (A, B, C ...) internally.
This builder accepts a mapping from column names to calibration labels
so the caller can control which column becomes which label.
"""
from __future__ import annotations

import numpy as np
from scipy import stats as sp_stats

from ..models.calibration import DepthCalibration, RegressionEntry
from ..models.analysis_result import StatisticsResult

# Default calibration labels for the JSON format
DEFAULT_CAL_LABELS = ['A', 'B', 'C', 'D']


class CalibrationBuilder:
    """Builds a DepthCalibration from a collection of StatisticsResult entries."""

    @staticmethod
    def build(
        statistics: list[StatisticsResult],
        num_sensors: int,
        sensor_labels: list[str] | None = None,
        col_to_label: dict[str, str] | None = None,
    ) -> DepthCalibration:
        """
        Generate a DepthCalibration from collected statistics.

        Fits a linear regression for each sensor pair difference vs mean depth.

        Args:
            statistics: List of StatisticsResult from different depths/casts.
            num_sensors: Number of sensors.
            sensor_labels: Labels for calibration file (defaults to A, B, C ...).
            col_to_label: Optional map from column name -> label. If provided,
                          difference_means keys (col_j, col_i) are translated
                          to (label_j, label_i) before regression fitting.

        Returns:
            DepthCalibration with regression entries.
        """
        if len(statistics) < 2:
            raise ValueError("Need at least 2 statistics entries for regression")

        if sensor_labels is None:
            sensor_labels = DEFAULT_CAL_LABELS[:num_sensors]

        depth_data = np.array([s.mean_depth_all_sensors for s in statistics])

        # Build a reverse lookup if we have column-to-label mapping
        # We need to translate difference_means keys from column names to labels
        def _translate_key(key: tuple[str, str]) -> tuple[str, str] | None:
            if col_to_label is None:
                return key
            j, i = key
            lj = col_to_label.get(j)
            li = col_to_label.get(i)
            if lj is not None and li is not None:
                return (lj, li)
            return None

        regressions = []
        for i in range(num_sensors):
            for j in range(i + 1, num_sensors):
                label_i = sensor_labels[i]
                label_j = sensor_labels[j]

                diff_data = []
                for s in statistics:
                    found = False
                    for raw_key, val in s.difference_means.items():
                        translated = _translate_key(raw_key)
                        if translated == (label_j, label_i):
                            diff_data.append(val)
                            found = True
                            break
                    if not found:
                        diff_data.append(np.nan)

                diff_data = np.array(diff_data)

                # Remove NaN
                mask = ~(np.isnan(depth_data) | np.isnan(diff_data))
                depth_clean = depth_data[mask]
                diff_clean = diff_data[mask]

                if len(depth_clean) < 2:
                    continue

                res = sp_stats.linregress(depth_clean, diff_clean)
                regressions.append(RegressionEntry(
                    sensor_i=label_i,
                    sensor_j=label_j,
                    slope=float(res.slope),
                    intercept=float(res.intercept),
                    r_squared=float(res.rvalue ** 2),
                    p_value=float(res.pvalue),
                ))

        return DepthCalibration(
            num_sensors=num_sensors,
            sensor_labels=sensor_labels,
            regressions=regressions,
        )

    @staticmethod
    def predict_offsets(
        calibration: DepthCalibration,
        target_depth: float,
    ) -> dict[tuple[str, str], float]:
        """
        Predict offsets at a given depth from the calibration.
        """
        predictions = {}
        for reg in calibration.regressions:
            offset = reg.predict_offset(target_depth)
            predictions[(reg.sensor_j, reg.sensor_i)] = offset
        return predictions
