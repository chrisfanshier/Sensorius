"""Project store: portable folder with SQLite + copied sensor/winch files."""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

DB_FILENAME = "sensorius_data.sqlite"

SUBDIRS = {
    "sensor": "sensor_data",
    "winch": "winch_data",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cruises (
    cruise_id     INTEGER PRIMARY KEY,
    cruise_name   TEXT NOT NULL UNIQUE,
    vessel_name   TEXT,
    notes         TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cores (
    core_id                   INTEGER PRIMARY KEY,
    cruise_id                 INTEGER NOT NULL REFERENCES cruises(cruise_id) ON DELETE CASCADE,
    core_name                 TEXT NOT NULL,
    core_type                 TEXT,
    core_length               REAL,
    scope                     REAL,
    start_datetime            TEXT,
    end_datetime              TEXT,
    trigger_line_length       REAL,
    trigger_core_length       REAL,
    trigger_core_penetration  REAL,
    trigger_core_recovery     REAL,
    piston_core_recovery      REAL,
    pig_weights               TEXT,
    wire_type                 TEXT,
    notes                     TEXT,
    created_at                TEXT DEFAULT (datetime('now')),
    UNIQUE (cruise_id, core_name)
);

CREATE TABLE IF NOT EXISTS sensor_files (
    sensor_file_id  INTEGER PRIMARY KEY,
    core_id         INTEGER NOT NULL REFERENCES cores(core_id) ON DELETE CASCADE,
    file_name       TEXT NOT NULL,
    rel_path        TEXT NOT NULL,
    sensor_location TEXT,
    sensor_type     TEXT,
    remarks         TEXT
);

CREATE TABLE IF NOT EXISTS winch_files (
    winch_file_id   INTEGER PRIMARY KEY,
    cruise_id       INTEGER NOT NULL REFERENCES cruises(cruise_id) ON DELETE CASCADE,
    file_name       TEXT NOT NULL,
    rel_path        TEXT NOT NULL,
    start_time      TEXT,
    end_time        TEXT,
    settings        TEXT NOT NULL,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS analysis_results (
    result_id               INTEGER PRIMARY KEY,
    core_id                 INTEGER NOT NULL REFERENCES cores(core_id) ON DELETE CASCADE,
    analyzed_at             TEXT DEFAULT (datetime('now')),
    trip_index              INTEGER,
    trip_datetime           TEXT,
    start_core_index        INTEGER,
    start_core_datetime     TEXT,
    result_recoil_max       REAL,
    result_recoil_time_s    REAL,
    result_fall_dist        REAL,
    result_suck_in          REAL,
    result_recoil_start     REAL,
    result_freefall_start   REAL,
    result_piston_suck      REAL,
    result_seafloor         REAL,
    result_piston_alt       REAL,
    result_pen_deficit      REAL,
    result_freefall_est     REAL,
    result_eff_trig_line    REAL,
    trigger_pen_m           REAL,
    winch_trip_index        INTEGER,
    winch_trip_datetime     TEXT,
    winch_time_offset_sec   REAL,
    params                  TEXT
);
"""


def _iso(dt) -> Optional[str]:
    if dt is None or (isinstance(dt, float) and pd.isna(dt)):
        return None
    ts = pd.to_datetime(dt)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.isoformat(sep=" ")


def _num(value) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _safe_dirname(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_ ." else "_" for c in name).strip() or "unnamed"


def _core_row_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["core_type_name"] = d.get("core_type")
    return d


class ProjectStore:
    """Owns one portable Sensorius project folder."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        for sub in SUBDIRS.values():
            (self.root / sub).mkdir(exist_ok=True)

        self.db_path = self.root / DB_FILENAME
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def full_path(self, rel_path: str, file_name: str) -> str:
        return str(self.root / rel_path / file_name)

    # ── cruises ───────────────────────────────────────────────────────

    def add_cruise(self, cruise_name: str, vessel_name: str = None, notes: str = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO cruises (cruise_name, vessel_name, notes) VALUES (?, ?, ?)",
            (cruise_name.strip(), vessel_name or None, notes or None),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_cruise(self, cruise_id: int, cruise_name: str, vessel_name: str = None, notes: str = None):
        self._conn.execute(
            "UPDATE cruises SET cruise_name = ?, vessel_name = ?, notes = ? WHERE cruise_id = ?",
            (cruise_name.strip(), vessel_name or None, notes or None, cruise_id),
        )
        self._conn.commit()

    def delete_cruise(self, cruise_id: int):
        for row in self.fetch_winch_files(cruise_id):
            self._remove_file(row["rel_path"], row["file_name"])
        for core in self.fetch_cores(cruise_id):
            for sf in self.fetch_sensor_files(core["core_id"]):
                self._remove_file(sf["rel_path"], sf["file_name"])
        self._conn.execute("DELETE FROM cruises WHERE cruise_id = ?", (cruise_id,))
        self._conn.commit()

    def fetch_cruises(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM cruises ORDER BY cruise_name").fetchall()
        return [dict(r) for r in rows]

    # ── cores ─────────────────────────────────────────────────────────

    def add_core(
        self,
        cruise_id: int,
        core_name: str,
        core_type: str = None,
        core_length: float = None,
        scope: float = None,
        start_datetime=None,
        end_datetime=None,
        trigger_line_length: float = None,
        trigger_core_length: float = None,
        trigger_core_penetration: float = None,
        trigger_core_recovery: float = None,
        piston_core_recovery: float = None,
        pig_weights: str = None,
        wire_type: str = None,
        notes: str = None,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO cores (
                cruise_id, core_name, core_type, core_length, scope,
                start_datetime, end_datetime, trigger_line_length,
                trigger_core_length, trigger_core_penetration,
                trigger_core_recovery, piston_core_recovery,
                pig_weights, wire_type, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cruise_id, core_name.strip(), core_type or None,
                _num(core_length), _num(scope),
                _iso(start_datetime), _iso(end_datetime),
                _num(trigger_line_length), _num(trigger_core_length),
                _num(trigger_core_penetration), _num(trigger_core_recovery),
                _num(piston_core_recovery), pig_weights or None, wire_type or None,
                notes or None,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_core(self, core_id: int, **fields):
        allowed = {
            "core_name", "core_type", "core_length", "scope",
            "start_datetime", "end_datetime", "trigger_line_length",
            "trigger_core_length", "trigger_core_penetration",
            "trigger_core_recovery", "piston_core_recovery",
            "pig_weights", "wire_type", "notes",
        }
        parts = []
        values = []
        for key, val in fields.items():
            if key not in allowed:
                continue
            if key in ("start_datetime", "end_datetime"):
                val = _iso(val)
            elif key in (
                "core_length", "scope", "trigger_line_length", "trigger_core_length",
                "trigger_core_penetration", "trigger_core_recovery", "piston_core_recovery",
            ):
                val = _num(val)
            elif key == "core_name" and val is not None:
                val = str(val).strip()
            parts.append(f"{key} = ?")
            values.append(val)
        if not parts:
            return
        values.append(core_id)
        self._conn.execute(
            f"UPDATE cores SET {', '.join(parts)} WHERE core_id = ?",
            values,
        )
        self._conn.commit()

    def update_trigger_core_penetration(self, core_id: int, value: float):
        self.update_core(core_id, trigger_core_penetration=_num(value))

    def delete_core(self, core_id: int):
        for row in self.fetch_sensor_files(core_id):
            self._remove_file(row["rel_path"], row["file_name"])
        self._conn.execute("DELETE FROM cores WHERE core_id = ?", (core_id,))
        self._conn.commit()

    def get_core(self, core_id: int) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM cores WHERE core_id = ?", (core_id,)).fetchone()
        return _core_row_dict(row) if row else None

    def fetch_cores(self, cruise_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM cores WHERE cruise_id = ? ORDER BY core_name",
            (cruise_id,),
        ).fetchall()
        return [_core_row_dict(r) for r in rows]

    def fetch_cores_with_sensor_files(self, cruise_id: int) -> list[dict]:
        rows = self._conn.execute(
            """SELECT DISTINCT c.*
               FROM cores c
               JOIN sensor_files sf ON c.core_id = sf.core_id
               WHERE c.cruise_id = ?
               ORDER BY c.core_name""",
            (cruise_id,),
        ).fetchall()
        return [_core_row_dict(r) for r in rows]

    # ── file copy-in ──────────────────────────────────────────────────

    def _cruise_name(self, cruise_id: int) -> str:
        row = self._conn.execute(
            "SELECT cruise_name FROM cruises WHERE cruise_id = ?", (cruise_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown cruise_id: {cruise_id}")
        return row["cruise_name"]

    def _import_file(self, src_path: str, kind: str, cruise_id: int) -> tuple[str, str]:
        src = Path(src_path)
        if not src.is_file():
            raise FileNotFoundError(f"File not found: {src_path}")

        rel_dir = Path(SUBDIRS[kind]) / _safe_dirname(self._cruise_name(cruise_id))
        dest_dir = self.root / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = dest_dir / src.name
        stem, suffix = src.stem, src.suffix
        counter = 1
        while dest.exists():
            dest = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        shutil.copy2(src, dest)
        return dest.name, str(rel_dir)

    def _remove_file(self, rel_path: str, file_name: str):
        try:
            target = (self.root / rel_path / file_name).resolve()
            if self.root.resolve() in target.parents and target.is_file():
                target.unlink()
        except OSError as exc:
            logger.warning("Could not remove file %s/%s: %s", rel_path, file_name, exc)

    # ── sensor files ──────────────────────────────────────────────────

    def add_sensor_file(
        self,
        core_id: int,
        src_path: str,
        sensor_location: str = None,
        sensor_type: str = None,
        remarks: str = None,
    ) -> int:
        core = self.get_core(core_id)
        if core is None:
            raise ValueError(f"Unknown core_id: {core_id}")
        file_name, rel_path = self._import_file(src_path, "sensor", core["cruise_id"])
        cur = self._conn.execute(
            """INSERT INTO sensor_files
               (core_id, file_name, rel_path, sensor_location, sensor_type, remarks)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (core_id, file_name, rel_path, sensor_location or None,
             sensor_type or None, remarks or None),
        )
        self._conn.commit()
        return cur.lastrowid

    def fetch_sensor_files(self, core_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sensor_files WHERE core_id = ? ORDER BY file_name",
            (core_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_sensor_file(self, sensor_file_id: int):
        row = self._conn.execute(
            "SELECT rel_path, file_name FROM sensor_files WHERE sensor_file_id = ?",
            (sensor_file_id,),
        ).fetchone()
        if row:
            self._remove_file(row["rel_path"], row["file_name"])
        self._conn.execute("DELETE FROM sensor_files WHERE sensor_file_id = ?", (sensor_file_id,))
        self._conn.commit()

    # ── winch files ───────────────────────────────────────────────────

    def add_winch_file(
        self,
        cruise_id: int,
        src_path: str,
        settings: dict,
        start_time=None,
        end_time=None,
        notes: str = None,
    ) -> int:
        file_name, rel_path = self._import_file(src_path, "winch", cruise_id)
        cur = self._conn.execute(
            """INSERT INTO winch_files
               (cruise_id, file_name, rel_path, start_time, end_time, settings, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cruise_id, file_name, rel_path, _iso(start_time), _iso(end_time),
             json.dumps(settings), notes or None),
        )
        self._conn.commit()
        return cur.lastrowid

    def fetch_winch_files(self, cruise_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM winch_files WHERE cruise_id = ? ORDER BY file_name",
            (cruise_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_winch_file(self, winch_file_id: int):
        row = self._conn.execute(
            "SELECT rel_path, file_name FROM winch_files WHERE winch_file_id = ?",
            (winch_file_id,),
        ).fetchone()
        if row:
            self._remove_file(row["rel_path"], row["file_name"])
        self._conn.execute("DELETE FROM winch_files WHERE winch_file_id = ?", (winch_file_id,))
        self._conn.commit()
