"""
Time correction processing - heave-based cross-correlation method.

Isolates wave/heave motion via bandpass filter, then uses
scipy.signal.correlate with parabolic sub-sample refinement to
determine the optimal time offset between sensors.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import signal as sp_signal

from ..models.sensor_data import SensorData, CorrectionRecord
from ..models.analysis_result import TimeOffsetResult


class TimeCorrectionProcessor:
    """
    Calculates and applies time lag corrections using heave cross-correlation.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def get_heave(
        series: np.ndarray,
        fs: float,
        low_freq: float = 0.05,
        high_freq: float = 0.5,
        order: int = 4,
    ) -> np.ndarray:
        """
        Isolate wave/heave motion from a depth time series.

        1. Detrend with a 2nd-order polynomial.
        2. Bandpass filter to retain only heave frequencies.
        """
        series = np.asarray(series, dtype=float)
        if len(series) < 3:
            return series

        x = np.arange(len(series))
        p = np.polyfit(x, series, 2)
        detrended = series - np.polyval(p, x)

        nyquist = fs / 2.0
        low = max(low_freq, 0.001)
        high = min(high_freq, nyquist * 0.99)
        if low >= high:
            return detrended

        sos = sp_signal.butter(order, [low, high], 'bp', fs=fs, output='sos')
        return sp_signal.sosfiltfilt(sos, detrended)

    @staticmethod
    def cross_correlate_offset(
        ref_heave: np.ndarray,
        mov_heave: np.ndarray,
        fs: float,
    ) -> tuple[float, np.ndarray, np.ndarray]:
        """
        Compute time offset between two heave signals via cross-correlation
        with parabolic sub-sample refinement.

        Returns:
            (offset_seconds, correlation, lags_seconds)
        """
        corr = sp_signal.correlate(ref_heave, mov_heave, mode='full')
        lags = sp_signal.correlation_lags(len(ref_heave), len(mov_heave), mode='full')

        idx = int(np.argmax(np.abs(corr)))

        if 0 < idx < len(corr) - 1:
            y_p = corr[idx - 1]
            y_0 = corr[idx]
            y_n = corr[idx + 1]
            denom = y_p - 2 * y_0 + y_n
            if abs(denom) > 1e-12:
                delta = 0.5 * (y_p - y_n) / denom
            else:
                delta = 0.0
        else:
            delta = 0.0

        offset_seconds = float((lags[idx] + delta) / fs)
        lags_seconds = lags / fs

        return offset_seconds, corr, lags_seconds

    @staticmethod
    def calculate_offsets(
        sensor_data: SensorData,
        start_idx: int,
        end_idx: int,
        ref_col: str,
        low_freq: float = 0.05,
        high_freq: float = 0.5,
        filter_order: int = 4,
    ) -> list[TimeOffsetResult]:
        """
        Calculate optimal time offsets for each non-reference sensor.

        Args:
            sensor_data: The full dataset.
            start_idx: Start row index of the selected range (inclusive).
            end_idx: End row index of the selected range (inclusive).
            ref_col: Reference depth column name.
            low_freq: Bandpass lower cutoff (Hz).
            high_freq: Bandpass upper cutoff (Hz).
            filter_order: Butterworth filter order.

        Returns:
            List of TimeOffsetResult for each sensor.
        """
        datetime_col = sensor_data.datetime_col
        depth_cols = sensor_data.depth_columns

        df_sel = sensor_data.df.iloc[start_idx:end_idx + 1].copy()

        dt = pd.to_datetime(df_sel[datetime_col]).diff().dt.total_seconds()
        median_dt = dt.median()
        if median_dt <= 0:
            raise ValueError("Cannot determine sampling rate.")
        fs = 1.0 / median_dt

        ref_data = df_sel[ref_col].values.astype(float)
        if np.all(np.isnan(ref_data)):
            raise ValueError(f"Reference sensor has no valid data in selection.")
        ref_heave = TimeCorrectionProcessor.get_heave(
            ref_data, fs, low_freq, high_freq, filter_order
        )

        results = []
        for col in depth_cols:
            if col == ref_col:
                results.append(TimeOffsetResult(
                    sensor_column=col,
                    offset_seconds=0.0,
                    rms_value=0.0,
                    is_reference=True,
                ))
                continue

            if col not in df_sel.columns:
                continue

            mov_data = df_sel[col].values.astype(float)
            if np.all(np.isnan(mov_data)):
                results.append(TimeOffsetResult(
                    sensor_column=col,
                    offset_seconds=0.0,
                    rms_value=float('nan'),
                ))
                continue

            mov_heave = TimeCorrectionProcessor.get_heave(
                mov_data, fs, low_freq, high_freq, filter_order
            )

            offset_sec, corr, lags_sec = TimeCorrectionProcessor.cross_correlate_offset(
                ref_heave, mov_heave, fs
            )

            shift_samples = int(round(offset_sec * fs))
            n = len(ref_heave)
            if abs(shift_samples) < n:
                if shift_samples >= 0:
                    rms = float(np.sqrt(np.nanmean(
                        (ref_heave[shift_samples:] - mov_heave[:n - shift_samples]) ** 2
                    )))
                else:
                    s = -shift_samples
                    rms = float(np.sqrt(np.nanmean(
                        (ref_heave[:n - s] - mov_heave[s:]) ** 2
                    )))
            else:
                rms = float('nan')

            results.append(TimeOffsetResult(
                sensor_column=col,
                offset_seconds=offset_sec,
                rms_value=rms,
            ))

        return results

    @staticmethod
    def compute_heave_profiles(
        sensor_data: SensorData,
        start_idx: int,
        end_idx: int,
        low_freq: float = 0.05,
        high_freq: float = 0.5,
        filter_order: int = 4,
    ) -> tuple[dict[str, np.ndarray], float]:
        """
        Compute heave profiles for all sensors within the selection range.

        Returns:
            (heaves, fs)
            heaves: Dict mapping depth_column -> heave array.
            fs: Sampling frequency in Hz.
        """
        datetime_col = sensor_data.datetime_col
        df_sel = sensor_data.df.iloc[start_idx:end_idx + 1].copy()

        dt = pd.to_datetime(df_sel[datetime_col]).diff().dt.total_seconds()
        fs = 1.0 / dt.median()

        heaves = {}
        for col in sensor_data.depth_columns:
            if col in df_sel.columns:
                data = df_sel[col].values.astype(float)
                heaves[col] = TimeCorrectionProcessor.get_heave(
                    data, fs, low_freq, high_freq, filter_order
                )
        return heaves, fs

    @staticmethod
    def apply_offset_to_series(
        time_seconds: np.ndarray,
        values: np.ndarray,
        offset_seconds: float,
    ) -> np.ndarray:
        """
        Shift a time series by a sub-sample offset using linear interpolation.
        """
        t_target = time_seconds + offset_seconds
        return np.interp(time_seconds, t_target, values)

    @staticmethod
    def apply_offsets(
        sensor_data: SensorData,
        offsets: list[TimeOffsetResult],
    ) -> SensorData:
        """
        Apply time offsets to the full dataset using sub-sample interpolation.

        Returns a new SensorData with corrected values.
        """
        datetime_col = sensor_data.datetime_col
        corrected_df = sensor_data.df.copy()

        timestamps = pd.to_datetime(corrected_df[datetime_col])
        t_sec = (timestamps - timestamps.iloc[0]).dt.total_seconds().values

        for result in offsets:
            if result.is_reference or result.offset_seconds == 0.0:
                continue

            col = result.sensor_column
            if col not in corrected_df.columns:
                continue

            corrected_df[col] = TimeCorrectionProcessor.apply_offset_to_series(
                t_sec, corrected_df[col].values.astype(float), result.offset_seconds
            )

        new_data = sensor_data.copy()
        new_data.update_dataframe(corrected_df)

        for result in offsets:
            if not result.is_reference and result.offset_seconds != 0.0:
                new_data.add_correction(CorrectionRecord(
                    correction_type='time_shift',
                    sensor_column=result.sensor_column,
                    description=f"Time shift: {result.offset_seconds:+.4f}s (heave cross-correlation)",
                    parameters={
                        'offset_seconds': result.offset_seconds,
                        'rms_heave_residual': result.rms_value,
                    },
                ))

        return new_data

    @staticmethod
    def apply_manual_offsets(
        sensor_data: SensorData,
        offsets: dict[str, float],
    ) -> dict[str, float]:
        """
        Apply constant manual time shifts to specified depth columns.

        Args:
            sensor_data: The SensorData to modify (mutated in place).
            offsets: Maps depth_column_name -> offset_seconds.

        Returns:
            dict of actually applied offsets (non-zero only).
        """
        datetime_col = sensor_data.datetime_col
        timestamps = pd.to_datetime(sensor_data.df[datetime_col])
        t_sec = (timestamps - timestamps.iloc[0]).dt.total_seconds().values

        applied = {}
        for col, offset in offsets.items():
            if offset == 0.0:
                continue
            if col not in sensor_data.df.columns:
                continue

            shifted = TimeCorrectionProcessor.apply_offset_to_series(
                t_sec, sensor_data.df[col].values.astype(float), offset
            )
            sensor_data.update_depth_column(col, shifted)

            sensor_data.add_correction(CorrectionRecord(
                correction_type='time_shift_manual',
                sensor_column=col,
                description=f"Manual time shift: {offset:+.4f}s",
                parameters={'offset_seconds': offset},
            ))
            applied[col] = offset

        return applied
