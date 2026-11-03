"""Tests for ECGC Historical Data Import, Rules Engine Overhaul & Scoring Simulator."""

import sqlite3
import pytest
from fastapi.testclient import TestClient

from app import golf_engine as ge, match_engine as me
from app.main import create_app


def test_plus_handicap_strokes_on_hole():
    """Plus-handicap golfers (+1 to +10, i.e. negative handicap) give strokes back

    to the course on the easiest holes (highest rank numbers: rank 9, 8, 7...).
    """
    # 9-hole course, ranks 1 (hardest) to 9 (easiest)
    # +1 handicap (-1.0): gives 1 stroke back on rank 9 (easiest hole)
    assert ge.strokes_on_hole(-1.0, 9, 9) == -1
    for r in range(1, 9):
        assert ge.strokes_on_hole(-1.0, r, 9) == 0

    # +2 handicap (-2.0): gives strokes back on rank 8 and rank 9
    assert ge.strokes_on_hole(-2.0, 9, 9) == -1
    assert ge.strokes_on_hole(-2.0, 8, 9) == -1
    for r in range(1, 8):
        assert ge.strokes_on_hole(-2.0, r, 9) == 0

    # +3 handicap (-3.0): gives strokes back on ranks 7, 8, 9
    assert ge.strokes_on_hole(-3.0, 9, 9) == -1
    assert ge.strokes_on_hole(-3.0, 8, 9) == -1
    assert ge.strokes_on_hole(-3.0, 7, 9) == -1
    for r in range(1, 7):
        assert ge.strokes_on_hole(-3.0, r, 9) == 0

    # +10 handicap (-10.0): gives 2 strokes back on rank 9, 1 stroke back on ranks 1-8
    assert ge.strokes_on_hole(-10.0, 9, 9) == -2
    for r in range(1, 9):
        assert ge.strokes_on_hole(-10.0, r, 9) == -1
    total_strokes = sum(ge.strokes_on_hole(-10.0, r, 9) for r in range(1, 10))
    assert total_strokes == -10


def test_plus_handicap_strokes_per_hole():
    """Test match_engine.strokes_per_hole for plus-handicap golfers."""
    ranks = [7, 1, 5, 4, 6, 3, 2, 8, 9]  # ECGC 9-hole ranks

    # Scratch (0.0): 0 strokes on all holes
    assert me.strokes_per_hole(0.0, ranks, 9) == [0] * 9

    # +1 handicap (-1.0): -1 on Hole 9 (rank 9)
    res_plus1 = me.strokes_per_hole(-1.0, ranks, 9)
    assert res_plus1 == [0, 0, 0, 0, 0, 0, 0, 0, -1]
    assert sum(res_plus1) == -1

    # +2 handicap (-2.0): -1 on Hole 8 (rank 8) and Hole 9 (rank 9)
    res_plus2 = me.strokes_per_hole(-2.0, ranks, 9)
    assert res_plus2 == [0, 0, 0, 0, 0, 0, 0, -1, -1]
    assert sum(res_plus2) == -2

    # +3 handicap (-3.0): -1 on Hole 1 (rank 7), Hole 8 (rank 8), Hole 9 (rank 9)
    res_plus3 = me.strokes_per_hole(-3.0, ranks, 9)
    assert res_plus3 == [-1, 0, 0, 0, 0, 0, 0, -1, -1]
    assert sum(res_plus3) == -3

    # Standard positive handicap (12.0): receives strokes on all 9 holes + extra on 3 hardest
    res_pos12 = me.strokes_per_hole(12.0, ranks, 9)
    assert sum(res_pos12) == 12
    # Ranks <= 3 (Holes 2, 7, 6) receive 2 strokes, others receive 1
    assert res_pos12[1] == 2  # Hole 2 (rank 1)
    assert res_pos12[6] == 2  # Hole 7 (rank 2)
    assert res_pos12[5] == 2  # Hole 6 (rank 3)
    assert res_pos12[0] == 1  # Hole 1 (rank 7)


def test_ecgc_pt_bonus_penalty_and_progression():
    """Test per-player Net vs Par bonus/penalty (PT) and weekly handicap progression."""
    # Net <= 35 -> PT = +1.0
    assert me.compute_ecgc_pt(33) == 1.0
    assert me.compute_ecgc_pt(35) == 1.0

    # Net == 36 -> PT = 0.0
    assert me.compute_ecgc_pt(36) == 0.0

    # Net >= 37 -> PT = -1.0
    assert me.compute_ecgc_pt(37) == -1.0
    assert me.compute_ecgc_pt(42) == -1.0

    # Handicap progression: HCP_next = HCP_prev - PT
    # Under net par drops handicap by 1 (harder)
    assert me.compute_next_handicap(10.0, 1.0) == 9.0
    # Over net par increases handicap by 1 (easier)
    assert me.compute_next_handicap(10.0, -1.0) == 11.0
    # Even net par leaves handicap unchanged
    assert me.compute_next_handicap(10.0, 0.0) == 10.0


def test_score_ecgc_2person_match():
    """Test 9-hole 2-person team match play with differential handicap and PT bonuses."""
    ranks = [7, 1, 5, 4, 6, 3, 2, 8, 9]
    pars = [4, 4, 4, 3, 5, 5, 4, 3, 4]  # Par 36

    team_a = {
        "team_id": 1,
        "team_name": "Team Alpha",
        "player1": {
            "player_id": 101,
            "player_name": "Alice",
            "handicap": 8.0,
            "gross_scores": [4, 4, 4, 3, 5, 4, 4, 3, 4],  # Gross 35, Net 27 -> PT +1.0
        },
        "player2": {
            "player_id": 102,
            "player_name": "Bob",
            "handicap": 12.0,
            "gross_scores": [5, 5, 5, 4, 6, 6, 5, 4, 5],  # Gross 45, Net 33 -> PT +1.0
        },
    }

    team_b = {
        "team_id": 2,
        "team_name": "Team Beta",
        "player1": {
            "player_id": 201,
            "player_name": "Charlie",
            "handicap": 5.0,
            "gross_scores": [4, 4, 4, 3, 5, 5, 4, 3, 4],  # Gross 36, Net 31 -> PT +1.0
        },
        "player2": {
            "player_id": 202,
            "player_name": "Dave",
            "handicap": 7.0,
            "gross_scores": [6, 6, 6, 5, 7, 7, 6, 5, 6],  # Gross 54, Net 47 -> PT -1.0
        },
    }

    res = me.score_ecgc_2person_match(team_a, team_b, ranks, pars)
    assert res["status"] == "scored"
    assert res["format"] == "ecgc_2person_match"

    # Hole points sum across 9 holes must equal 9.0
    hole_pts_total = res["team_a"]["hole_points"] + res["team_b"]["hole_points"]
    assert hole_pts_total == 9.0

    # Team A players both shot net < 36 -> both get +1.0 PT -> PT total = +2.0
    assert res["team_a"]["player1"]["pt"] == 1.0
    assert res["team_a"]["player2"]["pt"] == 1.0
    assert res["team_a"]["pt_bonus_total"] == 2.0
    assert res["team_a"]["total_points"] == res["team_a"]["hole_points"] + 2.0

    # Team B Charlie got +1.0, Dave got -1.0 -> PT total = 0.0
    assert res["team_b"]["player1"]["pt"] == 1.0
    assert res["team_b"]["player2"]["pt"] == -1.0
    assert res["team_b"]["pt_bonus_total"] == 0.0
    assert res["team_b"]["total_points"] == res["team_b"]["hole_points"] + 0.0

    # Automatic weekly handicap progression
    assert res["team_a"]["player1"]["hcp_next"] == 7.0  # 8.0 - 1.0
    assert res["team_a"]["player2"]["hcp_next"] == 11.0  # 12.0 - 1.0
    assert res["team_b"]["player2"]["hcp_next"] == 8.0  # 7.0 - (-1.0)


def test_ecgc_api_endpoints():
    """Test all ECGC and rules endpoints via FastAPI TestClient."""
    app = create_app()
    client = TestClient(app)

    # 1. Health check includes all leagues
    r = client.get("/api/health")
    assert r.status_code == 200
    h = r.json()
    assert h["leagues_count"] >= 21
    assert h["courses_count"] >= 5

    # 2. ECGC Seasons endpoint
    r = client.get("/api/ecgc/seasons")
    assert r.status_code == 200
    seasons = r.json()
    assert seasons["count"] == 18
    # Check that 2026 Men's League is present
    slugs = {(s["season_year"], s["league_slug"]) for s in seasons["seasons"]}
    assert (2026, "mens") in slugs
    assert (2026, "womens") in slugs

    # 3. ECGC Standings endpoint (split into first_half, second_half, final)
    r = client.get("/api/ecgc/standings?season_year=2026&league_slug=mens")
    assert r.status_code == 200
    st = r.json()
    assert "first_half" in st
    assert "second_half" in st
    assert "final" in st
    assert len(st["final"]) > 0

    # 4. ECGC Brackets endpoint
    r = client.get("/api/ecgc/brackets")
    assert r.status_code == 200
    br = r.json()
    assert br["count"] == 11
    # Check 2026 bracket
    assert any(b["season_year"] == 2026 for b in br["brackets"])

    # 5. ECGC Players endpoint
    r = client.get("/api/ecgc/players")
    assert r.status_code == 200
    pl = r.json()
    assert pl["count"] == 128
    first_player = pl["players"][0]
    assert "career_rounds" in first_player
    assert "avg_gross" in first_player
    assert "total_pt_points" in first_player

    # 6. ECGC Player Profile endpoint
    pid = first_player["id"]
    r = client.get(f"/api/ecgc/players/{pid}")
    assert r.status_code == 200
    profile = r.json()
    assert "player" in profile
    assert "season_summary" in profile
    assert "rounds" in profile
    assert "handicap_progression" in profile

    # 7. ECGC Match Breakdown endpoint
    m_list = client.get("/api/ecgc/matches?season_year=2026&league_slug=mens&week_number=1").json()["matches"]
    assert len(m_list) > 0
    known_mid = m_list[0]["id"]
    r = client.get(f"/api/ecgc/matches/{known_mid}/breakdown")
    assert r.status_code == 200
    bd = r.json()
    assert "match" in bd
    assert "team_a" in bd
    assert "team_b" in bd
    assert "holes" in bd
    assert len(bd["holes"]) == 9
    assert bd["team_a"]["hole_points"] + bd["team_b"]["hole_points"] == 9.0

    # 8. Rules Config endpoint (GET & POST)
    r = client.get("/api/rules/config/20261")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["rule_type"] == "ecgc_2person_match"
    assert cfg["net_bonus_below_max"] == 35

    # Update config
    update_payload = dict(cfg)
    update_payload["net_bonus_below_max"] = 34
    r = client.post("/api/rules/config/20261", json=update_payload)
    assert r.status_code == 200
    assert r.json()["net_bonus_below_max"] == 34
    # Revert back
    update_payload["net_bonus_below_max"] = 35
    client.post("/api/rules/config/20261", json=update_payload)

    # 9. Rules Simulate endpoint
    sim_payload = {
        "team_a": {
            "name": "Team 1",
            "player1": {"name": "P1", "handicap": 5.0, "gross_scores": [4, 4, 4, 3, 5, 5, 4, 3, 4]},
            "player2": {"name": "P2", "handicap": 10.0, "gross_scores": [5, 5, 5, 4, 6, 6, 5, 4, 5]},
        },
        "team_b": {
            "name": "Team 2",
            "player1": {"name": "P3", "handicap": 8.0, "gross_scores": [5, 4, 4, 4, 5, 5, 4, 4, 4]},
            "player2": {"name": "P4", "handicap": 12.0, "gross_scores": [6, 5, 5, 4, 6, 7, 5, 4, 6]},
        },
    }
    r = client.post("/api/rules/simulate", json=sim_payload)
    assert r.status_code == 200
    sim_res = r.json()
    assert sim_res["status"] == "scored"
    assert "holes" in sim_res
    assert len(sim_res["holes"]) == 9

    # 10. ECGC Matches list endpoint
    r = client.get("/api/ecgc/matches?season_year=2026&league_slug=mens&week_number=1")
    assert r.status_code == 200
    m_data = r.json()
    assert m_data["count"] > 0
    assert "week_number" in m_data["matches"][0]
    assert m_data["matches"][0]["week_number"] == 1


def test_ecgc_is_default_9hole_course(client):
    c_res = client.get("/api/courses").json()
    assert c_res["default_course_id"] == 5
    assert c_res["default_holes"] == 9
    first = c_res["courses"][0]
    assert first["CourseID"] == 5
    assert first["CourseName"] == "Edwards County Golf Course"
    assert first["is_default"] is True
    assert first["NumHoles"] == 9
    assert len(first["holes"]) == 9
    assert first["front_par"] == 36
    assert first["back_par"] == 0
    assert first["total_par"] == 36

    l_res = client.get("/api/leagues").json()
    assert l_res["default_league_id"] == 20261
    assert l_res["default_course_id"] == 5
    assert l_res["default_holes"] == 9
    assert l_res["leagues"][0]["LeagueID"] == 20261
    assert l_res["leagues"][0]["CourseID"] == 5
    assert l_res["leagues"][0]["LeagueHoles"] == 9

    wk_res = client.get("/api/leagues/20261/week/1").json()
    assert wk_res["num_holes"] == 9
    assert len(wk_res["holes_meta"]) == 9
    assert wk_res["course"]["CourseID"] == 5
    assert wk_res["course"]["NumHoles"] == 9


def test_ecgc_standings_backfilled_handicaps_and_player_pt(client):
    """CDX-02: Verify <lid>Teams combined handicaps & split points and <lid>Players round/PT stats."""
    st = client.get("/api/leagues/20261/standings").json()
    teams = st["teams"]
    players = st["players"]
    assert len(teams) == 22
    assert len(players) >= 44

    has_combined = [t for t in teams if float(t.get("CombinedHcp") or t.get("Handicap") or 0) > 0]
    assert len(has_combined) >= 20
    first_tm = teams[0]
    assert "1stHalfPts" in first_tm
    assert "2ndHalfPts" in first_tm
    assert "PlayerA_Name" in first_tm
    assert "PlayerB_Name" in first_tm
    assert "games_behind" in first_tm

    active_players = [p for p in players if int(p.get("rounds_played") or 0) > 0]
    assert len(active_players) >= 40
    sample_p = active_players[0]
    assert sample_p["gross_avg"] is not None
    assert sample_p["net_avg"] is not None
    assert "season_pt" in sample_p


def test_ecgc_live_score_save_triggers_2man_match_and_pt(client):
    """CDX-01 & AGY-02: Verify live 9-hole score saving computes 2-man match play + per-player Net PT."""
    wk1 = client.get("/api/leagues/20261/week/1").json()
    cards = wk1["scorecards"]
    assert len(cards) >= 44
    sample_card = next(c for c in cards if int(c.get("Gross") or 0) > 0)
    assert "ecgc_pt" in sample_card
    assert "next_handicap" in sample_card

    res = client.post("/api/leagues/20261/week/1/auto-score-matches")
    assert res.status_code == 200
    body = res.json()
    assert body["league_id"] == 20261
    assert body["week_num"] == 1
    assert len(body["team_results"]) >= 20
    assert len(body["ecgc_matches"]) >= 10


def test_ecgc_course_analytics_endpoint(client):
    """AGY-05: Verify Hole 1-9 scoring averages, relative-to-par toughness rank, and Birdie/Par/Bogey stats."""
    all_time = client.get("/api/ecgc/course-analytics").json()
    assert all_time["course_id"] == 5
    assert all_time["league_id"] is None
    holes = all_time["holes"]
    assert len(holes) == 9
    ranks = sorted(h["toughness_rank"] for h in holes)
    assert ranks == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    for h in holes:
        assert h["samples"] > 1000
        assert h["avg_gross"] > 2.5
        assert "birdies" in h and "pars" in h and "bogeys" in h

    season_only = client.get("/api/ecgc/course-analytics?league_id=20261").json()
    assert season_only["league_id"] == 20261
    assert len(season_only["holes"]) == 9


def test_ecgc_team_edit_and_schedule_matchups_and_rollover(client):
    """AGY-03, AGY-04, CDX-03: Verify 2-man team update, weekly matchup builder, and season rollover."""
    # 1. Update Team 1 partner/name
    r_tm = client.post(
        "/api/leagues/20261/teams/1",
        json={"TeamName": "Team 1 (Oferle / Strader)", "Division": 1},
    )
    assert r_tm.status_code == 200
    tm_list = r_tm.json()["teams"]
    t1 = next(t for t in tm_list if t["TeamID"] == 1)
    assert t1["TeamName"] == "Team 1 (Oferle / Strader)"

    # 2. Schedule endpoint returns all matches per week
    sched = client.get("/api/leagues/20261/schedule").json()
    assert len(sched["schedule"]) >= 16
    wk1_matches = sched["schedule"][0]["matches"]
    assert len(wk1_matches) == 11
    assert wk1_matches[0]["match_num"] == 1

    # 3. Save custom weekly 2-man pairings for Week 16
    r_wk = client.post(
        "/api/ecgc/leagues/20261/week/16/matchups",
        json={
            "date": "2026-08-18",
            "half": 2,
            "matches": [
                {"match_num": 1, "team1_id": 1, "team2_id": 2},
                {"match_num": 2, "team1_id": 3, "team2_id": 4},
            ],
        },
    )
    assert r_wk.status_code == 200
    wk16_row = next(w for w in r_wk.json()["schedule"] if w["WeekNum"] == 16)
    assert len(wk16_row["matches"]) >= 2
    assert wk16_row["Match1Team1"] == 1 and wk16_row["Match1Team2"] == 2
    assert wk16_row["Match2Team1"] == 3 and wk16_row["Match2Team2"] == 4
    assert wk16_row["matches"][0]["team1_id"] == 1
    assert wk16_row["matches"][0]["team2_id"] == 2

    # 4. Rollover 20261 into 2027 Men's (20271)
    r_ro = client.post(
        "/api/ecgc/seasons/rollover",
        json={
            "source_league_id": 20261,
            "target_year": 2027,
            "division": "mens",
            "weeks": 16,
            "start_date": "2027-05-05",
        },
    )
    assert r_ro.status_code == 200
    ro_data = r_ro.json()
    assert ro_data["status"] == "ok"
    assert ro_data["new_league_id"] == 20271
    assert ro_data["teams_carried_over"] == 22
    assert ro_data["players_carried_over"] >= 44
