# Sensorius (Standalone)

Portable desktop coring sensor analysis: depth/time correction, trip detection, piston geometry, winch alignment, and deployment calculations — with built-in metadata entry and native file uploads (RBR `.rsk`, Star-Oddi `.dat`/`.acc`/`.txt`, winch logs of any extension).

No PostgreSQL or Streamlit required. All data lives in a **portable project folder** (SQLite + copied files).

## Requirements (launcher version)

| Requirement | Details |
|---|---|
| Python | 3.10+ |
| PATH | `python` or `py -3` on Windows |
| Internet | First run only (pip install into `sensor_standalone/venv/`) |

## Running

**Windows:** double-click `run_windows.bat`  
**macOS/Linux:** `./run_mac_linux.sh`

The launcher creates `sensor_standalone/venv/` on first run using whatever `python` / `py -3` is on **that** computer. Do **not** copy the `venv` folder to another PC (it embeds the original Python path). If you already did, delete `venv` and run the launcher again — recent launchers recreate it automatically when broken.

Manual:

```bash
pip install -r sensor_standalone/requirements.txt
cd ..   # parent of sensor_standalone
python -m sensor_standalone
```

## Project layout

```
MyProject/
  sensorius_data.sqlite
  sensor_data/<cruise>/     # copied .rsk, .dat, …
  winch_data/<cruise>/      # copied winch logs (.dat, .csv, .raw, …)
```

## Workflow

1. **File ▸ New Project…** — pick a folder
2. **Data Manager** tab — create cruise, core (metadata + deployment window), register sensor and winch files
3. **Analysis** tab — select cruise/core, run the 10 analysis modes
4. **Save All to Project** / **Restore Results** — persists analysis to SQLite (multiple runs per core supported)

Trigger core length and penetration live on the **same core row** as the piston core (no separate TC record). `trigger_core_penetration` pre-fills Calculate mode and is written back when you save.

## Tests

```bash
python tests/test_sensor_standalone_headless.py
QT_QPA_PLATFORM=offscreen python -c "
import sys; sys.path.insert(0, '.')
from pyqtgraph.Qt import QtWidgets
import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
app = QtWidgets.QApplication([])
from sensor_standalone.gui.main_window import MainWindow
w = MainWindow(); w.show()
print('ok GUI smoke')
"
```

## Extending

| Change | File |
|--------|------|
| Winch ship format | `formats.py` → `WINCH_FORMATS` |
| Parser tweak | `persistence/file_parsers.py` |
| Core metadata field | `persistence/project.py` + `gui/data_manager.py` |

PyInstaller packaging is deferred; use the launcher for now.
