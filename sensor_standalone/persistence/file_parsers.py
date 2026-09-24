"""Self-contained sensor and winch file parsers (no repo imports)."""
from __future__ import annotations

import io
import logging
import os
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def process_rsk(full_path: str) -> Optional[pd.DataFrame]:
    """Read an RSK file and return datetime + depth/pressure columns."""
    try:
        from pyrsktools import RSK  # type: ignore
    except ImportError:
        raise ImportError(
            "pyRSKtools is required to load RSK sensor files. "
            "Install it with: pip install pyRSKtools"
        )

    if not os.path.exists(full_path):
        logger.error("RSK file not found: %s", full_path)
        return None

    try:
        with RSK(full_path) as rsk:
            rsk.open()
            rsk.readdata()
            rsk.deriveseapressure()
            rsk.derivedepth(latitude=45.0)
            return pd.DataFrame({
                "datetime": rsk.data["timestamp"],
                "Pressure (dbar)": rsk.data["pressure"],
                "Sea Pressure (dbar)": rsk.data["sea_pressure"],
                "Depth (m)": rsk.data["depth"],
            })
    except Exception as exc:  # noqa: BLE001
        logger.error("Error processing RSK file %s: %s", full_path, exc)
        return None


def parse_staroddi_dat(file_path: str) -> Optional[pd.DataFrame]:
    try:
        with open(file_path, "rb") as fh:
            lines = fh.read().decode("latin1").splitlines()
        data_start = next(i for i, line in enumerate(lines) if line and line[0].isdigit())
        colnames = [
            "index", "datetime", "temp", "press",
            "tilt_x", "tilt_y", "tilt_z", "EAL", "roll",
        ]
        df = pd.read_csv(
            io.StringIO("\n".join(lines[data_start:])),
            sep="\t", names=colnames, header=None,
            na_values="____", decimal=",",
        )
        df["datetime"] = df["datetime"].astype(str).str.replace(",", ".", regex=False)
        for col in ["temp", "press", "tilt_x", "tilt_y", "tilt_z", "EAL", "roll"]:
            df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["datetime"] = pd.to_datetime(
            df["datetime"], format="%d.%m.%Y %H:%M:%S.%f", errors="coerce"
        )
        return pd.DataFrame({
            "datetime": df["datetime"],
            "Pressure (dbar)": df["press"],
            "Sea Pressure (dbar)": df["press"],
            "Depth (m)": df["press"],
            "Tilt X": df["tilt_x"],
            "Tilt Y": df["tilt_y"],
            "Tilt Z": df["tilt_z"],
        })
    except Exception as exc:  # noqa: BLE001
        logger.error("Error parsing Star-Oddi .dat %s: %s", file_path, exc)
        return None


def parse_staroddi_acc(file_path: str) -> Optional[pd.DataFrame]:
    try:
        with open(file_path, "rb") as fh:
            lines = fh.read().decode("latin1").splitlines()
        data_start = next(i for i, line in enumerate(lines) if line and line[0].isdigit())
        colnames = ["rownum", "datetime", "g", "x_acc", "y_acc", "z_acc"]
        df = pd.read_csv(
            io.StringIO("\n".join(lines[data_start:])),
            sep="\t", names=colnames, header=None, na_values="____",
        )
        df["datetime"] = df["datetime"].astype(str).str.replace(",", ".", regex=False)
        df["datetime"] = pd.to_datetime(
            df["datetime"], format="%d.%m.%Y %H:%M:%S.%f", errors="coerce"
        )
        for col in ["g", "x_acc", "y_acc", "z_acc"]:
            df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return pd.DataFrame({
            "datetime": df["datetime"],
            "X_Acceleration": df["x_acc"],
            "Y_Acceleration": df["y_acc"],
            "Z_Acceleration": df["z_acc"],
            "Total_G": df["g"],
        })
    except Exception as exc:  # noqa: BLE001
        logger.error("Error parsing Star-Oddi .acc %s: %s", file_path, exc)
        return None


def process_star_oddi_data(full_path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(full_path):
        logger.error("Star-Oddi file not found: %s", full_path)
        return None
    lower = full_path.lower()
    if lower.endswith(".dat") or lower.endswith(".txt"):
        return parse_staroddi_dat(full_path)
    if lower.endswith(".acc"):
        return parse_staroddi_acc(full_path)
    logger.error("Unsupported Star-Oddi extension: %s", full_path)
    return None


def parse_sensor_file(full_path: str, sensor_type: str = "") -> Optional[pd.DataFrame]:
    """Dispatch by extension and optional sensor_type hint."""
    ext = os.path.splitext(full_path)[1].lower()
    stype = (sensor_type or "").lower()
    if ext == ".rsk" or "rbr" in stype:
        return process_rsk(full_path)
    if ext in (".dat", ".acc", ".txt") or "star" in stype:
        return process_star_oddi_data(full_path)
    logger.error("Unsupported sensor file: %s", full_path)
    return None


def parse_winch_dat(file_path: str, parsing_settings: dict) -> Optional[pd.DataFrame]:
    try:
        delimiter = parsing_settings.get("delimiter", ",")
        header_lines = parsing_settings.get("header_lines", 0)
        columns = parsing_settings.get("columns", None)
        datetime_code = parsing_settings.get("datetime_code", "pd.to_datetime(df['datetime'])")
        numeric_columns = parsing_settings.get("numeric_columns", [])

        df = pd.read_csv(
            file_path,
            delimiter=delimiter,
            skiprows=header_lines,
            header=None if columns else 0,
            names=columns if columns else None,
            low_memory=False,
            on_bad_lines="skip",
        )
        exec(f"df['datetime'] = {datetime_code}", {"df": df, "pd": pd})  # noqa: S102
        if pd.api.types.is_datetime64_any_dtype(df["datetime"]):
            if getattr(df["datetime"].dt, "tz", None) is not None:
                df["datetime"] = df["datetime"].dt.tz_localize(None)

        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.strip(), errors="coerce")
        return df
    except Exception as exc:  # noqa: BLE001
        logger.error("Error parsing winch file %s: %s", file_path, exc)
        return None
