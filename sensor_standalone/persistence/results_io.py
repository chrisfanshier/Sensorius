"""SQLite persistence for analysis results (replaces sensor_analysis_results)."""
from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np

from .project import ProjectStore, _iso

_FLAT_COLUMNS = frozenset({
    "trip_index", "trip_datetime", "start_core_index", "start_core_datetime",
    "result_recoil_max", "result_recoil_time_s", "result_fall_dist", "result_suck_in",
    "result_recoil_start", "result_freefall_start", "result_piston_suck",
    "result_seafloor", "result_piston_alt", "result_pen_deficit", "result_freefall_est",
    "result_eff_trig_line", "trigger_pen_m", "winch_trip_index", "winch_trip_datetime",
    "winch_time_offset_sec",
})


class _NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

    def iterencode(self, o, _one_shot=False):
        return super().iterencode(self._sanitize(o), _one_shot)

    def _sanitize(self, obj):
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        if isinstance(obj, dict):
            return {k: self._sanitize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._sanitize(v) for v in obj]
        return obj


def _conn(store: ProjectStore):
    return store._conn  # noqa: SLF001 — intentional tight coupling


def _is_blank(val) -> bool:
    """True for values that must never overwrite a stored one.

    ``None`` means "this stage did not produce a value", and SQLite has no NaN
    so a non-finite float lands as NULL too. Either one silently erased a
    previously saved number, which is the one thing a single-row-per-core
    layout cannot afford.
    """
    if val is None:
        return True
    if isinstance(val, float) and not math.isfinite(val):
        return True
    if isinstance(val, np.floating) and not math.isfinite(float(val)):
        return True
    return False


def _writable_flat(flat_data: Optional[dict]) -> dict:
    """Keep only real columns carrying a value worth writing."""
    return {
        k: v for k, v in (flat_data or {}).items()
        if k in _FLAT_COLUMNS and not _is_blank(v)
    }


def insert_result(
    store: ProjectStore,
    core_id: int,
    flat_data: Optional[dict] = None,
    params_section: Optional[dict] = None,
) -> int:
    cols = ["core_id"]
    vals = [core_id]
    for key, val in _writable_flat(flat_data).items():
        cols.append(key)
        if key.endswith("_datetime"):
            vals.append(_iso(val))
        else:
            vals.append(val)

    if params_section is not None:
        cols.append("params")
        vals.append(json.dumps(params_section, cls=_NumpyEncoder))

    placeholders = ", ".join("?" for _ in cols)
    col_sql = ", ".join(cols)
    cur = _conn(store).execute(
        f"INSERT INTO analysis_results ({col_sql}) VALUES ({placeholders})",
        vals,
    )
    _conn(store).commit()
    return cur.lastrowid


def update_result(
    store: ProjectStore,
    result_id: int,
    flat_data: Optional[dict] = None,
    params_section: Optional[dict] = None,
) -> None:
    writable = _writable_flat(flat_data)
    parts = [f"{k} = ?" for k in writable]
    vals = [
        _iso(v) if k.endswith("_datetime") else v
        for k, v in writable.items()
    ]
    # analyzed_at is only defaulted on insert, and with one row per core the
    # row is updated for the rest of its life, so bump it here or it would
    # report when the core was first touched rather than last saved.
    parts.append("analyzed_at = datetime('now')")
    vals.append(result_id)
    _conn(store).execute(
        f"UPDATE analysis_results SET {', '.join(parts)} WHERE result_id = ?",
        vals,
    )

    if params_section is not None:
        row = _conn(store).execute(
            "SELECT params FROM analysis_results WHERE result_id = ?",
            (result_id,),
        ).fetchone()
        existing = {}
        if row and row["params"]:
            existing = json.loads(row["params"])
        existing.update(params_section)
        _conn(store).execute(
            "UPDATE analysis_results SET params = ? WHERE result_id = ?",
            (json.dumps(existing, cls=_NumpyEncoder), result_id),
        )

    _conn(store).commit()


def latest_result_id(store: ProjectStore, core_id: int) -> Optional[int]:
    """Return the analysis row for *core_id*, or None if it has never been saved.

    A core has one analysis row. Older projects can hold several from when each
    save forked a new one; the highest result_id is the most recently inserted
    (result_id is an INTEGER PRIMARY KEY, so it is the monotonic rowid), which
    is the one those projects were already restoring from.
    """
    row = _conn(store).execute(
        "SELECT MAX(result_id) AS rid FROM analysis_results WHERE core_id = ?",
        (core_id,),
    ).fetchone()
    return None if row is None or row["rid"] is None else int(row["rid"])


def upsert_result(
    store: ProjectStore,
    core_id: int,
    flat_data: Optional[dict] = None,
    params_section: Optional[dict] = None,
) -> tuple[int, bool]:
    """Write into the core's analysis row, creating it on first save.

    Returns ``(result_id, created)``.
    """
    result_id = latest_result_id(store, core_id)
    if result_id is None:
        return insert_result(store, core_id, flat_data, params_section), True
    update_result(store, result_id, flat_data, params_section)
    return result_id, False


def fetch_results_for_core(store: ProjectStore, core_id: int) -> list[dict]:
    rows = _conn(store).execute(
        """SELECT result_id, analyzed_at, trip_index, start_core_index,
                  result_recoil_max, winch_trip_index, winch_time_offset_sec, params
           FROM analysis_results
           WHERE core_id = ?
           ORDER BY analyzed_at DESC""",
        (core_id,),
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        if d.get("params"):
            d["params"] = json.loads(d["params"])
        results.append(d)
    return results


def fetch_latest_result(store: ProjectStore, core_id: int) -> dict | None:
    """Return the core's analysis row in full, or None if never saved."""
    result_id = latest_result_id(store, core_id)
    return None if result_id is None else fetch_result_by_id(store, result_id)


def fetch_result_by_id(store: ProjectStore, result_id: int) -> dict | None:
    row = _conn(store).execute(
        "SELECT * FROM analysis_results WHERE result_id = ?",
        (result_id,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    if d.get("params"):
        d["params"] = json.loads(d["params"])
    return d
