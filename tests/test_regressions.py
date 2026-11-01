"""Regression tests for edge-case bugs found in the FSA-15 audit (one test per bug)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import golf_engine as ge
from app import mdb_migrator


# ---------------------------------------------------------------------------
# BUG: 9-hole leagues allocated handicap strokes with a broken rank mapping
# (ranks 7/13 and 9/17 collided, ranks 2/4 never received a stroke).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("lid", [9, 11])
def test_nine_hole_strokes_match_handicap_and_hardest_holes(client, lid):
    sc = client.get(f"/api/leagues/{lid}/week/1").json()
    assert sc["num_holes"] == 9
    ranks = ge.stroke_index_map(sc["holes_meta"])
    checked = 0
    for card in sc["scorecards"]:
        hcp = ge.round_half_up(card["Handicap"])
        if hcp <= 0:
            continue
        strokes = card["strokes_received"]
        assert sum(strokes) == hcp, (card["PlayerName"], card["Handicap"], strokes)
        # Strokes never go to an easier hole while a harder hole gets fewer.
        by_rank = [strokes[ranks.index(r)] for r in range(1, 10)]
        assert by_rank == sorted(by_rank, reverse=True), by_rank
        checked += 1
    assert checked > 0


def test_nine_hole_two_handicap_gets_strokes_on_two_hardest_front_nine_holes():
    # Course 3 front-nine 18-hole ranks: hole 6 = 1, hole 9 = 3 (the two hardest of the nine).
    holes = [{"hole": i + 1, "handicap_rank": r} for i, r in enumerate((5, 9, 17, 7, 13, 1, 11, 15, 3))]
    ranks = ge.stroke_index_map(holes)
    got = [h["hole"] for h, r in zip(holes, ranks) if ge.strokes_on_hole(2, r, 9)]
    assert got == [6, 9]


# ---------------------------------------------------------------------------
# BUG: first score for a new week / player always 500'd (26 placeholders, 28 columns).
# ---------------------------------------------------------------------------
def test_first_score_for_new_week_is_inserted(client, db_path):
    holes = [5, 4, 3, 5, 4, 4, 3, 4, 5, 4, 4, 3, 5, 4, 4, 3, 4, 5]
    r = client.post("/api/leagues/10/week/6/scores", json={"PlayerID": 3, "holes": holes, "NumPutts": 30})
    assert r.status_code == 200, r.text
    card = next(c for c in r.json()["scorecards"] if c["PlayerID"] == 3)
    assert card["Gross"] == sum(holes)
    row = sqlite3.connect(db_path).execute(
        'SELECT "FrontNine","BackNine","NumPutts","Sub","Forfeit" FROM "10PlayerResults" WHERE "WeekNum"=6 AND "PlayerID"=3'
    ).fetchone()
    assert row == (sum(holes[:9]), sum(holes[9:]), 30, 0, 0)


# ---------------------------------------------------------------------------
# BUG: a 9-hole league persisted back-nine strokes that the UI never shows.
# ---------------------------------------------------------------------------
def test_nine_hole_league_discards_back_nine_scores(client, db_path):
    pid = client.get("/api/leagues/11/standings").json()["players"][0]["PlayerID"]
    r = client.post("/api/leagues/11/week/5/scores", json={"PlayerID": pid, "holes": [4] * 9 + [9] * 9})
    assert r.status_code == 200, r.text
    row = sqlite3.connect(db_path).execute(
        'SELECT "FrontNine","BackNine","10","18" FROM "11PlayerResults" WHERE "WeekNum"=5 AND "PlayerID"=?', (pid,)
    ).fetchone()
    assert row == (36, 0, 0, 0)


# ---------------------------------------------------------------------------
# BUG: season Points were never reset when a player's weekly points dropped to 0.
# ---------------------------------------------------------------------------
def test_season_points_reset_when_score_cleared(client):
    r = client.post("/api/leagues/10/players", json={"PlayerFirst": "Reset", "PlayerLast": "Check", "TeamID": 1, "Handicap": 5})
    pid = next(p["PlayerID"] for p in r.json()["players"] if p["PlayerFirst"] == "Reset")

    client.post("/api/leagues/10/week/7/scores", json={"PlayerID": pid, "holes": [4] * 18, "IndividualPts": 7})
    pts = lambda: next(p["Points"] for p in client.get("/api/leagues/10/standings").json()["players"] if p["PlayerID"] == pid)
    assert pts() == 7

    client.post("/api/leagues/10/week/7/scores", json={"PlayerID": pid, "holes": [0] * 18, "IndividualPts": 0})
    assert pts() == 0


# ---------------------------------------------------------------------------
# BUG: net Stableford gave 0 points for a net score <= 0 (should be best possible).
# ---------------------------------------------------------------------------
def test_net_stableford_counts_net_zero_holes(client):
    sc = client.get("/api/leagues/10/standings").json()
    hcp_player = max(sc["players"], key=lambda p: p.get("Handicap") or 0)
    pid = hcp_player["PlayerID"]
    assert ge.round_half_up(hcp_player["Handicap"]) >= 1

    week = client.get("/api/leagues/10/week/8").json()
    meta = week["holes_meta"]
    ranks = ge.stroke_index_map(meta)
    hardest = ranks.index(1)
    holes = [0] * 18
    holes[hardest] = 1  # ace on the hardest hole -> net 0 or lower
    r = client.post("/api/leagues/10/week/8/scores", json={"PlayerID": pid, "holes": holes})
    card = next(c for c in r.json()["scorecards"] if c["PlayerID"] == pid)
    assert card["net_holes"][hardest] <= 0
    assert card["StablefordNet"] >= 4


# ---------------------------------------------------------------------------
# BUG: Net score used banker's rounding (handicap 10.5 played off 10).
# ---------------------------------------------------------------------------
def test_net_uses_half_up_rounding(client, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute('UPDATE "10Players" SET "Handicap"=10.5 WHERE "PlayerID"=4')
    conn.commit()
    conn.close()
    r = client.post("/api/leagues/10/week/9/scores", json={"PlayerID": 4, "holes": [5] * 18})
    card = next(c for c in r.json()["scorecards"] if c["PlayerID"] == 4)
    assert card["Net"] == 90 - 11
    assert sum(card["strokes_received"]) == 11


# ---------------------------------------------------------------------------
# BUG: weird legacy cell values (text in score columns) crashed the scorecard.
# ---------------------------------------------------------------------------
def test_scorecard_tolerates_junk_cells(client, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute('UPDATE "10PlayerResults" SET "1"=\'N/A\', "NumPutts"=\'?\' WHERE "WeekNum"=1 AND "PlayerID"=1')
    conn.commit()
    conn.close()
    r = client.get("/api/leagues/10/week/1")
    assert r.status_code == 200
    card = next(c for c in r.json()["scorecards"] if c["PlayerID"] == 1)
    assert card["holes"][0] == 0 and card["NumPutts"] == 0


def test_recalculate_handicaps_tolerates_junk_cells(client, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute('UPDATE "10AdjScores" SET "ID1"=\'abc\' WHERE "WeekNum"=1')
    conn.commit()
    conn.close()
    assert client.post("/api/leagues/10/recalculate-handicaps").status_code == 200


def test_recalculated_handicaps_are_within_league_bounds(client):
    out = client.post("/api/leagues/10/recalculate-handicaps").json()
    max_hcp = client.get("/api/leagues/10/standings").json()["rules_summary"]["MaximumHandicap"]
    for u in out["updates"]:
        assert 0 <= u["new_handicap"] <= max_hcp


# ---------------------------------------------------------------------------
# Auto-scoring is idempotent (re-running does not double-count).
# ---------------------------------------------------------------------------
def test_auto_score_is_idempotent(client):
    a = client.post("/api/leagues/10/week/1/auto-score-matches").json()
    st1 = client.get("/api/leagues/10/standings").json()
    b = client.post("/api/leagues/10/week/1/auto-score-matches").json()
    st2 = client.get("/api/leagues/10/standings").json()
    assert a["matchups"] == b["matchups"]
    assert [p["Points"] for p in st1["players"]] == [p["Points"] for p in st2["players"]]
    assert [t["Points"] for t in st1["teams"]] == [t["Points"] for t in st2["teams"]]


def test_match_points_conserved_per_match(client):
    sc = client.post("/api/leagues/10/week/1/auto-score-matches").json()
    rs = sc["rules_summary"]
    for m in sc["matchups"]:
        if m["status"] == "Awaiting Scores":
            continue
        played = m["holes_won_a"] + m["holes_won_b"] + m["holes_halved"]
        assert m["computed_pts_a"] + m["computed_pts_b"] == pytest.approx(played * rs["HolePts"] + rs["IndMatchPts"])


def test_skins_require_outright_low_score(client):
    sc = client.get("/api/leagues/10/week/1").json()
    for s in sc["gross_skins"]:
        idx = s["hole"] - 1
        scores = [c["holes"][idx] for c in sc["scorecards"] if c["holes"][idx] > 0]
        assert scores.count(s["score"]) == 1 and s["score"] == min(scores)


# ---------------------------------------------------------------------------
# BUG: migrator aborted on duplicate/empty sanitised column names and ragged rows.
# ---------------------------------------------------------------------------
def test_migrator_handles_duplicate_empty_headers_and_ragged_rows(fake_mdbtools, tmp_path: Path):
    fake_mdbtools(
        {
            "Weird": 'Pts-1,Pts 1,!!!,Name\n1,2,3,"Ann"\n4,5\n\n7,8,9,"Bob",EXTRA\n',
            "Leagues": "LeagueID,LeagueName\n1,One\n",
        }
    )
    target = tmp_path / "out.db"
    res = mdb_migrator.migrate_mdb_to_sqlite(tmp_path / "x.mdb", target)
    assert res["migrated_tables"] == 2
    conn = sqlite3.connect(target)
    cols = [r[1] for r in conn.execute('PRAGMA table_info("Weird")')]
    assert cols == ["Pts1", "Pts1_2", "col3", "Name"]
    rows = conn.execute('SELECT * FROM "Weird"').fetchall()
    assert rows == [(1, 2, 3, "Ann"), (4, 5, None, None), (7, 8, 9, "Bob")]
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_migrator_failure_keeps_existing_target(fake_mdbtools, tmp_path: Path):
    # Table "A" exists in the live DB *and* in the .mdb; the export of "B" then fails.
    # The live copy of "A" must survive (the old code had already dropped/recreated it).
    target = tmp_path / "live.db"
    c = sqlite3.connect(target)
    c.execute('CREATE TABLE "A" (x)')
    c.execute('INSERT INTO "A" VALUES (42)')
    c.commit()
    c.close()
    fake_mdbtools({"A": "y\n1\n", "B": "y\n2\n"}, fail_on="B")
    with pytest.raises(Exception):
        mdb_migrator.migrate_mdb_to_sqlite(tmp_path / "x.mdb", target)
    conn = sqlite3.connect(target)
    assert [r[1] for r in conn.execute('PRAGMA table_info("A")')] == ["x"]
    assert conn.execute('SELECT x FROM "A"').fetchall() == [(42,)]
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".gls9-migrate-")]


@pytest.mark.parametrize("raw,expected", [("", None), (None, None), ("12", 12), ("-3", -3), ("1.50", 1.5), ("12abc", "12abc"), ("1e5", "1e5")])
def test_migrator_value_inference(raw, expected):
    assert mdb_migrator._infer_val(raw) == expected
