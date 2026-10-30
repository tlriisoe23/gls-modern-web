"""Migrates GolfSoft GLS9 Microsoft Jet/Access (.mdb) database (all 60 tables) and
Schedules/*.csv round-robin templates into a modern SQLite (WAL) database."""
from __future__ import annotations

import csv
import io
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any


def _safe_ident(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]", "", name)
    return f'"{clean}"'


def _infer_val(v: str) -> Any:
    if v == "" or v is None:
        return None
    if re.fullmatch(r"-?\d+", v):
        try:
            return int(v)
        except ValueError:
            return v
    if re.fullmatch(r"-?\d+\.\d+", v):
        try:
            return float(v)
        except ValueError:
            return v
    return v


def migrate_mdb_to_sqlite(mdb_path: Path, sqlite_path: Path, schedules_dir: Path | None = None) -> dict[str, Any]:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    mdb_tables_bin = shutil.which("mdb-tables") or "/usr/bin/mdb-tables"
    mdb_export_bin = shutil.which("mdb-export") or "/usr/bin/mdb-export"

    res_t = subprocess.run([mdb_tables_bin, "-1", str(mdb_path)], capture_output=True, text=True, check=True, timeout=30)
    tables = sorted(t.strip() for t in res_t.stdout.splitlines() if t.strip())

    conn = sqlite3.connect(str(sqlite_path))
    conn.execute("PRAGMA journal_mode=WAL")
    migrated_tables = 0
    total_rows = 0

    with conn:
        for tbl in tables:
            res_csv = subprocess.run([mdb_export_bin, str(mdb_path), tbl], capture_output=True, text=True, check=True, timeout=30)
            reader = list(csv.reader(io.StringIO(res_csv.stdout)))
            if not reader:
                continue
            headers = [h.strip() for h in reader[0]]
            rows = reader[1:]
            q_tbl = _safe_ident(tbl)
            conn.execute(f"DROP TABLE IF EXISTS {q_tbl}")
            col_defs = ", ".join(f"{_safe_ident(h)} NUMERIC" for h in headers)
            conn.execute(f"CREATE TABLE {q_tbl} ({col_defs})")
            if rows:
                placeholders = ", ".join("?" for _ in headers)
                parsed_rows = [[_infer_val(cell) for cell in r[:len(headers)]] for r in rows if any(c.strip() for c in r)]
                conn.executemany(f"INSERT INTO {q_tbl} VALUES ({placeholders})", parsed_rows)
                total_rows += len(parsed_rows)
            migrated_tables += 1

        # Migrate Schedules/*.csv round-robin templates
        conn.execute(
            "CREATE TABLE IF NOT EXISTS round_robin_templates ("
            "num_teams INTEGER PRIMARY KEY, filename TEXT, weeks_count INTEGER, raw_csv TEXT)"
        )
        templates_loaded = 0
        if schedules_dir and schedules_dir.is_dir():
            for csv_file in sorted(schedules_dir.glob("*team.csv")):
                m = re.match(r"^(\d+)team\.csv$", csv_file.name, re.IGNORECASE)
                if not m:
                    continue
                n_teams = int(m.group(1))
                raw_txt = csv_file.read_text(encoding="latin-1", errors="replace")
                lines = [ln for ln in raw_txt.splitlines() if ln.strip()]
                conn.execute(
                    "INSERT OR REPLACE INTO round_robin_templates(num_teams, filename, weeks_count, raw_csv) VALUES (?,?,?,?)",
                    (n_teams, csv_file.name, len(lines), raw_txt),
                )
                templates_loaded += 1

    conn.close()
    return {
        "migrated_tables": migrated_tables,
        "total_rows": total_rows,
        "templates_loaded": templates_loaded,
        "tables": tables,
    }
