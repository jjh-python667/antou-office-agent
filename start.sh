#!/bin/sh
# macOS / Linux counterpart of start.cmd. Extra arguments are passed to app.py.
set -eu
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  if ! "$PY" -m venv .venv; then
    echo "Could not create .venv. On Debian/Ubuntu, install python3-venv. Or install requirements.txt yourself and run: python app.py" >&2
    exit 1
  fi
elif [ ! -x .venv/bin/python ]; then
  echo "error: .venv exists but .venv/bin/python is missing. Refusing to delete .venv. A Windows virtual environment keeps its interpreter in .venv/Scripts instead. Remove or recreate .venv yourself, then run start.sh again." >&2
  exit 1
fi
if ! .venv/bin/python -c "import openpyxl, docx" >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python app.py "$@"
