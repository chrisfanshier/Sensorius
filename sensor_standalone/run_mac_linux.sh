#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$HERE/venv/bin/python"

ensure_venv() {
    if [ -x "$VENV_PY" ] && "$VENV_PY" -c "import sys" 2>/dev/null; then
        return 0
    fi
    if [ -d "$HERE/venv" ]; then
        echo "Existing venv cannot run on this computer (copied folder or moved Python)."
        echo "Recreating virtual environment..."
        rm -rf "$HERE/venv"
    else
        echo "First run: setting up Python environment..."
    fi
    python3 -m venv "$HERE/venv"
}

ensure_venv

if ! "$VENV_PY" -c "import PySide6, pyqtgraph, pandas, numpy, scipy" 2>/dev/null; then
    echo "Installing requirements (one-time, may take a few minutes)..."
    "$VENV_PY" -m pip install -r "$HERE/requirements.txt"
fi

cd "$HERE/.."
exec "$VENV_PY" -m sensor_standalone
