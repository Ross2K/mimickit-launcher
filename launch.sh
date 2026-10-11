#!/usr/bin/env bash
# MimicKit Launcher - Linux starter. Needs Python 3 with tkinter (sudo apt install python3-tk) and matplotlib.
# Set MIMICKIT_LAUNCHER_PYTHON to force a specific interpreter.
cd "$(dirname "$0")"
PY="${MIMICKIT_LAUNCHER_PYTHON:-$(command -v python3 || command -v python)}"
[ -z "$PY" ] && { echo "Python 3 not found"; exit 1; }
exec "$PY" mimickit_launcher.py "$@"
