"""Pure unit tests for the scoring / handicap / match-play / schedule engine."""
from __future__ import annotations

import sqlite3

import pytest

from app import golf_engine as ge


# ---------------------------------------------------------------------------
# Rounding & coercion helpers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value,expected",
    [(0, 0), (0.4, 0), (0.5, 1), (1.5, 2), (2.5, 3), (12.5, 13), (12.49, 12), (-0.5, -1), (-1.4, -1), (None, 0),
     (float("nan"), 0), (float("inf"), 0)],
)
def test_round_half_up(value, expected):
    assert ge.round_half_up(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(None, 0), ("", 0), ("7", 7), ("7.0", 7), (7.9, 7), ("N/A", 0), (float("nan"), 0), ([], 0)],
)
def test_safe_int(value, expected):
    assert ge.safe_int(value) == expected


def test_safe_int_default():
    assert ge.safe_int("junk", default=-1) == -1


# ---------------------------------------------------------------------------
# Handicap stroke allocation
# ---------------------------------------------------------------------------
def test_strokes_zero_and_negative_handicap():
    assert ge.strokes_on_hole(0, 1) == 0
    assert ge.strokes_on_hole(-3, 1) == 0
    assert ge.strokes_on_hole(None, 1) == 0


def test_strokes_18_hole_total_equals_handicap():
    for hcp in (1, 9, 17, 18, 19, 27, 36, 40):
        total = sum(ge.strokes_on_hole(hcp, rank, 18) for rank in range(1, 19))
        assert total == hcp, hcp


def test_strokes_9_hole_total_equals_handicap():
    for hcp in (1, 4, 8, 9, 10, 18, 20):
        total = sum(ge.strokes_on_hole(hcp, rank, 9) for rank in range(1, 10))
        assert total == hcp, hcp


def test_strokes_go_to_hardest_holes_first():
    assert ge.strokes_on_hole(1, 1) == 1
    assert ge.strokes_on_hole(1, 2) == 0
    assert ge.strokes_on_hole(20, 1) == 2
    assert ge.strokes_on_hole(20, 2) == 2
    assert ge.strokes_on_hole(20, 3) == 1


def test_strokes_half_handicap_rounds_up():
    # Regression: banker's rounding made a 12.5 handicap play off 12.
    total = sum(ge.strokes_on_hole(12.5, r, 18) for r in range(1, 19))
    assert total == 13


def test_strokes_9_hole_with_18_hole_rank_is_compressed():
    # Ranks 17 and 18 both map to the 9th-hardest of nine.
    assert ge.strokes_on_hole(8, 17, 9) == 0
    assert ge.strokes_on_hole(9, 17, 9) == 1
    assert ge.strokes_on_hole(1, 2, 9) == 0  # rank 2 is 2nd hardest


def test_stroke_index_map_relative_order():
    holes = [{"handicap_rank": r} for r in (5, 9, 17, 7, 13, 1, 11, 15, 3)]
    assert ge.stroke_index_map(holes) == [3, 5, 9, 4, 7, 1, 6, 8, 2]


def test_stroke_index_map_handles_duplicate_and_missing_ranks():
    holes = [{"handicap_rank": 3}, {"handicap_rank": None}, {"handicap_rank": 3}, {}]
    ranks = ge.stroke_index_map(holes)
    assert sorted(ranks) == [1, 2, 3, 4]
    assert ranks[0] == 1 and ranks[2] == 2  # ties broken by hole order


# ---------------------------------------------------------------------------
# Equitable Stroke Control
# ---------------------------------------------------------------------------
def test_esc_unplayed_and_mode_zero():
    assert ge.apply_esc_cap(0, 4, 10) == 0
    assert ge.apply_esc_cap(-2, 4, 10) == 0
    assert ge.apply_esc_cap(12, 4, 10, adjust_mode=0) == 12


def test_esc_double_bogey_mode():
    assert ge.apply_esc_cap(9, 4, 30, adjust_mode=1) == 6
    assert ge.apply_esc_cap(5, 4, 30, adjust_mode=1) == 5


@pytest.mark.parametrize(
    "hcp,par,expected_cap",
    [(0, 4, 6), (9, 5, 7), (10, 4, 7), (19, 4, 7), (20, 4, 8), (29, 4, 8), (30, 4, 9), (39, 4, 9), (40, 4, 10), (54, 4, 10)],
)
def test_esc_usga_table(hcp, par, expected_cap):
    assert ge.apply_esc_cap(15, par, hcp, adjust_mode=2) == expected_cap


def test_esc_usga_uses_rounded_course_handicap():
    # Regression: a 9.4 handicap is a course handicap of 9 -> double-bogey cap (6 on par 4), not 7.
    assert ge.apply_esc_cap(12, 4, 9.4, adjust_mode=2) == 6
    assert ge.apply_esc_cap(12, 4, 9.5, adjust_mode=2) == 7


def test_esc_usga_nine_hole_doubles_handicap():
    assert ge.apply_esc_cap(12, 4, 5, adjust_mode=2, num_holes=9) == 7  # 5*2 = 10 -> cap 7
    assert ge.apply_esc_cap(12, 4, 4, adjust_mode=2, num_holes=9) == 6  # 8 -> double bogey


# ---------------------------------------------------------------------------
# Stableford
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("score,par,pts", [(2, 5, 5), (1, 4, 5), (2, 4, 4), (3, 4, 2), (4, 4, 1), (5, 4, 0), (6, 4, -1), (9, 4, -1)])
def test_stableford_points(score, par, pts):
    assert ge.hole_stableford_pts(score, par) == pts


def test_stableford_unplayed_gross_is_zero():
    assert ge.hole_stableford_pts(0, 4) == 0


def test_stableford_net_zero_or_negative_scores_points():
    # Regression: an ace on a par 3 with 2 strokes is net -1 -> albatross-or-better.
    assert ge.hole_stableford_pts(-1, 3, is_net=True) == 5
    assert ge.hole_stableford_pts(0, 3, is_net=True) == 5
    assert ge.hole_stableford_pts(1, 3, is_net=True) == 4


# ---------------------------------------------------------------------------
# Rules summary
# ---------------------------------------------------------------------------
def test_rules_summary_defaults_on_empty_input():
    rs = ge.build_rules_summary({}, {}, [])
    assert rs["HolePts"] == 1.0
    assert rs["IndMatchPts"] == 2.0
    assert rs["TeamMatchPts"] == 4.0
    assert rs["FieldTopPts"] == 0.0
    assert rs["AdjustScores"] == 1
    assert rs["AdjustScoresLabel"] == "Double Bogey Max"
    assert rs["Divisions"] == ["Open Flight"]


def test_rules_summary_divisions_filter_na():
    rs = ge.build_rules_summary({"Div1": "A", "Div2": "NA", "Div3": "", "Div4": "C"}, {}, [])
    assert rs["Divisions"] == ["A", "C"]


# ---------------------------------------------------------------------------
# Field points
# ---------------------------------------------------------------------------
def _card(pid, net, gross=40):
    return {"PlayerID": pid, "Net": net, "Gross": gross}


def test_field_points_disabled_when_top_is_zero():
    assert ge._compute_field_points([_card(1, 30)], {"FieldTopPts": 0}) == {}


def test_field_points_steps_ties_and_floor():
    cards = [_card(1, 30), _card(2, 31), _card(3, 31), _card(4, 40), _card(5, 0, gross=0)]
    pts = ge._compute_field_points(cards, {"FieldTopPts": 4, "FieldStepPts": 2})
    assert pts[1] == 4.0
    assert pts[2] == pts[3] == 1.0  # (2 + 0) / 2
    assert pts[4] == 0.0  # floored at zero, never negative
    assert 5 not in pts  # did not play


# ---------------------------------------------------------------------------
# Match play
# ---------------------------------------------------------------------------
HOLES_9 = [{"hole": i, "par": 4, "handicap_rank": i} for i in range(1, 10)]


def _mcard(pid, holes, hcp=0.0, team=1):
    g = sum(holes)
    return {"PlayerID": pid, "PlayerName": f"P{pid}", "TeamID": team, "Handicap": hcp, "holes": holes, "Gross": g, "Net": g - round(hcp)}


def test_match_play_win_and_points():
    cards = {1: _mcard(1, [4] * 9), 2: _mcard(2, [5] * 9)}
    (m,) = ge._compute_matchups([(1, 2)], cards, HOLES_9, {"HolePts": 1, "IndMatchPts": 2}, 9)
    assert m["holes_won_a"] == 9 and m["holes_won_b"] == 0
    assert m["computed_pts_a"] == 11.0 and m["computed_pts_b"] == 0.0
    assert "wins +9 UP" in m["status"]


def test_match_play_all_halved_splits_points():
    cards = {1: _mcard(1, [4] * 9), 2: _mcard(2, [4] * 9)}
    (m,) = ge._compute_matchups([(1, 2)], cards, HOLES_9, {"HolePts": 1, "IndMatchPts": 2}, 9)
    assert m["holes_halved"] == 9
    assert m["computed_pts_a"] == m["computed_pts_b"] == 5.5
    assert m["status"] == "All Square (Halved)"


def test_match_play_handicap_difference_strokes():
    # B is 1 stroke higher -> gets a stroke on the hardest hole (rank 1) only.
    cards = {1: _mcard(1, [4] * 9, hcp=2), 2: _mcard(2, [5] + [4] * 8, hcp=3)}
    (m,) = ge._compute_matchups([(1, 2)], cards, HOLES_9, {"HolePts": 1, "IndMatchPts": 2}, 9)
    assert m["holes_halved"] == 9


def test_match_play_awaiting_scores():
    cards = {1: _mcard(1, [4] * 9), 2: _mcard(2, [0] * 9)}
    (m,) = ge._compute_matchups([(1, 2)], cards, HOLES_9, {}, 9)
    assert m["status"] == "Awaiting Scores"
    assert m["computed_pts_a"] == m["computed_pts_b"] == 0


def test_match_play_skips_self_and_duplicate_pairings():
    cards = {i: _mcard(i, [4] * 9) for i in (1, 2, 3)}
    out = ge._compute_matchups([(1, 1), (1, 2), (2, 3), (3, 3)], cards, HOLES_9, {}, 9)
    assert [(m["PlayerA_ID"], m["PlayerB_ID"]) for m in out] == [(1, 2)]


def test_match_play_unknown_player_ignored():
    cards = {1: _mcard(1, [4] * 9)}
    assert ge._compute_matchups([(1, 99)], cards, HOLES_9, {}, 9) == []


# ---------------------------------------------------------------------------
# Schedule generation (validation paths use an in-memory DB)
# ---------------------------------------------------------------------------
def _sched_db(num_teams=4, template: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute('CREATE TABLE "Leagues" ("LeagueID", "CourseID", "LeagueName")')
    conn.execute('INSERT INTO "Leagues" VALUES (1, 1, "Test")')
    conn.execute('CREATE TABLE "LeagueRules" ("LeagueID")')
    for t in ("Courses", "CoursePar", "CourseHandicap", "CourseYards"):
        conn.execute(f'CREATE TABLE "{t}" ("CourseID", "CourseName")' if t == "Courses" else f'CREATE TABLE "{t}" ("CourseID")')
    conn.execute('CREATE TABLE "1Teams" ("TeamID", "TeamName", "Points", "PrevPts")')
    for i in range(1, num_teams + 1):
        conn.execute('INSERT INTO "1Teams" VALUES (?,?,0,0)', (i, f"T{i}"))
    conn.execute(
        'CREATE TABLE "1Schedule" ("WeekNum","Date","DateType","CourseID","SchedUsed","Half","Weather",'
        '"Match1Team1","Match1Team2","Match2Team1","Match2Team2")'
    )
    conn.execute("CREATE TABLE round_robin_templates (num_teams INTEGER PRIMARY KEY, filename TEXT, weeks_count INTEGER, raw_csv TEXT)")
    if template is not None:
        conn.execute("INSERT INTO round_robin_templates VALUES (?,?,?,?)", (num_teams, "x.csv", 1, template))
    return conn


@pytest.mark.parametrize("weeks", [0, -1, 53, 10_000])
def test_generate_schedule_rejects_bad_week_counts(weeks):
    conn = _sched_db()
    with pytest.raises(ge.InvalidInputError):
        ge.generate_schedule(conn, 1, weeks, "2026-05-05")
    # Regression: a rejected request must not wipe the existing schedule.
    assert conn.execute('SELECT COUNT(*) FROM "1Schedule"').fetchone()[0] == 0


@pytest.mark.parametrize("bad", ["", "05/05/2026", "2026-13-01", "2026-02-30", "garbage"])
def test_generate_schedule_rejects_bad_dates(bad):
    with pytest.raises(ge.InvalidInputError):
        ge.generate_schedule(_sched_db(), 1, 4, bad)


def test_generate_schedule_unknown_league():
    with pytest.raises(ge.NotFoundError):
        ge.generate_schedule(_sched_db(), 2, 4, "2026-05-05")


def test_generate_schedule_from_template_and_dates():
    conn = _sched_db(template="1,2,3,4\n1,3,2,4\n1,4,2,3\n")
    rows = ge.generate_schedule(conn, 1, 5, "2026-05-05")
    assert [r["WeekNum"] for r in rows] == [1, 2, 3, 4, 5]
    assert rows[0]["Date"].startswith("05/05/26")
    assert rows[1]["Date"].startswith("05/12/26")
    assert (rows[0]["Match1Team1"], rows[0]["Match1Team2"]) == (1, 2)
    assert (rows[3]["Match1Team1"], rows[3]["Match1Team2"]) == (1, 2)  # template wraps
    assert [r["Half"] for r in rows] == [1, 1, 2, 2, 2]


def test_generate_schedule_ignores_malformed_template_rows():
    # Rows with repeated / out-of-range teams are discarded; the circle-method fallback kicks in.
    conn = _sched_db(template="1,1,2,2\n9,9,9,9\n")
    rows = ge.generate_schedule(conn, 1, 3, "2026-05-05")
    for r in rows:
        teams = [r["Match1Team1"], r["Match1Team2"], r["Match2Team1"], r["Match2Team2"]]
        assert len(set(teams)) == 4
        assert all(1 <= t <= 4 for t in teams)


def test_generate_schedule_circle_method_is_a_round_robin():
    conn = _sched_db(num_teams=4)
    rows = ge.generate_schedule(conn, 1, 3, "2026-05-05")
    games = set()
    for r in rows:
        games.add(frozenset((r["Match1Team1"], r["Match1Team2"])))
        games.add(frozenset((r["Match2Team1"], r["Match2Team2"])))
    assert len(games) == 6  # every one of the C(4,2) pairings exactly once in 3 weeks


def test_generate_schedule_accepts_date_object():
    from datetime import date

    rows = ge.generate_schedule(_sched_db(), 1, 1, date(2026, 6, 2))
    assert rows[0]["Date"].startswith("06/02/26")


def test_not_found_error_str_is_clean():
    assert str(ge.NotFoundError("League 5 not found")) == "League 5 not found"

def test_field_points_with_legacy_and_new_columns(monkeypatch):
    import sqlite3
    from app import match_engine

    entries = {
        1: {"PlayerName": "P1", "Net": 30, "Division": "A", "played": True, "IndividualPts": 0, "holes_won": 0, "Gross": 40},
        2: {"PlayerName": "P2", "Net": 35, "Division": "A", "played": True, "IndividualPts": 0, "holes_won": 0, "Gross": 45}
    }

    def fake_load_week_entries(*args):
        return entries

    def fake_matchsetup_pairs(*args):
        return []

    def fake_resolve_pairs(*args):
        return [], ""

    monkeypatch.setattr(match_engine, "load_week_entries", fake_load_week_entries)
    monkeypatch.setattr(match_engine, "matchsetup_pairs", fake_matchsetup_pairs)
    monkeypatch.setattr(match_engine, "resolve_pairs", fake_resolve_pairs)

    def fake_load_league_context_new(conn, lid):
        return {
            "rules": {"FieldTopPts": 10.0, "FieldStepPts": 2.0},
            "divisions": ["A"],
            "scoring_mode_name": "x",
            "adjust_mode_name": "x",
            "num_man_teams": 1,
            "teams": {},
            "league": {}
        }

    monkeypatch.setattr(match_engine, "load_league_context", fake_load_league_context_new)

    conn = sqlite3.connect(":memory:")
    res_new = match_engine.compute_week(conn, 1, 1)

    def fake_load_league_context_legacy(conn, lid):
        return {
            "rules": {"IndPtsNetField": 10.0, "IndNetFieldDiff": 2.0},
            "divisions": ["A"],
            "scoring_mode_name": "x",
            "adjust_mode_name": "x",
            "num_man_teams": 1,
            "teams": {},
            "league": {}
        }

    monkeypatch.setattr(match_engine, "load_league_context", fake_load_league_context_legacy)

    res_legacy = match_engine.compute_week(conn, 1, 1)

    # Both should assign 10.0 pts to the winner (P1, Net 30) and 8.0 to P2 (Net 35)
    fld_new = {c["PlayerID"]: c["FieldPts"] for c in res_new["field_points"]}
    fld_legacy = {c["PlayerID"]: c["FieldPts"] for c in res_legacy["field_points"]}

    assert fld_new == {1: 10.0, 2: 8.0}
    assert fld_legacy == {1: 10.0, 2: 8.0}
