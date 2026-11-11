#!/bin/sh
# macOS / Linux counterpart of start.cmd. Extra arguments are passed to app.py.
set -eu
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
if [ ! -x .venv/bin/python ]; then
  rm -rf .venv
  if ! "$PY" -m venv .venv; then
    echo "Could not create .venv. On Debian/Ubuntu, install python3-venv. Or install requirements.txt yourself and run: python app.py" >&2
    exit 1
  fi
fi
if ! .venv/bin/python -c "import openpyxl, docx" >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python app.py "$@"
