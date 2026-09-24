"""
Depth correction processing - pure business logic, no Qt dependencies.

Applies depth-dependent (regression-based) and/or manual constant offsets
to sensor data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..models.sensor_data import SensorData, CorrectionRecord
from ..models.calibration import DepthCalibration


class DepthCorrectionProcessor:
    """
    Applies depth corrections to a SensorData instance.

    Can apply:
    - Regression-based corrections from a DepthCalibration
    - Manual constant offsets per depth column
    """

    @staticmethod
    def apply_calibration(
        sensor_data: SensorData,
        calibration: DepthCalibration,
        ref_col: str,
        target_mapping: dict[str, str],
        enabled_targets: list[str] | None = None,
    ) -> dict[str, dict]:
        """
        Apply depth-dependent calibration corrections.

        Args:
            sensor_data: The SensorData to modify (mutated in place).
            calibration: The DepthCalibration containing regression models.
            ref_col: The reference depth column name (will not be modified).
            target_mapping: Maps calibration label -> depth column name for targets.
            enabled_targets: Calibration labels to correct. If None, all applicable.

        Returns:
            dict mapping depth_column -> {mean, std, min, max} of applied corrections.
        """
        # Determine which calibration label corresponds to ref_col
        ref_label = None
        all_mapping = dict(target_mapping)
        for cal_label, col in all_mapping.items():
            if col == ref_col:
                ref_label = cal_label
                break

        if ref_label is None:
            raise ValueError(f"Reference column {ref_col} not found in calibration mapping")

        if ref_col not in sensor_data.df.columns:
            raise ValueError(f"Reference column not found: {ref_col}")

        ref_depths = sensor_data.df[ref_col].values
        applicable = calibration.get_applicable_corrections(ref_label)
        results = {}

        for item in applicable:
            target_label = item['target']
            if enabled_targets is not None and target_label not in enabled_targets:
                continue

            target_col = target_mapping.get(target_label)
            if target_col is None or target_col not in sensor_data.df.columns:
                continue

            reg = item['reg']
            sign = item['sign']

            offsets = reg.slope * ref_depths + reg.intercept
            corrections = sign * offsets

            original = sensor_data.df[target_col].values
            sensor_data.update_depth_column(target_col, original + corrections)

            sensor_data.add_correction(CorrectionRecord(
                correction_type='depth_calibration',
                sensor_column=target_col,
                description=(
                    f"Regression {reg.sensor_j}-{reg.sensor_i}: "
                    f"slope={reg.slope:.6f}, intercept={reg.intercept:.6f}"
                ),
                parameters={
                    'slope': reg.slope,
                    'intercept': reg.intercept,
                    'sign': sign,
                    'ref_col': ref_col,
                },
            ))

            results[target_col] = {
                'mean': float(np.nanmean(corrections)),
                'std': float(np.nanstd(corrections)),
                'min': float(np.nanmin(corrections)),
                'max': float(np.nanmax(corrections)),
            }

        return results

    @staticmethod
    def apply_manual_offsets(
        sensor_data: SensorData,
        offsets: dict[str, float],
    ) -> dict[str, float]:
        """
        Apply constant manual offsets to specified depth columns.

        Args:
            sensor_data: The SensorData to modify (mutated in place).
            offsets: Maps depth_column_name -> offset_meters.

        Returns:
            dict of actually applied offsets (non-zero only).
        """
        applied = {}
        for col, offset in offsets.items():
            if offset == 0.0:
                continue
            if col not in sensor_data.df.columns:
                continue

            original = sensor_data.df[col].values
            sensor_data.update_depth_column(col, original + offset)

            sensor_data.add_correction(CorrectionRecord(
                correction_type='depth_manual',
                sensor_column=col,
                description=f"Manual offset: {offset:+.4f}m",
                parameters={'offset_m': offset},
            ))
            applied[col] = offset

        return applied
