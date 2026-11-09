import shutil
import sqlite3
import subprocess
from contextlib import closing

import pytest

from app.mdb_migrator import (
    _clean_ident,
    _infer_val,
    _safe_ident,
    _unique_columns,
    migrate_mdb_to_sqlite,
)


def test_clean_ident():
    assert _clean_ident("Pts-1") == "Pts1"
    assert _clean_ident("Hello World!") == "HelloWorld"
    assert _clean_ident(None) == ""


def test_safe_ident():
    assert _safe_ident("Pts-1") == '"Pts1"'


def test_unique_columns():
    headers = ["Pts-1", "Pts 1", "!", ""]
    assert _unique_columns(headers) == ["Pts1", "Pts1_2", "col3", "col4"]


def test_infer_val_empty():
    assert _infer_val(None) is None
    assert _infer_val("") is None


def test_infer_val_int():
    assert _infer_val("123") == 123
    assert _infer_val("-456") == -456


def test_infer_val_float():
    assert _infer_val("123.45") == 123.45
    assert _infer_val("-123.45") == -123.45


def test_infer_val_string():
    assert _infer_val("hello") == "hello"
    assert _infer_val("123hello") == "123hello"


def test_infer_val_int_error(monkeypatch):
    import re
    original_fullmatch = re.fullmatch

    def mock_fullmatch(pattern, string):
        if pattern == r"-?\d+" and string == "hello_int":
            class MockMatch:
                pass
            return MockMatch()
        return original_fullmatch(pattern, string)

    monkeypatch.setattr(re, "fullmatch", mock_fullmatch)

    assert _infer_val("hello_int") == "hello_int"


def test_infer_val_float_error(monkeypatch):
    import re
    original_fullmatch = re.fullmatch

    def mock_fullmatch(pattern, string):
        if pattern == r"-?\d+\.\d+" and string == "hello":
            class MockMatch:
                pass
            return MockMatch()
        return original_fullmatch(pattern, string)

    monkeypatch.setattr(re, "fullmatch", mock_fullmatch)

    assert _infer_val("hello") == "hello"


def test_migrate_mdb_to_sqlite_success(tmp_path, monkeypatch):
    mdb_path = tmp_path / "test.mdb"
    mdb_path.touch()
    sqlite_path = tmp_path / "out.db"
    schedules_dir = tmp_path / "Schedules"
    schedules_dir.mkdir()
    (schedules_dir / "4team.csv").write_text("T1,T2\nT3,T4\n", encoding="latin-1")
    (schedules_dir / "not_a_csv.txt").write_text("ignore me")
    # This matches the regex, but isn't parsed
    (schedules_dir / "Xteam.csv").write_text("ignore me")

    def mock_run(args, **kwargs):
        class CompletedProcess:
            def __init__(self, stdout):
                self.stdout = stdout

        cmd = args[0]
        if "mdb-tables" in cmd:
            return CompletedProcess(stdout="Table1\nTable2\n  \n")
        elif "mdb-export" in cmd:
            tbl = args[-1]
            if tbl == "Table1":
                return CompletedProcess(stdout="Col1,Col2\nVal1,123\nVal2,45.6\nVal3,\n")
            elif tbl == "Table2":
                # Test duplicate columns and empty table
                return CompletedProcess(stdout="ID,ID\n1,2\n")
        return CompletedProcess(stdout="")

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(shutil, "which", lambda x: f"/mock/bin/{x}")

    res = migrate_mdb_to_sqlite(mdb_path, sqlite_path, schedules_dir)

    assert res["migrated_tables"] == 2
    assert res["total_rows"] == 4
    assert res["templates_loaded"] == 1
    assert res["tables"] == ["Table1", "Table2"]

    with closing(sqlite3.connect(str(sqlite_path))) as conn:
        conn.row_factory = sqlite3.Row
        t1 = conn.execute("SELECT * FROM Table1").fetchall()
        assert len(t1) == 3
        assert t1[0]["Col1"] == "Val1"
        assert t1[0]["Col2"] == 123
        assert t1[1]["Col2"] == 45.6
        assert t1[2]["Col2"] is None

        t2 = conn.execute("SELECT * FROM Table2").fetchall()
        assert len(t2) == 1
        assert t2[0]["ID"] == 1
        assert t2[0]["ID_2"] == 2

        rr = conn.execute("SELECT * FROM round_robin_templates").fetchall()
        assert len(rr) == 1
        assert rr[0]["num_teams"] == 4
        assert rr[0]["weeks_count"] == 2


def test_migrate_mdb_to_sqlite_cleanup_on_error(tmp_path, monkeypatch):
    mdb_path = tmp_path / "test.mdb"
    mdb_path.touch()
    sqlite_path = tmp_path / "out.db"

    def mock_run(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(shutil, "which", lambda x: f"/mock/bin/{x}")

    with pytest.raises(subprocess.CalledProcessError):
        migrate_mdb_to_sqlite(mdb_path, sqlite_path)

    assert not sqlite_path.exists()
    # Ensure scratch DB files are cleaned up
    scratch_files = list(tmp_path.glob(".gls9-migrate-*"))
    assert not scratch_files


def test_migrate_mdb_to_sqlite_edge_cases(tmp_path, monkeypatch):
    mdb_path = tmp_path / "test.mdb"
    mdb_path.touch()
    sqlite_path = tmp_path / "out.db"
    schedules_dir = tmp_path / "Schedules"
    schedules_dir.mkdir()
    (schedules_dir / "not_matching.csv").write_text("T1,T2\nT3,T4\n", encoding="latin-1")

    def mock_run(args, **kwargs):
        class CompletedProcess:
            def __init__(self, stdout):
                self.stdout = stdout

        cmd = args[0]
        if "mdb-tables" in cmd:
            return CompletedProcess(stdout="Table1\nTable2\nTable3\n!!\n")
        elif "mdb-export" in cmd:
            tbl = args[-1]
            if tbl == "Table1":
                return CompletedProcess(stdout="")
            elif tbl == "Table2":
                return CompletedProcess(stdout="\n\n")
            elif tbl == "Table3":
                return CompletedProcess(stdout=",,,\n")
            elif tbl == "!!":
                return CompletedProcess(stdout="ID,Name\n1,Test\n")
        return CompletedProcess(stdout="")

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(shutil, "which", lambda x: f"/mock/bin/{x}")

    res = migrate_mdb_to_sqlite(mdb_path, sqlite_path, schedules_dir)

    assert res["migrated_tables"] == 1
    assert res["total_rows"] == 0
    assert res["templates_loaded"] == 0
