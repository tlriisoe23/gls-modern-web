import pytest
from pathlib import Path
from app import mdb_migrator

def test_schedules_migration(tmp_path, monkeypatch):
    schedules_dir = tmp_path / "Schedules"
    schedules_dir.mkdir()

    csv_file1 = schedules_dir / "4team.csv"
    csv_file1.write_text("1,2\n3,4\n", encoding="latin-1")

    csv_file2 = schedules_dir / "invalid.csv"
    csv_file2.write_text("invalid", encoding="latin-1")

    csv_file3 = schedules_dir / "10team.txt"
    csv_file3.write_text("text", encoding="latin-1")

    def mock_run(*args, **kwargs):
        class MockProcess:
            returncode = 0
            stdout = ""
        return MockProcess()

    monkeypatch.setattr(mdb_migrator.subprocess, "run", mock_run)
    monkeypatch.setattr(mdb_migrator.shutil, "which", lambda x: "/bin/mocked")

    mdb_path = tmp_path / "test.mdb"
    sqlite_path = tmp_path / "test.sqlite"

    result = mdb_migrator._migrate_into(mdb_path, sqlite_path, schedules_dir)

    assert result["templates_loaded"] == 1

    import sqlite3
    with sqlite3.connect(sqlite_path) as conn:
        rows = conn.execute("SELECT * FROM round_robin_templates").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 4
        assert rows[0][1] == "4team.csv"
        assert rows[0][2] == 2
        assert rows[0][3] == "1,2\n3,4\n"

def test_schedules_migration_invalid_regex(tmp_path, monkeypatch):
    schedules_dir = tmp_path / "Schedules"
    schedules_dir.mkdir()

    csv_file = schedules_dir / "abc_team.csv"
    csv_file.write_text("1,2\n", encoding="latin-1")

    def mock_run(*args, **kwargs):
        class MockProcess:
            returncode = 0
            stdout = ""
        return MockProcess()

    monkeypatch.setattr(mdb_migrator.subprocess, "run", mock_run)
    monkeypatch.setattr(mdb_migrator.shutil, "which", lambda x: "/bin/mocked")

    mdb_path = tmp_path / "test.mdb"
    sqlite_path = tmp_path / "test.sqlite"

    result = mdb_migrator._migrate_into(mdb_path, sqlite_path, schedules_dir)
    assert result["templates_loaded"] == 0

def test_migrate_into_empty_tables(tmp_path, monkeypatch):
    mdb_path = tmp_path / "test.mdb"
    sqlite_path = tmp_path / "test.sqlite"

    def mock_run(*args, **kwargs):
        class MockProcess:
            returncode = 0
            if "mdb-tables" in args[0]:
                stdout = "tbl1\ntbl2\ntbl3\n"
            else:
                if "tbl1" in args[0]:
                    stdout = ""  # empty table, no reader -> covers line 100
                elif "tbl2" in args[0]:
                    stdout = "\n" # empty row -> reader is [[]], reader[0] is [], _unique_columns returns [] -> covers line 103
                elif "tbl3" in args[0]:
                    stdout = "h1,h1\n1,2" # valid headers, but invalid tblname
                else:
                    stdout = ""
        return MockProcess()

    monkeypatch.setattr(mdb_migrator.subprocess, "run", mock_run)
    monkeypatch.setattr(mdb_migrator.shutil, "which", lambda x: "/bin/mocked")
    monkeypatch.setattr(mdb_migrator, "_clean_ident", lambda x: "" if x == "tbl3" else x)

    result = mdb_migrator._migrate_into(mdb_path, sqlite_path, None)
    assert result["migrated_tables"] == 0

def test_infer_val_value_errors(monkeypatch):
    import re
    class MockMatch:
        pass

    orig_fullmatch = re.fullmatch

    def mock_fullmatch(pattern, string, flags=0):
        if string == "12a" and pattern == r"-?\d+":
            return MockMatch()
        if string == "1.2.3" and pattern == r"-?\d+\.\d+":
            return MockMatch()
        return orig_fullmatch(pattern, string, flags)

    monkeypatch.setattr(mdb_migrator.re, "fullmatch", mock_fullmatch)

    assert mdb_migrator._infer_val("12a") == "12a"
    assert mdb_migrator._infer_val("1.2.3") == "1.2.3"
