"""API input validation, error handling and security-header tests."""
from __future__ import annotations

import sqlite3

import pytest

from app import main as main_mod
from tests.conftest import fake_mdb_bytes

HOLES_18 = [4] * 18


# ---------------------------------------------------------------------------
# Unknown league / out-of-range path parameters
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/leagues/999/standings", None),
        ("get", "/api/leagues/999/week/1", None),
        ("get", "/api/leagues/999/week/1/report", None),
        ("post", "/api/leagues/999/week/1/scores", {"PlayerID": 1, "holes": HOLES_18}),
        ("post", "/api/leagues/999/week/1/auto-score-matches", None),
        ("post", "/api/leagues/999/recalculate-handicaps", None),
        ("get", "/api/leagues/999/schedule", None),
        ("post", "/api/leagues/999/schedule/generate", {"weeks": 4}),
        ("post", "/api/leagues/999/players", {"PlayerFirst": "A", "PlayerLast": "B"}),
    ],
)
def test_unknown_league_is_404_everywhere(client, method, path, body):
    r = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
    assert r.status_code == 404, r.text
    assert "999" in r.json()["detail"]


@pytest.mark.parametrize("path", ["/api/leagues/0/standings", "/api/leagues/-1/standings", "/api/leagues/abc/standings"])
def test_bad_league_id_is_422(client, path):
    assert client.get(path).status_code == 422


@pytest.mark.parametrize("week", [0, -1, 53, 10_000])
def test_out_of_range_week_is_422(client, week):
    assert client.get(f"/api/leagues/10/week/{week}").status_code == 422
    assert client.post(f"/api/leagues/10/week/{week}/scores", json={"PlayerID": 1, "holes": HOLES_18}).status_code == 422


# ---------------------------------------------------------------------------
# Score entry validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [
        {"PlayerID": 1, "holes": [-1] + [4] * 17},
        {"PlayerID": 1, "holes": [21] + [4] * 17},
        {"PlayerID": 1, "holes": [4] * 19},
        {"PlayerID": 1, "holes": ["four"] * 18},
        {"PlayerID": 0, "holes": HOLES_18},
        {"PlayerID": 1, "holes": HOLES_18, "NumPutts": -1},
        {"PlayerID": 1, "holes": HOLES_18, "GreensInRegulation": 19},
        {"PlayerID": 1, "holes": HOLES_18, "IndividualPts": 1e9},
        {"holes": HOLES_18},
    ],
)
def test_invalid_score_payloads_rejected(client, payload):
    r = client.post("/api/leagues/10/week/1/scores", json=payload)
    assert r.status_code == 422, r.text


def test_nan_individual_points_rejected(client):
    r = client.post(
        "/api/leagues/10/week/1/scores",
        content=b'{"PlayerID": 1, "holes": [4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4], "IndividualPts": NaN}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422


def test_score_for_player_not_in_league_is_404_and_writes_nothing(client, db_path):
    before = sqlite3.connect(db_path).execute('SELECT COUNT(*) FROM "10PlayerResults"').fetchone()[0]
    r = client.post("/api/leagues/10/week/1/scores", json={"PlayerID": 9999, "holes": HOLES_18})
    assert r.status_code == 404
    after = sqlite3.connect(db_path).execute('SELECT COUNT(*) FROM "10PlayerResults"').fetchone()[0]
    assert before == after


def test_partial_hole_list_is_padded(client):
    r = client.post("/api/leagues/10/week/3/scores", json={"PlayerID": 2, "holes": [5, 4, 3]})
    assert r.status_code == 200
    card = next(c for c in r.json()["scorecards"] if c["PlayerID"] == 2)
    assert card["holes"][:3] == [5, 4, 3]
    assert card["Gross"] == 12


# ---------------------------------------------------------------------------
# Player upsert validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "patch",
    [
        {"PlayerFirst": ""},
        {"PlayerFirst": "   "},
        {"PlayerFirst": "x" * 41},
        {"PlayerLast": "Bad\x00Name"},
        {"PlayerLast": "Line\nBreak"},
        {"EMail": "not-an-email"},
        {"EMail": "a@b.c<script>"},
        {"HomePhone": "<script>alert(1)</script>"},
        {"Handicap": 99},
        {"Handicap": -11},
        {"TeamID": 0},
        {"PlayerID": -5},
    ],
)
def test_invalid_player_payloads_rejected(client, patch):
    payload = {"PlayerFirst": "Ann", "PlayerLast": "Lee", "TeamID": 1, "Handicap": 5} | patch
    r = client.post("/api/leagues/10/players", json=payload)
    assert r.status_code == 422, r.text


def test_player_team_must_exist_in_team_league(client):
    r = client.post("/api/leagues/10/players", json={"PlayerFirst": "Ann", "PlayerLast": "Lee", "TeamID": 77})
    assert r.status_code == 422
    assert "Team 77" in r.json()["detail"]


def test_individual_league_accepts_any_team_number(client):
    # League 11 is an individual (no *Teams rows) league.
    r = client.post("/api/leagues/11/players", json={"PlayerFirst": "Ann", "PlayerLast": "Lee", "TeamID": 15})
    assert r.status_code == 200


def test_update_of_missing_player_is_404(client):
    r = client.post("/api/leagues/10/players", json={"PlayerID": 4242, "PlayerFirst": "A", "PlayerLast": "B"})
    assert r.status_code == 404


def test_player_names_are_trimmed_and_stored_verbatim(client):
    r = client.post(
        "/api/leagues/10/players",
        json={"PlayerFirst": "  Seán ", "PlayerLast": "O'Brien & Sons", "TeamID": 2, "EMail": "sean@example.ie", "HomePhone": "+1 (555) 010-2030"},
    )
    assert r.status_code == 200
    p = next(p for p in r.json()["players"] if p["PlayerLast"] == "O'Brien & Sons")
    assert p["PlayerFirst"] == "Seán"


def test_xss_payload_is_stored_as_inert_data(client):
    evil = '<img src=x onerror="alert(1)">'
    r = client.post("/api/leagues/10/players", json={"PlayerFirst": evil, "PlayerLast": "Hacker", "TeamID": 1})
    assert r.status_code == 200
    assert any(p["PlayerFirst"] == evil for p in r.json()["players"])
    # JSON responses are never sniffed/rendered as HTML.
    r = client.get("/api/leagues/10/standings")
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_sql_injection_in_player_name_is_harmless(client, db_path):
    name = "Robert'); DROP TABLE \"10Players\";--"
    r = client.post("/api/leagues/10/players", json={"PlayerFirst": name, "PlayerLast": "Tables", "TeamID": 1})
    assert r.status_code == 200
    conn = sqlite3.connect(db_path)
    assert conn.execute('SELECT COUNT(*) FROM "10Players" WHERE "PlayerFirst"=?', (name,)).fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Schedule generation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "body",
    [{"weeks": 0}, {"weeks": 53}, {"weeks": 10**9}, {"weeks": 4, "start_date": "05/05/2026"}, {"weeks": 4, "start_date": "2026-02-30"}],
)
def test_schedule_generate_validation(client, db_path, body):
    before = sqlite3.connect(db_path).execute('SELECT COUNT(*) FROM "10Schedule"').fetchone()[0]
    r = client.post("/api/leagues/10/schedule/generate", json=body)
    assert r.status_code == 422
    after = sqlite3.connect(db_path).execute('SELECT COUNT(*) FROM "10Schedule"').fetchone()[0]
    assert before == after, "a rejected request must not wipe the schedule"


def test_schedule_generate_ok(client):
    r = client.post("/api/leagues/10/schedule/generate", json={"weeks": 52, "start_date": "2026-04-07"})
    assert r.status_code == 200
    sched = r.json()["schedule"]
    assert len(sched) == 52
    assert sched[0]["Date"].startswith("04/07/26")


# ---------------------------------------------------------------------------
# Raw table explorer
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name",
    ['Leagues"--', "Leagues;DROP", "sqlite_master%00", "..%2F..%2Fetc%2Fpasswd", "x" * 200, 'Lea"gues'],
)
def test_table_explorer_rejects_non_identifiers(client, name):
    assert client.get(f"/api/tables/{name}").status_code == 404


def test_table_explorer_unknown_table(client):
    assert client.get("/api/tables/NoSuchTable").status_code == 404


def test_table_explorer_limits_rows(client):
    r = client.get("/api/tables/round_robin_templates")
    assert r.status_code == 200
    assert r.json()["row_count"] <= 200


# ---------------------------------------------------------------------------
# .mdb import
# ---------------------------------------------------------------------------
def test_import_rejects_empty_file(client):
    r = client.post("/api/import/mdb", files={"file": ("x.mdb", b"", "application/octet-stream")})
    assert r.status_code == 400


def test_import_rejects_non_access_file(client):
    r = client.post("/api/import/mdb", files={"file": ("evil.mdb", b"<html><script>alert(1)</script>" * 10, "application/octet-stream")})
    assert r.status_code == 400
    assert "Access" in r.json()["detail"]


def test_import_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr(main_mod, "MAX_MDB_UPLOAD_BYTES", 1024)
    r = client.post("/api/import/mdb", files={"file": ("big.mdb", fake_mdb_bytes() * 4, "application/octet-stream")})
    assert r.status_code == 413


def test_import_without_mdbtools_is_503(client, monkeypatch):
    monkeypatch.setattr(main_mod.mdb_migrator.shutil, "which", lambda _: None)
    monkeypatch.setenv("PATH", "/nonexistent")
    r = client.post("/api/import/mdb", files={"file": ("x.mdb", fake_mdb_bytes(), "application/octet-stream")})
    assert r.status_code in (400, 503)


def test_import_success_with_fake_mdbtools(client, fake_mdbtools):
    fake_mdbtools({"Leagues": "LeagueID,LeagueName,CourseID\n1,Imported League,1\n", "Courses": "CourseID,CourseName\n1,New Course\n"})
    r = client.post("/api/import/mdb", files={"file": ("x.mdb", fake_mdb_bytes(), "application/octet-stream")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["migrated_tables"] == 2
    lg = client.get("/api/leagues").json()["leagues"]
    assert [x["LeagueName"] for x in lg] == ["Imported League"]


def test_failed_import_leaves_live_db_untouched(client, fake_mdbtools, db_path):
    fake_mdbtools({"Leagues": "LeagueID,LeagueName\n1,Half\n", "Zebra": "a\n1\n"}, fail_on="Zebra")
    r = client.post("/api/import/mdb", files={"file": ("x.mdb", fake_mdb_bytes(), "application/octet-stream")})
    assert r.status_code == 400
    # Original 3 sample leagues are still there - no half-migrated state.
    assert client.get("/api/health").json()["leagues_count"] == 3
    leftovers = [p.name for p in db_path.parent.iterdir() if p.name.startswith(".gls9-migrate-")]
    assert leftovers == []


# ---------------------------------------------------------------------------
# Security headers & error hygiene
# ---------------------------------------------------------------------------
def test_security_headers_on_spa_and_api(client):
    for path in ("/", "/api/health"):
        r = client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "no-referrer"
        csp = r.headers["content-security-policy"]
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "object-src 'none'" in csp
    assert client.get("/api/health").headers["cache-control"] == "no-store"


def test_docs_not_broken_by_csp(client):
    r = client.get("/docs")
    assert r.status_code == 200
    assert "content-security-policy" not in r.headers


def test_database_errors_do_not_leak_sql(client, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute('DROP TABLE "10AdjScores"')
    conn.execute('ALTER TABLE "10PlayerResults" RENAME COLUMN "FrontNine" TO "Front9"')
    conn.commit()
    conn.close()
    r = client.post("/api/leagues/10/week/1/scores", json={"PlayerID": 1, "holes": HOLES_18})
    assert r.status_code == 500
    assert r.json() == {"detail": "Database error"}


def test_connections_are_closed_after_each_request(client, monkeypatch):
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        closed_flag = False

        def close(self):
            self.closed_flag = True
            super().close()

    def tracking_connect(*a, **kw):
        c = real_connect(*a, factory=TrackedConnection, **kw)
        opened.append(c)
        return c

    monkeypatch.setattr(main_mod.sqlite3, "connect", tracking_connect)
    for path in ("/api/health", "/api/leagues", "/api/leagues/10/standings", "/api/tables", "/api/leagues/999/standings"):
        client.get(path)
    client.post("/api/leagues/10/week/1/scores", json={"PlayerID": 9999, "holes": HOLES_18})  # error path
    assert opened, "expected the app to open connections"
    assert all(c.closed_flag for c in opened), f"{sum(not c.closed_flag for c in opened)} connection(s) leaked"


def test_corrupt_league_id_rows_are_skipped(client, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute('INSERT INTO "Leagues" ("LeagueID", "LeagueName") VALUES (?, ?)', ('1" OR 1=1 --', "Evil"))
    conn.commit()
    conn.close()
    r = client.get("/api/leagues")
    assert r.status_code == 200
    assert {x["LeagueID"] for x in r.json()["leagues"]} == {9, 10, 11}

def test_mdb_migrator_closes_connection_on_subprocess_error(monkeypatch, db_path):
    from app import mdb_migrator
    from pathlib import Path
    import subprocess
    import tempfile

    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        closed_flag = False
        def close(self):
            self.closed_flag = True
            super().close()

    def tracking_connect(*a, **kw):
        c = real_connect(*a, factory=TrackedConnection, **kw)
        opened.append(c)
        return c

    monkeypatch.setattr(mdb_migrator.sqlite3, "connect", tracking_connect)

    def fake_run(args, **kwargs):
        if "mdb-export" in args[0]:
            raise subprocess.CalledProcessError(1, args)
        class FakeCompletedProcess:
            stdout = "Table1\nTable2\n"
        return FakeCompletedProcess()

    monkeypatch.setattr(mdb_migrator.subprocess, "run", fake_run)
    monkeypatch.setattr(mdb_migrator.shutil, "which", lambda x: f"/fake/bin/{x}")

    import pytest
    with tempfile.NamedTemporaryFile(suffix=".db") as tf:
        with pytest.raises(subprocess.CalledProcessError):
            mdb_migrator._migrate_into(Path("/fake/path.mdb"), Path(tf.name), None)

    assert opened, "expected _migrate_into to open a connection"
    assert all(c.closed_flag for c in opened), "connection was leaked on subprocess error"
