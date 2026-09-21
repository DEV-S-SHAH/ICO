#!/bin/bash
# ================================================================================
#   Intelligent Cache Optimization - macOS / Linux Launcher
# ================================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "[ERROR] Python 3 not found in PATH. Please install Python 3.9+."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "[INFO] Creating virtual environment in .venv..."
    $PYTHON -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    pip install -e .
    if [ -f requirements.txt ]; then
        pip install -r requirements.txt
    fi
else
    source .venv/bin/activate
fi

python run.py "$@"
