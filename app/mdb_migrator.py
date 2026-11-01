"""Migrates GolfSoft GLS9 Microsoft Jet/Access (.mdb) database (all 60 tables) and
Schedules/*.csv round-robin templates into a modern SQLite (WAL) database."""
from __future__ import annotations

import csv
import io
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _clean_ident(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "", name or "")


def _safe_ident(name: str) -> str:
    return f'"{_clean_ident(name)}"'


def _unique_columns(headers: list[str]) -> list[str]:
    """Sanitise column names and make them unique and non-empty.

    Two Access columns that differ only by punctuation (e.g. ``Pts-1`` and ``Pts 1``) or a
    column made only of punctuation would otherwise collapse to a duplicate / empty
    identifier and abort the whole migration with ``duplicate column name``."""
    out: list[str] = []
    seen: set[str] = set()
    for idx, h in enumerate(headers, start=1):
        base = _clean_ident(h.strip()) or f"col{idx}"
        name = base
        n = 2
        while name.lower() in seen:
            name = f"{base}_{n}"
            n += 1
        seen.add(name.lower())
        out.append(name)
    return out


def _infer_val(v: str | None) -> Any:
    if v is None or v == "":
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
    """Migrate into a scratch database first, then copy it over ``sqlite_path`` with the
    SQLite online-backup API. A failure part-way through (corrupt .mdb, mdbtools crash,
    timeout) therefore leaves the live database untouched instead of half-migrated."""
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    fd, scratch = tempfile.mkstemp(prefix=".gls9-migrate-", suffix=".db", dir=str(sqlite_path.parent))
    os.close(fd)
    try:
        res = _migrate_into(mdb_path, Path(scratch), schedules_dir)
        src = sqlite3.connect(scratch)
        dst = sqlite3.connect(str(sqlite_path), timeout=30)
        try:
            dst.execute("PRAGMA journal_mode=WAL")
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        return res
    finally:
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                os.unlink(scratch + suffix)
            except FileNotFoundError:
                pass


def _migrate_into(mdb_path: Path, sqlite_path: Path, schedules_dir: Path | None = None) -> dict[str, Any]:
    mdb_tables_bin = shutil.which("mdb-tables") or "/usr/bin/mdb-tables"
    mdb_export_bin = shutil.which("mdb-export") or "/usr/bin/mdb-export"

    res_t = subprocess.run([mdb_tables_bin, "-1", str(mdb_path)], capture_output=True, text=True, check=True, timeout=30)
    tables = sorted(t.strip() for t in res_t.stdout.splitlines() if t.strip())

    conn = sqlite3.connect(str(sqlite_path))
    migrated_tables = 0
    total_rows = 0

    with conn:
        for tbl in tables:
            res_csv = subprocess.run([mdb_export_bin, str(mdb_path), tbl], capture_output=True, text=True, check=True, timeout=30)
            reader = list(csv.reader(io.StringIO(res_csv.stdout)))
            if not reader:
                continue
            headers = _unique_columns(reader[0])
            if not headers or not _clean_ident(tbl):
                continue
            rows = reader[1:]
            q_tbl = _safe_ident(tbl)
            conn.execute(f"DROP TABLE IF EXISTS {q_tbl}")
            col_defs = ", ".join(f'"{h}" NUMERIC' for h in headers)
            conn.execute(f"CREATE TABLE {q_tbl} ({col_defs})")
            if rows:
                placeholders = ", ".join("?" for _ in headers)
                width = len(headers)
                # Short (ragged) CSV rows are padded with NULLs; extra cells are dropped.
                parsed_rows = [
                    ([_infer_val(cell) for cell in r[:width]] + [None] * max(0, width - len(r)))
                    for r in rows
                    if any(c.strip() for c in r)
                ]
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
