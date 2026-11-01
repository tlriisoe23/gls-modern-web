"""Shared fixtures.

Every test runs against a *throwaway copy* of the bundled sample database
(``data/gls9.db``) so the suite is hermetic: it never mutates the checked-in DB and
does not depend on the external ``/tmp/GLS9`` GolfSoft install.
"""
from __future__ import annotations

import os
import shutil
import stat
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import create_app  # noqa: E402

SAMPLE_DB = ROOT / "data" / "gls9.db"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    if not SAMPLE_DB.exists():
        pytest.skip("bundled sample database data/gls9.db is missing")
    dst = tmp_path / "gls9_test.db"
    shutil.copyfile(SAMPLE_DB, dst)
    return dst


@pytest.fixture()
def app(db_path: Path, tmp_path: Path):
    return create_app(db_path=db_path, mdb_seed=tmp_path / "absent.mdb", schedules_dir=tmp_path / "no-schedules")


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def fake_mdbtools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Install fake ``mdb-tables`` / ``mdb-export`` executables on PATH.

    Returns a function ``define(tables: dict[str, str], fail_on: str | None = None)``
    where ``tables`` maps table name -> CSV text that ``mdb-export`` will print.
    """
    bin_dir = tmp_path / "fakebin"
    data_dir = tmp_path / "fakemdb"
    bin_dir.mkdir()
    data_dir.mkdir()

    py = sys.executable
    tables_script = textwrap.dedent(
        f"""\
        #!{py}
        import pathlib, sys
        d = pathlib.Path({str(data_dir)!r})
        print("\\n".join(sorted(p.stem for p in d.glob("*.csv"))))
        """
    )
    export_script = textwrap.dedent(
        f"""\
        #!{py}
        import pathlib, sys
        d = pathlib.Path({str(data_dir)!r})
        tbl = sys.argv[2]
        if (d / "FAIL").exists() and (d / "FAIL").read_text().strip() == tbl:
            sys.stderr.write("simulated mdbtools crash\\n")
            sys.exit(3)
        sys.stdout.write((d / (tbl + ".csv")).read_text())
        """
    )
    for name, body in (("mdb-tables", tables_script), ("mdb-export", export_script)):
        p = bin_dir / name
        p.write_text(body)
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    def define(tables: dict[str, str], fail_on: str | None = None) -> Path:
        for old in data_dir.glob("*"):
            old.unlink()
        for name, csv_text in tables.items():
            (data_dir / f"{name}.csv").write_text(csv_text)
        if fail_on:
            (data_dir / "FAIL").write_text(fail_on)
        return data_dir

    return define


def fake_mdb_bytes() -> bytes:
    """Minimal bytes carrying the Jet 3/4 file signature at offset 4."""
    return b"\x00\x01\x00\x00Standard Jet DB\x00" + b"\x00" * 2048
