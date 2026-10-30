"""Tests for Golf League Secretary (GLS9) Clean-Room Modern Web Studio."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_gls9_full_migration_and_api(tmp_path: Path):
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

    # 3. Standings for League 10 (18-Hole, 4-Person Team League)
    r = client.get("/api/leagues/10/standings")
    assert r.status_code == 200
    st = r.json()
    assert len(st["teams"]) == 4
    assert len(st["players"]) == 17
    assert st["course"]["CourseName"] == "Mundy Meadows Golf Course"

    # 4. Week 1 Scorecard & Skins
    r = client.get("/api/leagues/10/week/1")
    assert r.status_code == 200
    sc = r.json()
    assert sc["num_holes"] == 18
    assert len(sc["scorecards"]) == 17
    assert any(c["Gross"] > 0 for c in sc["scorecards"])

    # 5. Save Hole-by-Hole Score for Player #1 on Week 1
    holes = [4, 4, 3, 5, 4, 4, 3, 4, 5, 4, 4, 3, 5, 4, 4, 3, 4, 5]
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
    assert p1["NumPutts"] == 31

    # 6. Recalculate Handicaps
    r = client.post("/api/leagues/10/recalculate-handicaps")
    assert r.status_code == 200
    assert r.json()["updated_players"] > 0

    # 7. Generate Round-Robin Schedule from GLS9 templates
    r = client.post("/api/leagues/10/schedule/generate", json={"weeks": 12, "start_date": "2026-05-05"})
    assert r.status_code == 200
    assert r.json()["generated_weeks"] == 12

    # 8. Courses & Raw .mdb Tables Explorer
    r = client.get("/api/courses")
    assert r.status_code == 200
    assert len(r.json()["courses"]) == 4

    r = client.get("/api/tables")
    assert r.status_code == 200
    assert r.json()["table_count"] >= 60

    r = client.get("/api/tables/10Teams")
    assert r.status_code == 200
    assert r.json()["row_count"] == 4

    # 9. Frontend SPA served
    r = client.get("/")
    assert r.status_code == 200
    assert "Golf League Secretary" in r.text
