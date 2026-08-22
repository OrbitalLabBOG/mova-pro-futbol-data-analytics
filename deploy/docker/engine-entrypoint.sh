#!/bin/sh
set -eu
umask 027
python - <<'PY'
import os
import sqlite3

actual = tuple(int(part) for part in sqlite3.sqlite_version.split("."))
minimum_text = os.environ.get("MOVA_SQLITE_MIN_VERSION", "3.51.3")
minimum = tuple(int(part) for part in minimum_text.split("."))
if actual < minimum:
    raise SystemExit(f"SQLite {sqlite3.sqlite_version} < required {minimum_text}")
print(f'{{"event":"runtime_gate","sqlite_version":"{sqlite3.sqlite_version}","status":"passed"}}', flush=True)
PY
exec "$@"
