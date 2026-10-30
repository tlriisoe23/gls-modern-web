"""Tests for Golf League Secretary (GLS9) Clean-Room Modern Web Studio V2."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_gls9_full_migration_and_v2_engine(tmp_path: Path):
    db_file = tmp_path / "gls9_test.db"
    mdb_file = Path("/tmp/GLS9/Database/Gls90db.mdb")
    sched_dir = Path("/tmp/GLS9/Schedules")
    app = create_app(db_path=db_file, mdb_seed=mdb_file, schedules_dir=sched_dir)
    client = TestClient(app)

    # 1. Health & migration count
    r = client.get("/api/health")
    assert r.status_code == 200
    h = r.json()
    assert h["status"] == "ok"
    assert h["leagues_count"] == 3
    assert h["courses_count"] == 4
    assert h["sqlite_tables_count"] >= 60
    assert h["round_robin_templates_count"] >= 24

    # 2. Leagues list
    r = client.get("/api/leagues")
    assert r.status_code == 200
    lgs = r.json()["leagues"]
    assert len(lgs) == 3
    lids = {x["LeagueID"] for x in lgs}
    assert lids == {9, 10, 11}

    # 3. Standings & Ground-Truth Rules Summary for League 10 (AGY-F1)
    r = client.get("/api/leagues/10/standings")
    assert r.status_code == 200
    st = r.json()
    assert len(st["teams"]) == 4
    assert len(st["players"]) == 17
    assert st["course"]["CourseName"] == "Mundy Meadows Golf Course"
    rs = st["rules_summary"]
    assert rs["HolePts"] == 1.0
    assert rs["IndMatchPts"] == 2.0
    assert rs["TeamMatchPts"] == 4.0
    assert rs["AdjustScores"] == 2

    # 4. Week 1 Scorecard, ESC, Stableford, Matchups & Skins (AGY-F2, AGY-F3, CDX-F1)
    r = client.get("/api/leagues/10/week/1")
    assert r.status_code == 200
    sc = r.json()
    assert sc["num_holes"] == 18
    assert len(sc["scorecards"]) == 17
    assert len(sc["matchups"]) == 8
    assert any(c["Gross"] > 0 for c in sc["scorecards"])
    assert any("StablefordNet" in c and "AdjGross" in c for c in sc["scorecards"])

    # 5. Save Hole-by-Hole Score with blow-up hole (10 on Par 4) to verify ESC cap & *AdjScores sync (AGY-F3, CDX-F3)
    holes = [10, 4, 3, 5, 4, 4, 3, 4, 5, 4, 4, 3, 5, 4, 4, 3, 4, 5]
    r = client.post(
        "/api/leagues/10/week/1/scores",
        json={
            "PlayerID": 1,
            "holes": holes,
            "NumPutts": 31,
            "GreensInRegulation": 11,
            "IndividualPts": 12.5,
        },
    )
    assert r.status_code == 200
    sc_after = r.json()
    p1 = next(c for c in sc_after["scorecards"] if c["PlayerID"] == 1)
    assert p1["FrontNine"] == sum(holes[:9])
    assert p1["BackNine"] == sum(holes[9:18])
    assert p1["Gross"] == sum(holes)
    assert p1["AdjGross"] < p1["Gross"]
    assert p1["ESC_CappedStrokes"] > 0

    # Verify *AdjScores table received the ESC-capped row
    r_adj = client.get("/api/tables/10AdjScores")
    assert r_adj.status_code == 200
    assert r_adj.json()["row_count"] > 0

    # 6. Auto-Score Head-to-Head Matches (League 10) & Individual Field Points (League 11) (AGY-F2, CDX-F1, CDX-F2)
    r = client.post("/api/leagues/10/week/1/auto-score-matches")
    assert r.status_code == 200
    assert len(r.json()["matchups"]) == 8

    r11 = client.post("/api/leagues/11/week/1/auto-score-matches")
    assert r11.status_code == 200
    assert any(c["FieldPts"] > 0 for c in r11.json()["scorecards"])

    # 7. Printable Clubhouse Report endpoint (AGY-F4)
    r_rep = client.get("/api/leagues/10/week/1/report")
    assert r_rep.status_code == 200
    rep = r_rep.json()
    assert "matchups" in rep and "teams" in rep and "gross_skins" in rep

    # 8. Recalculate Handicaps & Round-Robin Schedule
    r = client.post("/api/leagues/10/recalculate-handicaps")
    assert r.status_code == 200
    assert r.json()["updated_players"] > 0

    r = client.post("/api/leagues/10/schedule/generate", json={"weeks": 12, "start_date": "2026-05-05"})
    assert r.status_code == 200
    assert r.json()["generated_weeks"] == 12

    # 9. Frontend SPA served with V2 Mobile Caddy & Print Clubhouse Sheet
    r = client.get("/")
    assert r.status_code == 200
    assert "Toggle Mobile Caddy Mode" in r.text
    assert "Print Clubhouse Sheet" in r.text
