import pytest
from app import match_engine as me


def test_esc_cap():
    assert me.esc_cap(4, 5.0, 0) is None
    assert me.esc_cap(4, 5.0, 1) is None
    assert me.esc_cap(4, 5.0, 2) == 6
    assert me.esc_cap(5, 5.0, 2) == 7
    assert me.esc_cap(3, 9.0, 3) == 5
    assert me.esc_cap(4, 15.0, 3) == 7
    assert me.esc_cap(5, 25.0, 3) == 8
    assert me.esc_cap(3, 35.0, 3) == 9
    assert me.esc_cap(4, 45.0, 3) == 10

def test_apply_esc():
    holes = [3, 4, 5, 0, -1, 10, 8]
    pars =  [3, 4, 5, 3, 4,  4,  5]
    assert me.apply_esc(holes, pars, 15.0, 3) == [3, 4, 5, 0, 0, 7, 7]
    assert me.apply_esc(holes, pars, 5.0, 2) == [3, 4, 5, 0, 0, 6, 7]
    assert me.apply_esc(holes, pars, 15.0, 0) == [3, 4, 5, 0, 0, 10, 8]

def test_nine_ranks():
    # Example caps18: hole 1 has cap 17, hole 2 has cap 1, etc.
    caps18 = [17, 1, 15, 3, 13, 5, 11, 7, 9,
              18, 2, 16, 4, 14, 6, 12, 8, 10]
    assert me.nine_ranks(caps18, "front") == [9, 1, 8, 2, 7, 3, 6, 4, 5]
    assert me.nine_ranks(caps18, "back") == [9, 1, 8, 2, 7, 3, 6, 4, 5]

def test_strokes_per_hole():
    ranks = [9, 1, 8, 2, 7, 3, 6, 4, 5]
    assert me.strokes_per_hole(5.0, ranks, 9) == [0, 1, 0, 1, 0, 1, 0, 1, 1]
    assert me.strokes_per_hole(12.0, ranks, 9) == [1, 2, 1, 2, 1, 2, 1, 1, 1]
    assert me.strokes_per_hole(0.0, ranks, 9) == [0, 0, 0, 0, 0, 0, 0, 0, 0]

def test_stableford_points():
    matrix = me.MODIFIED_STABLEFORD_DEFAULT
    net_or_gross = [3, 4, 5, 6, 3, 4, 0, 10, 8]
    pars =         [4, 4, 4, 4, 3, 3, 3, 4,  5]
    # diffs: -1, 0, 1, 2, 0, 1, None, 6, 3
    # pts: 2, 0, -1, -3, 0, -1, 0, -3, -3
    assert me.stableford_points(net_or_gross, pars, matrix) == -9

def test_split_points():
    assert me.split_points(35.0, 36.0, 2.0) == (2.0, 0.0)
    assert me.split_points(36.0, 35.0, 2.0) == (0.0, 2.0)
    assert me.split_points(35.0, 35.0, 2.0) == (1.0, 1.0)
    assert me.split_points(35.0, 35.0, 0.0) == (0.0, 0.0)

def test_holes_won():
    a = [3, 4, 5, 0, 4]
    b = [4, 4, 4, 3, 0]
    aw, bw, codes = me.holes_won(a, b)
    assert aw == 1.5
    assert bw == 1.5
    assert codes == ["A", "T", "B", "-", "-"]

def test_field_points():
    entries = [(1, 35.0), (2, 36.0), (3, 36.0), (4, 38.0)]
    # Pool 0: 10
    # Pool 1 (ties): 9 + 8 = 17 / 2 = 8.5
    # Pool 2: 7
    res = me.field_points(entries, 10.0, 1.0)
    assert res == {1: 10.0, 2: 8.5, 3: 8.5, 4: 7.0}
    assert me.field_points([], 10.0, 1.0) == {}
    assert me.field_points([(1, 35.0)], 0.0, 1.0) == {}

def test_tee_times():
    assert me.tee_times(None, None, 3) == ["5:30 PM", "5:40 PM", "5:50 PM"]
    assert me.tee_times("04:00 PM", 15, 2) == ["4:00 PM", "4:15 PM"]
    assert me.tee_times("14:30", 8, 3) == ["2:30 PM", "2:38 PM", "2:46 PM"]
    assert me.tee_times("invalid", 10, 2) == ["5:30 PM", "5:40 PM"]

def test_detect_nine():
    # 18 holes
    assert me.detect_nine([1]*18, 18) == "both"
    # Front 9
    assert me.detect_nine([1]*9 + [0]*9, 9) == "front"
    # Back 9
    assert me.detect_nine([0]*9 + [1]*9, 9) == "back"
    # Default fallback
    assert me.detect_nine([0]*18, 9, "front") == "front"
    assert me.detect_nine([0]*18, 9, "back") == "back"

def test_rules_summary():
    ctx = {
        "scoring_mode": 2,
        "scoring_mode_name": "hole_by_hole_match",
        "adjust_mode": 3,
        "adjust_mode_name": "usga_esc",
        "stableford": {},
        "stableford_source": "default",
        "divisions": ["A"],
        "num_man_teams": 2,
        "league": {
            "FirstTeeTime": "05:30 PM",
            "MinsBetweenGroups": 10,
            "SubPercent": 100
        },
        "rules": {
            "IndPtsNet": 1.0,
            "IndPtsAct": 0.0,
            "IndPtsNetMatch": 2.0,
            "IndPtsActMatch": 0.0,
            "IndPtsHolesMatch": 0.0,
            "IndPtsNetField": 0.0,
            "IndNetFieldDiff": 0.0,
            "TeamPtsNetMatch": 2.0,
            "TeamPtsHolesMatch": 2.0,
            "PlayerForfeit": 10.0,
        }
    }
    summary = me.rules_summary(ctx)
    assert summary["scoring_mode"] == 2
    assert "1 pt per net hole won (ties split)" in summary["human_rules"]
    assert "2 pts for low net round (ties split)" in summary["human_rules"]
    assert "Team: 2 pts low team net" in summary["human_rules"]
    assert "Team: 2 pts aggregate net holes won" in summary["human_rules"]
    assert "Forfeit: opponent receives 10" in summary["human_rules"]
    assert summary["rule_values"]["IndPtsNet"] == 1.0

def test_score_ecgc_2person_match():
    team_a = {
        "team_id": 1,
        "team_name": "Team A",
        "player1": {"id": 1, "name": "P1", "handicap": 5.0, "gross_scores": [4,4,4,4,4,4,4,4,4]},
        "player2": {"id": 2, "name": "P2", "handicap": 5.0, "gross_scores": [4,4,4,4,4,4,4,4,4]}
    }
    team_b = {
        "team_id": 2,
        "team_name": "Team B",
        "player1": {"id": 3, "name": "P3", "handicap": 5.0, "gross_scores": [5,5,5,5,5,5,5,5,5]},
        "player2": {"id": 4, "name": "P4", "handicap": 5.0, "gross_scores": [5,5,5,5,5,5,5,5,5]}
    }
    rules = {
        "points_per_hole_win": 1.0,
        "points_per_hole_tie": 0.5,
        "net_bonus_below_max": 35,
        "net_bonus_pts": 1.0,
        "net_even_min": 36,
        "net_even_max": 36,
        "net_even_pts": 0.0,
        "net_penalty_above_min": 37,
        "net_penalty_pts": -1.0,
    }
    pars = [4]*9
    ranks = [1,2,3,4,5,6,7,8,9]
    res = me.score_ecgc_2person_match(team_a, team_b, ranks, pars, rules)
    assert res["status"] == "scored"
    assert res["team_a"]["hole_points"] == 9.0
    assert res["team_b"]["hole_points"] == 0.0
    assert res["match_winner"] == "team_a"
    # P1 net: 36 - 5 = 31 (under 35 => 1 pt)
    assert res["team_a"]["pt_bonus_total"] == 2.0

def test_score_match_forfeit_and_absent():
    ctx = {
        "scoring_mode_name": "hole_by_hole_match",
        "rules": {
            "PlayerForfeit": 10.0,
            "PresentPlayerPts": 12.0
        },
        "players": []
    }
    a_played = {"PlayerID": 1, "PlayerName": "A", "Handicap": 0, "Gross": 36, "AdjGross": 36, "Net": 36, "holes": [4]*9, "adj_holes": [4]*9, "net_holes": [4]*9, "strokes": [0]*9, "played": True, "forfeit": False}
    b_forfeit = {"PlayerID": 2, "PlayerName": "B", "Handicap": 0, "Gross": 0, "AdjGross": 0, "Net": 0, "holes": [0]*9, "adj_holes": [0]*9, "net_holes": [0]*9, "strokes": [0]*9, "played": False, "forfeit": True}

    # B forfeits, A gets forfeit points (10.0)
    res1 = me.score_match(ctx, a_played, b_forfeit, 1, 2)
    assert res1["status"] == "forfeit_b"
    assert res1["a"]["IndividualPts"] == 10.0
    assert res1["b"]["IndividualPts"] == 0.0

    b_absent = {"PlayerID": 2, "PlayerName": "B", "Handicap": 0, "Gross": 0, "AdjGross": 0, "Net": 0, "holes": [0]*9, "adj_holes": [0]*9, "net_holes": [0]*9, "strokes": [0]*9, "played": False, "forfeit": False}
    # B absent, A gets present points (12.0)
    res2 = me.score_match(ctx, a_played, b_absent, 1, 2)
    assert res2["status"] == "absent_b"
    assert res2["a"]["IndividualPts"] == 12.0
    assert res2["b"]["IndividualPts"] == 0.0

def test_score_match_hole_by_hole():
    ctx = {
        "scoring_mode_name": "hole_by_hole_match",
        "rules": {
            "IndPtsNet": 1.0,
            "IndPtsAct": 0.5,
            "IndPtsNetMatch": 2.0,
            "IndPtsActMatch": 1.0,
            "IndPtsHolesMatch": 0.0
        },
        "players": []
    }
    a = {"PlayerID": 1, "PlayerName": "A", "Handicap": 0, "Gross": 35, "AdjGross": 35, "Net": 35, "holes": [3,4,4,4,4,4,4,4,4], "adj_holes": [3,4,4,4,4,4,4,4,4], "net_holes": [3,4,4,4,4,4,4,4,4], "strokes": [0]*9, "played": True, "forfeit": False}
    b = {"PlayerID": 2, "PlayerName": "B", "Handicap": 0, "Gross": 36, "AdjGross": 36, "Net": 36, "holes": [4,4,4,4,4,4,4,4,4], "adj_holes": [4,4,4,4,4,4,4,4,4], "net_holes": [4,4,4,4,4,4,4,4,4], "strokes": [0]*9, "played": True, "forfeit": False}

    res = me.score_match(ctx, a, b, 1, 2)
    assert res["status"] == "scored"
    # A wins hole 1, ties other 8. Total holes won = 1 + 8*(0.5) = 5.0
    # B wins 0 holes, ties 8. Total holes won = 0 + 8*(0.5) = 4.0
    # Net pts A: 5.0 * 1.0 = 5.0. Gross pts A: 5.0 * 0.5 = 2.5
    # A has low net (35 vs 36) -> 2.0. A has low gross (35 vs 36) -> 1.0
    # Total A = 5.0 + 2.5 + 2.0 + 1.0 = 10.5
    assert res["a"]["IndividualPts"] == 10.5
    # Net pts B: 4.0 * 1.0 = 4.0. Gross pts B: 4.0 * 0.5 = 2.0
    # Total B = 4.0 + 2.0 + 0 + 0 = 6.0
    assert res["b"]["IndividualPts"] == 6.0

def test_score_match_nines_plus_match():
    ctx = {
        "scoring_mode_name": "nines_plus_match",
        "rules": {
            "IndPtsNet": 1.0,
            "IndPtsHolesMatch": 2.0,
            "IndPtsNetMatch": 2.0
        },
        "players": []
    }
    # Test with 18 holes
    a = {"PlayerID": 1, "PlayerName": "A", "Handicap": 0, "Gross": 70, "AdjGross": 70, "Net": 70, "holes": [3]*18, "adj_holes": [3]*18, "net_holes": [3]*18, "strokes": [0]*18, "played": True, "forfeit": False}
    b = {"PlayerID": 2, "PlayerName": "B", "Handicap": 0, "Gross": 72, "AdjGross": 72, "Net": 72, "holes": [4]*18, "adj_holes": [4]*18, "net_holes": [4]*18, "strokes": [0]*18, "played": True, "forfeit": False}

    res = me.score_match(ctx, a, b, 1, 2)
    assert res["status"] == "scored"
    # A wins front nine net (27 vs 36) -> 1.0
    # A wins back nine net (27 vs 36) -> 1.0
    # A wins holes match (18 vs 0) -> 2.0
    # A wins low net round (70 vs 72) -> 2.0
    # Total A = 1.0 + 1.0 + 2.0 + 2.0 = 6.0
    assert res["a"]["IndividualPts"] == 6.0
    assert res["b"]["IndividualPts"] == 0.0

    # Test with 9 holes
    a9 = {"PlayerID": 1, "PlayerName": "A", "Handicap": 0, "Gross": 35, "AdjGross": 35, "Net": 35, "holes": [3]*9, "adj_holes": [3]*9, "net_holes": [3]*9, "strokes": [0]*9, "played": True, "forfeit": False}
    b9 = {"PlayerID": 2, "PlayerName": "B", "Handicap": 0, "Gross": 36, "AdjGross": 36, "Net": 36, "holes": [4]*9, "adj_holes": [4]*9, "net_holes": [4]*9, "strokes": [0]*9, "played": True, "forfeit": False}
    res9 = me.score_match(ctx, a9, b9, 1, 2)
    assert res9["a"]["IndividualPts"] == 5.0 # 1.0 (nine net) + 2.0 (holes match) + 2.0 (low net)

def test_score_match_missing_scores():
    ctx = {
        "scoring_mode_name": "hole_by_hole_match",
        "rules": {},
        "players": []
    }
    a_unplayed = {"PlayerID": 1, "PlayerName": "A", "Handicap": 0, "Gross": 0, "AdjGross": 0, "Net": 0, "holes": [0]*9, "adj_holes": [0]*9, "net_holes": [0]*9, "strokes": [0]*9, "played": False, "forfeit": False}
    b_unplayed = {"PlayerID": 2, "PlayerName": "B", "Handicap": 0, "Gross": 0, "AdjGross": 0, "Net": 0, "holes": [0]*9, "adj_holes": [0]*9, "net_holes": [0]*9, "strokes": [0]*9, "played": False, "forfeit": False}

    res = me.score_match(ctx, a_unplayed, b_unplayed, 1, 2)
    assert res["status"] == "no_scores"
    assert res["a"]["IndividualPts"] == 0.0
    assert res["b"]["IndividualPts"] == 0.0

    res2 = me.score_match(ctx, None, None, 1, 2)
    assert res2["status"] == "no_scores"

def test_score_match_forfeit_a_and_absent_a():
    ctx = {
        "scoring_mode_name": "hole_by_hole_match",
        "rules": {
            "PlayerForfeit": 10.0,
            "PresentPlayerPts": 12.0
        },
        "players": []
    }
    b_played = {"PlayerID": 2, "PlayerName": "B", "Handicap": 0, "Gross": 36, "AdjGross": 36, "Net": 36, "holes": [4]*9, "adj_holes": [4]*9, "net_holes": [4]*9, "strokes": [0]*9, "played": True, "forfeit": False}
    a_forfeit = {"PlayerID": 1, "PlayerName": "A", "Handicap": 0, "Gross": 0, "AdjGross": 0, "Net": 0, "holes": [0]*9, "adj_holes": [0]*9, "net_holes": [0]*9, "strokes": [0]*9, "played": False, "forfeit": True}

    # A forfeits, B gets forfeit points (10.0)
    res1 = me.score_match(ctx, a_forfeit, b_played, 1, 2)
    assert res1["status"] == "forfeit_a"
    assert res1["a"]["IndividualPts"] == 0.0
    assert res1["b"]["IndividualPts"] == 10.0

    a_absent = {"PlayerID": 1, "PlayerName": "A", "Handicap": 0, "Gross": 0, "AdjGross": 0, "Net": 0, "holes": [0]*9, "adj_holes": [0]*9, "net_holes": [0]*9, "strokes": [0]*9, "played": False, "forfeit": False}
    # A absent, B gets present points (12.0)
    res2 = me.score_match(ctx, a_absent, b_played, 1, 2)
    assert res2["status"] == "absent_a"
    assert res2["a"]["IndividualPts"] == 0.0
    assert res2["b"]["IndividualPts"] == 12.0

def test_score_match_hole_by_hole_holesmatch():
    ctx = {
        "scoring_mode_name": "hole_by_hole_match",
        "rules": {
            "IndPtsNet": 0.0,
            "IndPtsAct": 0.0,
            "IndPtsNetMatch": 0.0,
            "IndPtsActMatch": 0.0,
            "IndPtsHolesMatch": 5.0
        },
        "players": []
    }
    a = {"PlayerID": 1, "PlayerName": "A", "Handicap": 0, "Gross": 35, "AdjGross": 35, "Net": 35, "holes": [3,4,4,4,4,4,4,4,4], "adj_holes": [3,4,4,4,4,4,4,4,4], "net_holes": [3,4,4,4,4,4,4,4,4], "strokes": [0]*9, "played": True, "forfeit": False}
    b = {"PlayerID": 2, "PlayerName": "B", "Handicap": 0, "Gross": 36, "AdjGross": 36, "Net": 36, "holes": [4,4,4,4,4,4,4,4,4], "adj_holes": [4,4,4,4,4,4,4,4,4], "net_holes": [4,4,4,4,4,4,4,4,4], "strokes": [0]*9, "played": True, "forfeit": False}

    res = me.score_match(ctx, a, b, 1, 2)
    assert res["status"] == "scored"
    # A wins more holes, gets the 5.0 points for holes match
    assert res["a"]["IndividualPts"] == 5.0
    assert res["b"]["IndividualPts"] == 0.0

def test_stableford_points_other_matrix():
    matrix = {
        "DEagle": 8, "Eagle": 5, "Birdie": 2, "Par": 0, "Bogie": -1, "Double": -3, "Triple": -3
    }
    net_or_gross = [3, 4, 5, 6, 3, 4, 0, 10, 8]
    pars =         [4, 4, 4, 4, 3, 3, 3, 4,  5]
    # diffs: -1, 0, 1, 2, 0, 1, None, 6, 3
    # pts: 2, 0, -1, -3, 0, -1, 0, -3, -3
    assert me.stableford_points(net_or_gross, pars, matrix) == -9

    # Check eagle and double eagle
    matrix2 = {
        "DEagle": 10, "Eagle": 5, "Birdie": 2, "Par": 0, "Bogie": -1, "Double": -3, "Triple": -5
    }
    net2 = [2, 3, 7]
    pars2 = [5, 5, 4]
    # diffs: -3 (DEagle), -2 (Eagle), 3 (Triple)
    # pts: 10 + 5 + -5 = 10
    assert me.stableford_points(net2, pars2, matrix2) == 10

def test_rules_summary_other_branches():
    ctx = {
        "scoring_mode": 4,
        "scoring_mode_name": "nines_plus_match",
        "adjust_mode": 3,
        "adjust_mode_name": "usga_esc",
        "stableford": {},
        "stableford_source": "default",
        "divisions": ["A"],
        "num_man_teams": 2,
        "league": {
            "FirstTeeTime": "05:30 PM",
            "MinsBetweenGroups": 10,
            "SubPercent": 100
        },
        "rules": {
            "IndPtsNet": 1.0,
            "IndPtsAct": 2.0,
            "IndPtsNetMatch": 0.0,
            "IndPtsActMatch": 2.0,
            "IndPtsHolesMatch": 3.0,
            "IndPtsNetField": 4.0,
            "IndNetFieldDiff": 0.5,
            "TeamPtsNetMatch": 0.0,
            "TeamPtsHolesMatch": 0.0,
            "PlayerForfeit": 0.0,
        }
    }
    summary = me.rules_summary(ctx)
    assert summary["scoring_mode"] == 4
    assert "1 pt per nine (low net), 3 pts for the 18-hole net holes-won match" in summary["human_rules"]
    assert "Field points 4 / -0.5 per place on net" in summary["human_rules"]

def test_rules_summary_more_branches():
    ctx = {
        "scoring_mode": 1,
        "scoring_mode_name": "stroke_play_field",
        "adjust_mode": 3,
        "adjust_mode_name": "usga_esc",
        "stableford": {},
        "stableford_source": "default",
        "divisions": ["A"],
        "num_man_teams": 2,
        "league": {
            "FirstTeeTime": "05:30 PM",
            "MinsBetweenGroups": 10,
            "SubPercent": 100
        },
        "rules": {
            "IndPtsNet": 0.0,
            "IndPtsAct": 2.0,
            "IndPtsNetMatch": 0.0,
            "IndPtsActMatch": 3.0,
            "IndPtsHolesMatch": 0.0,
            "IndPtsNetField": 0.0,
            "IndNetFieldDiff": 0.0,
            "TeamPtsNetMatch": 0.0,
            "TeamPtsHolesMatch": 0.0,
            "PlayerForfeit": 0.0,
        }
    }
    summary = me.rules_summary(ctx)
    assert summary["scoring_mode"] == 1
    assert "2 pts per gross hole won (ties split)" in summary["human_rules"]
    assert "3 pts for low gross round" in summary["human_rules"]

def test_compute_next_handicap():
    assert me.compute_next_handicap(5.0, 1.0) == 4.0
    assert me.compute_next_handicap(5.0, -1.0) == 6.0
    assert me.compute_next_handicap(5.0, 0.0) == 5.0

def test_score_ecgc_2person_match_unplayed_sub():
    team_a = {
        "team_id": 1,
        "team_name": "Team A",
        "player1": {"id": 1, "name": "P1", "handicap": 5.0, "unplayed": True},
        "player2": {"id": 2, "name": "P2", "handicap": 5.0, "is_sub": True, "gross_scores": [4,4,4,4,4,4,4,4,4]}
    }
    team_b = {
        "team_id": 2,
        "team_name": "Team B",
        "player1": {"id": 3, "name": "P3", "handicap": 5.0, "gross_scores": [5,5,5,5,5,5,5,5,5]},
        "player2": {"id": 4, "name": "P4", "handicap": 5.0, "gross_scores": [5,5,5,5,5,5,5,5,5]}
    }
    rules = {
        "points_per_hole_win": 1.0,
        "points_per_hole_tie": 0.5,
        "net_bonus_below_max": 35,
        "net_bonus_pts": 1.0,
        "net_even_min": 36,
        "net_even_max": 36,
        "net_even_pts": 0.0,
        "net_penalty_above_min": 37,
        "net_penalty_pts": -1.0,
    }
    pars = [4]*9
    ranks = [1,2,3,4,5,6,7,8,9]
    res = me.score_ecgc_2person_match(team_a, team_b, ranks, pars, rules)
    assert res["status"] == "scored"
    assert res["team_a"]["player1"]["unplayed"] is True
    assert res["team_a"]["player1"]["net_total"] == -36
    assert res["team_a"]["player1"]["pt"] == 0.0

def test_score_ecgc_2person_match_tie():
    team_a = {
        "team_id": 1,
        "team_name": "Team A",
        "player1": {"id": 1, "name": "P1", "handicap": 0.0, "gross_scores": [4]*9},
        "player2": {"id": 2, "name": "P2", "handicap": 0.0, "gross_scores": [4]*9}
    }
    team_b = {
        "team_id": 2,
        "team_name": "Team B",
        "player1": {"id": 3, "name": "P3", "handicap": 0.0, "gross_scores": [4]*9},
        "player2": {"id": 4, "name": "P4", "handicap": 0.0, "gross_scores": [4]*9}
    }
    rules = {
        "points_per_hole_win": 1.0,
        "points_per_hole_tie": 0.5,
        "net_bonus_below_max": 35,
        "net_bonus_pts": 1.0,
        "net_even_min": 36,
        "net_even_max": 36,
        "net_even_pts": 0.0,
        "net_penalty_above_min": 37,
        "net_penalty_pts": -1.0,
    }
    pars = [4]*9
    ranks = [1,2,3,4,5,6,7,8,9]
    res = me.score_ecgc_2person_match(team_a, team_b, ranks, pars, rules)
    assert res["match_winner"] == "tie"
    assert res["team_a"]["total_points"] == 4.5
    assert res["team_b"]["total_points"] == 4.5

def test_strokes_per_hole_negative_handicap():
    ranks = [9, 1, 8, 2, 7, 3, 6, 4, 5]
    # For a +2 handicap, we give strokes back on the easiest holes (ranks 9 and 8)
    assert me.strokes_per_hole(-2.0, ranks, 9) == [-1, 0, -1, 0, 0, 0, 0, 0, 0]
    # For a +12 handicap, we give back 1 on all, and an extra 1 on easiest 3 (ranks 9, 8, 7)
    assert me.strokes_per_hole(-12.0, ranks, 9) == [-2, -1, -2, -1, -2, -1, -1, -1, -1]

def test_score_ecgc_2person_match_negative_diff():
    team_a = {
        "team_id": 1,
        "team_name": "Team A",
        "player1": {"id": 1, "name": "P1", "handicap": 0.0, "gross_scores": [4]*9},
        "player2": {"id": 2, "name": "P2", "handicap": 0.0, "gross_scores": [4]*9}
    }
    team_b = {
        "team_id": 2,
        "team_name": "Team B",
        "player1": {"id": 3, "name": "P3", "handicap": 5.0, "gross_scores": [5]*9},
        "player2": {"id": 4, "name": "P4", "handicap": 5.0, "gross_scores": [5]*9}
    }
    rules = {
        "points_per_hole_win": 1.0,
        "points_per_hole_tie": 0.5,
        "net_bonus_below_max": 35,
        "net_bonus_pts": 1.0,
        "net_even_min": 36,
        "net_even_max": 36,
        "net_even_pts": 0.0,
        "net_penalty_above_min": 37,
        "net_penalty_pts": -1.0,
    }
    pars = [4]*9
    ranks = [1,2,3,4,5,6,7,8,9]
    res = me.score_ecgc_2person_match(team_a, team_b, ranks, pars, rules)
    assert res["match_winner"] == "team_a"
    assert res["team_b"]["diff_strokes"] == 10



def test_scheduled_nine():
    import sqlite3

    from app import match_engine as me

    conn = sqlite3.connect(":memory:")

    # Default is front
    assert me.scheduled_nine(conn, 1, 1) == "front"
    # SchedNine table exists, but no rows
    conn.execute('CREATE TABLE "1SchedNine" ("WeekNum" INTEGER, "Match1" INTEGER)')
    assert me.scheduled_nine(conn, 1, 1) == "front"
    # SchedNine has row, match1 = 2 (back)
    conn.execute('INSERT INTO "1SchedNine" ("WeekNum", "Match1") VALUES (1, 2)')
    assert me.scheduled_nine(conn, 1, 1) == "back"
    # SchedNine has row, match1 = 1 (front)
    conn.execute('UPDATE "1SchedNine" SET "Match1" = 1 WHERE "WeekNum" = 1')
    assert me.scheduled_nine(conn, 1, 1) == "front"


def test_matchsetup_pairs():
    import sqlite3

    from app import match_engine as me

    conn = sqlite3.connect(":memory:")

    assert me.matchsetup_pairs(conn, 1, 1) == []

    conn.execute('CREATE TABLE "1MatchSetup" ("WeekNum" INTEGER, "ID1" INTEGER, "ID2" INTEGER, "ID3" INTEGER, "ID4" INTEGER, "ID5" INTEGER, "ID6" INTEGER)')
    assert me.matchsetup_pairs(conn, 1, 1) == []

    # Foursome [1, 2, 3, 4] -> (1, 3), (2, 4). Twosome [5, 6] -> (5, 6)
    conn.execute('INSERT INTO "1MatchSetup" ("WeekNum", "ID1", "ID2", "ID3", "ID4", "ID5", "ID6") VALUES (1, 1, 2, 3, 4, 5, 6)')
    assert me.matchsetup_pairs(conn, 1, 1) == [(1, 3), (2, 4), (5, 6)]


def test_resolve_pairs():
    import sqlite3

    from app import match_engine as me

    conn = sqlite3.connect(":memory:")

    ctx = {"players": [{"PlayerID": 1, "Handicap": 10.0}, {"PlayerID": 2, "Handicap": 12.0}], "num_man_teams": 1}
    entries = {
        1: {"OpponentID": 2},
        2: {"OpponentID": 1},
    }
    pairs, source = me.resolve_pairs(ctx, conn, 1, 1, entries)
    assert source == "PlayerResults.OpponentID"
    assert pairs == [(1, 2)] or pairs == [(2, 1)]

    entries2 = {
        1: {"OpponentID": 0},
        2: {"OpponentID": 0},
    }
    pairs, source = me.resolve_pairs(ctx, conn, 1, 1, entries2)
    assert source == "auto_handicap_order"
    assert pairs == [(1, 2)]


def test_load_week_entries():
    import sqlite3

    from app import match_engine as me

    conn = sqlite3.connect(":memory:")

    # mock context
    ctx = {
        "num_holes": 18,
        "players": [{"PlayerID": 1, "Handicap": 10.0, "PlayerFirst": "John", "PlayerLast": "Doe"}],
        "league": {"SubPercent": 100},
        "pars18": [4]*18,
        "caps18": list(range(1, 19)),
        "adjust_mode": 1,
        "stableford": {}
    }
    # No tables
    assert me.load_week_entries(conn, ctx, 1, 1) == {}

    conn.execute('CREATE TABLE "1PlayerResults" ("WeekNum" INTEGER, "PlayerID" INTEGER, "1" INTEGER, "Sub" INTEGER, "Forfeit" INTEGER)')
    conn.execute('INSERT INTO "1PlayerResults" ("WeekNum", "PlayerID", "1", "Sub", "Forfeit") VALUES (1, 1, 4, 1, 0)')

    conn.execute('CREATE TABLE "1SubResults" ("WeekNum" INTEGER, "PlayerID" INTEGER, "SubID" INTEGER, "1" INTEGER, "SubCap" REAL)')
    conn.execute('INSERT INTO "1SubResults" ("WeekNum", "PlayerID", "SubID", "1", "SubCap") VALUES (1, 1, 99, 3, 5.0)')

    conn.execute('CREATE TABLE "1Subs" ("SubID" INTEGER, "SubFirst" TEXT, "SubLast" TEXT, "SubHandicap" REAL)')
    conn.execute('INSERT INTO "1Subs" ("SubID", "SubFirst", "SubLast", "SubHandicap") VALUES (99, "Sub", "Bob", 15.0)')

    entries = me.load_week_entries(conn, ctx, 1, 1)
    assert 1 in entries
    assert entries[1]["is_sub"] is True
    assert entries[1]["sub_name"] == "Sub Bob"
    assert entries[1]["Handicap"] == 5.0 # uses subcap
    assert entries[1]["holes"][0] == 3 # uses sub result


def test_load_week_entries_back_and_both():
    import sqlite3

    from app import match_engine as me
    conn = sqlite3.connect(":memory:")

    ctx = {
        "num_holes": 18,
        "players": [
            {"PlayerID": 1, "Handicap": 10.0, "PlayerFirst": "A", "PlayerLast": "B"},
            {"PlayerID": 2, "Handicap": 10.0, "PlayerFirst": "C", "PlayerLast": "D"}
        ],
        "league": {"SubPercent": 100},
        "pars18": [4]*18,
        "caps18": list(range(1, 19)),
        "adjust_mode": 1,
        "stableford": {}
    }

    conn.execute('CREATE TABLE "1PlayerResults" ("WeekNum" INTEGER, "PlayerID" INTEGER, "1" INTEGER, "10" INTEGER, "Sub" INTEGER, "Forfeit" INTEGER)')
    # Player 1 played back nine only (hole 10 = 4)
    conn.execute('INSERT INTO "1PlayerResults" ("WeekNum", "PlayerID", "1", "10", "Sub", "Forfeit") VALUES (1, 1, 0, 4, 0, 0)')
    # Player 2 played both (hole 1 = 4, hole 10 = 4)
    conn.execute('INSERT INTO "1PlayerResults" ("WeekNum", "PlayerID", "1", "10", "Sub", "Forfeit") VALUES (1, 2, 4, 4, 0, 0)')

    entries = me.load_week_entries(conn, ctx, 1, 1)
    assert entries[1]["nine"] == "both"
    assert entries[2]["nine"] == "both"


def test_load_week_entries_front():
    import sqlite3

    from app import match_engine as me
    conn = sqlite3.connect(":memory:")

    ctx = {
        "num_holes": 9,
        "players": [
            {"PlayerID": 1, "Handicap": 10.0, "PlayerFirst": "A", "PlayerLast": "B"},
        ],
        "league": {"SubPercent": 100},
        "pars18": [4]*18,
        "caps18": list(range(1, 19)),
        "adjust_mode": 1,
        "stableford": {}
    }

    conn.execute('CREATE TABLE "1PlayerResults" ("WeekNum" INTEGER, "PlayerID" INTEGER, "1" INTEGER, "Sub" INTEGER, "Forfeit" INTEGER)')
    conn.execute('INSERT INTO "1PlayerResults" ("WeekNum", "PlayerID", "1", "Sub", "Forfeit") VALUES (1, 1, 4, 0, 0)')

    entries = me.load_week_entries(conn, ctx, 1, 1)
    assert entries[1]["nine"] == "front"


def test_auto_pairs():
    import sqlite3

    from app import match_engine as me

    conn = sqlite3.connect(":memory:")

    ctx = {
        "num_man_teams": 2,
        "players": [
            {"PlayerID": 1, "TeamID": 1, "Handicap": 10.0},
            {"PlayerID": 2, "TeamID": 1, "Handicap": 12.0},
            {"PlayerID": 3, "TeamID": 2, "Handicap": 10.0},
            {"PlayerID": 4, "TeamID": 2, "Handicap": 12.0}
        ]
    }

    conn.execute('CREATE TABLE "1Schedule" ("WeekNum" INTEGER, "Match1Team1" INTEGER, "Match1Team2" INTEGER)')
    conn.execute('INSERT INTO "1Schedule" ("WeekNum", "Match1Team1", "Match1Team2") VALUES (1, 1, 2)')

    pairs = me.auto_pairs(ctx, conn, 1, 1, {})
    assert pairs == [(1, 3), (2, 4)]

    ctx["num_man_teams"] = 1
    pairs = me.auto_pairs(ctx, conn, 1, 1, {})
    assert pairs == [(1, 3), (2, 4)]


def test_compute_week():
    import sqlite3

    from app import match_engine as me
    conn = sqlite3.connect(":memory:")

    conn.execute('CREATE TABLE "Leagues" ("LeagueID" INTEGER, "LeagueName" TEXT, "LeagueHoles" INTEGER, "SubPercent" INTEGER, "NumManTeams" INTEGER)')
    conn.execute('INSERT INTO "Leagues" ("LeagueID", "LeagueName", "LeagueHoles", "SubPercent", "NumManTeams") VALUES (1, "Test League", 18, 100, 2)')

    conn.execute('CREATE TABLE "LeagueRules" ("LeagueID" INTEGER, "IndPtsNet" REAL)')
    conn.execute('INSERT INTO "LeagueRules" ("LeagueID", "IndPtsNet") VALUES (1, 1.0)')

    conn.execute('CREATE TABLE "Courses" ("CourseID" INTEGER, "CourseName" TEXT)')
    conn.execute('INSERT INTO "Courses" ("CourseID", "CourseName") VALUES (1, "Test Course")')

    conn.execute('CREATE TABLE "1Players" ("PlayerID" INTEGER, "PlayerFirst" TEXT, "PlayerLast" TEXT, "Handicap" REAL, "TeamID" INTEGER, "Division" TEXT)')
    conn.execute('INSERT INTO "1Players" ("PlayerID", "PlayerFirst", "PlayerLast", "Handicap", "TeamID", "Division") VALUES (1, "John", "Doe", 10.0, 1, "A")')
    conn.execute('INSERT INTO "1Players" ("PlayerID", "PlayerFirst", "PlayerLast", "Handicap", "TeamID", "Division") VALUES (2, "Jane", "Doe", 12.0, 2, "A")')

    conn.execute('CREATE TABLE "1Teams" ("TeamID" INTEGER, "TeamName" TEXT)')
    conn.execute('INSERT INTO "1Teams" ("TeamID", "TeamName") VALUES (1, "Team 1")')
    conn.execute('INSERT INTO "1Teams" ("TeamID", "TeamName") VALUES (2, "Team 2")')

    conn.execute('CREATE TABLE "CourseYards" ("CourseID" INTEGER)')
    conn.execute('CREATE TABLE "CourseHandicap" ("CourseID" INTEGER)')
    conn.execute('CREATE TABLE "CoursePar" ("CourseID" INTEGER)')
    conn.execute('CREATE TABLE "CourseHoles" ("CourseID" INTEGER, "HoleNumber" INTEGER, "Par" INTEGER, "HandicapRank" INTEGER)')
    for i in range(1, 19):
        conn.execute('INSERT INTO "CourseHoles" ("CourseID", "HoleNumber", "Par", "HandicapRank") VALUES (1, ?, 4, ?)', (i, i))

    conn.execute('CREATE TABLE "1Schedule" ("WeekNum" INTEGER, "Match1Team1" INTEGER, "Match1Team2" INTEGER)')
    conn.execute('INSERT INTO "1Schedule" ("WeekNum", "Match1Team1", "Match1Team2") VALUES (1, 1, 2)')

    # Sub tables
    conn.execute('CREATE TABLE "1Subs" ("SubID" INTEGER, "SubFirst" TEXT, "SubLast" TEXT, "SubHandicap" REAL)')
    conn.execute('INSERT INTO "1Subs" ("SubID", "SubFirst", "SubLast", "SubHandicap") VALUES (99, "Sub", "Bob", 15.0)')

    conn.execute('CREATE TABLE "1SubResults" ("WeekNum" INTEGER, "PlayerID" INTEGER, "SubID" INTEGER, ' + ', '.join([f'"{i}" INTEGER' for i in range(1, 19)]) + ', "SubCap" REAL)')
    conn.execute('INSERT INTO "1SubResults" ("WeekNum", "PlayerID", "SubID", ' + ', '.join([f'"{i}"' for i in range(1, 19)]) + ', "SubCap") VALUES (1, 1, 99, ' + ', '.join(['3' for _ in range(18)]) + ', 5.0)')

    conn.execute('CREATE TABLE "1PlayerResults" ("WeekNum" INTEGER, "PlayerID" INTEGER, "Sub" INTEGER, "Forfeit" INTEGER, ' + ', '.join([f'"{i}" INTEGER' for i in range(1, 19)]) + ')')
    # Player 1 is a sub
    conn.execute('INSERT INTO "1PlayerResults" ("WeekNum", "PlayerID", "Sub", "Forfeit", ' + ', '.join([f'"{i}"' for i in range(1, 19)]) + ') VALUES (1, 1, 1, 0, ' + ', '.join(['0' for _ in range(18)]) + ')')
    # Player 2 is normal
    conn.execute('INSERT INTO "1PlayerResults" ("WeekNum", "PlayerID", "Sub", "Forfeit", ' + ', '.join([f'"{i}"' for i in range(1, 19)]) + ') VALUES (1, 2, 0, 0, ' + ', '.join(['4' for _ in range(18)]) + ')')

    res = me.compute_week(conn, 1, 1)

    assert "matches" in res
    assert "entries" in res

    matches = res["matches"]
    assert len(matches) == 1
    assert matches[0]["a"]["PlayerID"] == 1
    assert matches[0]["b"]["PlayerID"] == 2

    entries = res["entries"]
    assert entries[1]["is_sub"] is True
    assert entries[1]["sub_name"] == "Sub Bob"
    assert entries[1]["Handicap"] == 5.0

    # Also test team_results
    assert "team_results" in res
    assert len(res["team_results"]) == 2
    assert res["team_results"][0]["TeamID"] == 1
    assert res["team_results"][0]["players_played"] == 1
    assert res["team_results"][1]["TeamID"] == 2
    assert res["team_results"][1]["players_played"] == 1

def test_auto_score_week():
    import sqlite3
    from app.match_engine import auto_score_week

    conn = sqlite3.connect(":memory:")

    conn.execute("CREATE TABLE Leagues (LeagueID INTEGER, LeagueName TEXT, LeagueHoles INTEGER, SubPercent INTEGER, NumManTeams INTEGER)")
    conn.execute("INSERT INTO Leagues (LeagueID, LeagueName, LeagueHoles, SubPercent, NumManTeams) VALUES (1, 'Test League', 18, 100, 2)")

    conn.execute("CREATE TABLE LeagueRules (LeagueID INTEGER, IndPtsNet REAL)")
    conn.execute("INSERT INTO LeagueRules (LeagueID, IndPtsNet) VALUES (1, 1.0)")

    conn.execute("CREATE TABLE Courses (CourseID INTEGER, CourseName TEXT)")
    conn.execute("INSERT INTO Courses (CourseID, CourseName) VALUES (1, 'Test Course')")

    conn.execute("CREATE TABLE \"1Players\" (PlayerID INTEGER, PlayerFirst TEXT, PlayerLast TEXT, Handicap REAL, TeamID INTEGER, Division TEXT, Points REAL)")
    conn.execute("INSERT INTO \"1Players\" (PlayerID, PlayerFirst, PlayerLast, Handicap, TeamID, Division, Points) VALUES (1, 'John', 'Doe', 10.0, 1, 'A', 0)")
    conn.execute("INSERT INTO \"1Players\" (PlayerID, PlayerFirst, PlayerLast, Handicap, TeamID, Division, Points) VALUES (2, 'Jane', 'Doe', 12.0, 2, 'A', 0)")

    conn.execute("CREATE TABLE \"1Teams\" (TeamID INTEGER, TeamName TEXT, Points REAL)")
    conn.execute("INSERT INTO \"1Teams\" (TeamID, TeamName, Points) VALUES (1, 'Team 1', 0)")
    conn.execute("INSERT INTO \"1Teams\" (TeamID, TeamName, Points) VALUES (2, 'Team 2', 0)")

    conn.execute("CREATE TABLE CourseYards (CourseID INTEGER)")
    conn.execute("CREATE TABLE CourseHandicap (CourseID INTEGER)")
    conn.execute("CREATE TABLE CoursePar (CourseID INTEGER)")
    conn.execute("CREATE TABLE CourseHoles (CourseID INTEGER, HoleNumber INTEGER, Par INTEGER, HandicapRank INTEGER)")
    for i in range(1, 19):
        conn.execute("INSERT INTO CourseHoles (CourseID, HoleNumber, Par, HandicapRank) VALUES (1, ?, 4, ?)", (i, i))

    conn.execute("CREATE TABLE \"1Schedule\" (WeekNum INTEGER, Match1Team1 INTEGER, Match1Team2 INTEGER)")
    conn.execute("INSERT INTO \"1Schedule\" (WeekNum, Match1Team1, Match1Team2) VALUES (1, 1, 2)")

    # Sub tables
    conn.execute("CREATE TABLE \"1Subs\" (SubID INTEGER, SubFirst TEXT, SubLast TEXT, SubHandicap REAL)")
    conn.execute("INSERT INTO \"1Subs\" (SubID, SubFirst, SubLast, SubHandicap) VALUES (99, 'Sub', 'Bob', 15.0)")

    conn.execute("CREATE TABLE \"1SubResults\" (WeekNum INTEGER, PlayerID INTEGER, SubID INTEGER, " + ", ".join([f'"{i}" INTEGER' for i in range(1, 19)]) + ", SubCap REAL)")
    conn.execute("INSERT INTO \"1SubResults\" (WeekNum, PlayerID, SubID, " + ", ".join([f'"{i}"' for i in range(1, 19)]) + ", SubCap) VALUES (1, 1, 99, " + ", ".join(["3" for _ in range(18)]) + ", 5.0)")

    conn.execute("CREATE TABLE \"1PlayerResults\" (WeekNum INTEGER, PlayerID INTEGER, Sub INTEGER, Forfeit INTEGER, OpponentID INTEGER, IndividualPts REAL, FieldPts REAL, " + ", ".join([f'"{i}" INTEGER' for i in range(1, 19)]) + ")")
    # Player 1 is a sub
    conn.execute("INSERT INTO \"1PlayerResults\" (WeekNum, PlayerID, Sub, Forfeit, " + ", ".join([f'"{i}"' for i in range(1, 19)]) + ") VALUES (1, 1, 1, 0, " + ", ".join(["0" for _ in range(18)]) + ")")
    # Player 2 is normal
    conn.execute("INSERT INTO \"1PlayerResults\" (WeekNum, PlayerID, Sub, Forfeit, " + ", ".join([f'"{i}"' for i in range(1, 19)]) + ") VALUES (1, 2, 0, 0, " + ", ".join(["4" for _ in range(18)]) + ")")

    conn.execute("CREATE TABLE \"1TeamResults\" (WeekNum INTEGER, TeamID INTEGER, TeamPts REAL, MatchPts REAL, FieldPts REAL, TeamActual INTEGER, TeamNet INTEGER, SubPts INTEGER, UserDefinedPts INTEGER)")

    conn.execute("CREATE TABLE \"1AdjScores\" (WeekNum INTEGER, ID1 INTEGER, ID2 INTEGER)")
    conn.execute("CREATE TABLE \"1ActScores\" (WeekNum INTEGER, ID1 INTEGER, ID2 INTEGER)")
    conn.execute("CREATE TABLE \"1Handicaps\" (WeekNum INTEGER, ID1 INTEGER, ID2 INTEGER)")
    conn.execute("CREATE TABLE \"1AdjOverPar\" (WeekNum INTEGER, ID1 INTEGER, ID2 INTEGER)")

    res = auto_score_week(conn, 1, 1)

    assert res["persisted"] is True

    # Run it again to test update path
    res2 = auto_score_week(conn, 1, 1)
    assert res2["persisted"] is True



@pytest.fixture
def clubhouse_db(monkeypatch):
    import datetime
    class MockDatetime(datetime.datetime):
        @classmethod
        def utcnow(cls):
            return cls(2023, 1, 1, 12, 0, 0)
    monkeypatch.setattr('app.match_engine.datetime', MockDatetime)

    import sqlite3
    conn = sqlite3.connect(":memory:")

    conn.execute("CREATE TABLE Leagues (LeagueID INTEGER, LeagueName TEXT, LeagueHoles INTEGER, SubPercent INTEGER, NumManTeams INTEGER, FirstTeeTime TEXT, MinsBetweenGroups INTEGER)")
    conn.execute("INSERT INTO Leagues (LeagueID, LeagueName, LeagueHoles, SubPercent, NumManTeams, FirstTeeTime, MinsBetweenGroups) VALUES (1, 'Test League', 18, 100, 2, '08:00 AM', 10)")

    conn.execute("CREATE TABLE LeagueRules (LeagueID INTEGER, IndPtsNet REAL)")
    conn.execute("INSERT INTO LeagueRules (LeagueID, IndPtsNet) VALUES (1, 1.0)")

    conn.execute("CREATE TABLE Courses (CourseID INTEGER, CourseName TEXT)")
    conn.execute("INSERT INTO Courses (CourseID, CourseName) VALUES (1, 'Test Course')")

    conn.execute("CREATE TABLE \"1Players\" (PlayerID INTEGER, PlayerFirst TEXT, PlayerLast TEXT, Handicap REAL, TeamID INTEGER, Division TEXT, Points REAL)")
    conn.execute("INSERT INTO \"1Players\" (PlayerID, PlayerFirst, PlayerLast, Handicap, TeamID, Division, Points) VALUES (1, 'John', 'Doe', 10.0, 1, 'A', 0)")
    conn.execute("INSERT INTO \"1Players\" (PlayerID, PlayerFirst, PlayerLast, Handicap, TeamID, Division, Points) VALUES (2, 'Jane', 'Doe', 12.0, 2, 'A', 0)")
    conn.execute("INSERT INTO \"1Players\" (PlayerID, PlayerFirst, PlayerLast, Handicap, TeamID, Division, Points) VALUES (3, 'A', 'B', 10.0, 3, 'A', 0)")
    conn.execute("INSERT INTO \"1Players\" (PlayerID, PlayerFirst, PlayerLast, Handicap, TeamID, Division, Points) VALUES (4, 'C', 'D', 10.0, 4, 'A', 0)")

    conn.execute("CREATE TABLE \"1Teams\" (TeamID INTEGER, TeamName TEXT, Points REAL)")
    conn.execute("INSERT INTO \"1Teams\" (TeamID, TeamName, Points) VALUES (1, 'Team 1', 0)")
    conn.execute("INSERT INTO \"1Teams\" (TeamID, TeamName, Points) VALUES (2, 'Team 2', 0)")
    conn.execute("INSERT INTO \"1Teams\" (TeamID, TeamName, Points) VALUES (3, 'Team 3', 0)")
    conn.execute("INSERT INTO \"1Teams\" (TeamID, TeamName, Points) VALUES (4, 'Team 4', 0)")

    conn.execute("CREATE TABLE CourseYards (CourseID INTEGER)")
    conn.execute("CREATE TABLE CourseHandicap (CourseID INTEGER)")
    conn.execute("CREATE TABLE CoursePar (CourseID INTEGER)")
    conn.execute("CREATE TABLE CourseHoles (CourseID INTEGER, HoleNumber INTEGER, Par INTEGER, HandicapRank INTEGER)")
    for i in range(1, 19):
        conn.execute("INSERT INTO CourseHoles (CourseID, HoleNumber, Par, HandicapRank) VALUES (1, ?, 4, ?)", (i, i))

    conn.execute("CREATE TABLE \"1Schedule\" (WeekNum INTEGER, Match1Team1 INTEGER, Match1Team2 INTEGER, Match2Team1 INTEGER, Match2Team2 INTEGER, Date TEXT, Weather TEXT)")

    conn.execute("CREATE TABLE \"1Scorecards\" (WeekNum INTEGER, PlayerID INTEGER, Hole1 INTEGER, Hole2 INTEGER, Hole3 INTEGER, Hole4 INTEGER, Hole5 INTEGER, Hole6 INTEGER, Hole7 INTEGER, Hole8 INTEGER, Hole9 INTEGER, Hole10 INTEGER, Hole11 INTEGER, Hole12 INTEGER, Hole13 INTEGER, Hole14 INTEGER, Hole15 INTEGER, Hole16 INTEGER, Hole17 INTEGER, Hole18 INTEGER)")

    conn.execute("CREATE TABLE \"1PlayerResults\" (WeekNum INTEGER, PlayerID INTEGER, Sub INTEGER, Forfeit INTEGER, OpponentID INTEGER, IndividualPts REAL, FieldPts REAL, " + ", ".join([f'"{i}" INTEGER' for i in range(1, 19)]) + ")")
    conn.execute("INSERT INTO \"1PlayerResults\" (WeekNum, PlayerID, Sub, Forfeit, " + ", ".join([f'"{i}"' for i in range(1, 19)]) + ") VALUES (1, 1, 0, 0, " + ", ".join(["4" for _ in range(18)]) + ")")
    conn.execute("INSERT INTO \"1PlayerResults\" (WeekNum, PlayerID, Sub, Forfeit, " + ", ".join([f'"{i}"' for i in range(1, 19)]) + ") VALUES (1, 2, 0, 0, " + ", ".join(["5" for _ in range(18)]) + ")")
    conn.execute("INSERT INTO \"1PlayerResults\" (WeekNum, PlayerID, Sub, Forfeit, " + ", ".join([f'"{i}"' for i in range(1, 19)]) + ") VALUES (1, 3, 0, 0, " + ", ".join(["4" for _ in range(18)]) + ")")
    conn.execute("INSERT INTO \"1PlayerResults\" (WeekNum, PlayerID, Sub, Forfeit, " + ", ".join([f'"{i}"' for i in range(1, 19)]) + ") VALUES (1, 4, 0, 0, " + ", ".join(["5" for _ in range(18)]) + ")")

    return conn

@pytest.mark.parametrize("scenario", [
    "normal", "edge_cases", "fallback", "while_loop", "while_fallback"
])
def test_clubhouse_sheet_scenarios(clubhouse_db, scenario):
    from app.match_engine import clubhouse_sheet
    conn = clubhouse_db

    if scenario == "normal":
        conn.execute("INSERT INTO \"1Schedule\" (WeekNum, Match1Team1, Match1Team2, Date, Weather) VALUES (1, 1, 2, '2023-01-01', 'Sunny')")
        conn.execute("CREATE TABLE \"1TeeTimes\" (MatchNum INTEGER, Ttime TEXT)")
        conn.execute("INSERT INTO \"1TeeTimes\" (MatchNum, Ttime) VALUES (1, '08:00 AM')")
        res = clubhouse_sheet(conn, 1, 1)
        assert res["week_num"] == 1
        assert res["league"]["LeagueName"] == 'Test League'

    elif scenario == "edge_cases":
        conn.execute("INSERT INTO \"1Schedule\" (WeekNum, Match1Team1, Match1Team2, Date, Weather) VALUES (1, 1, 2, '2023-01-01', 'Sunny')")
        conn.execute("CREATE TABLE \"1TeeTimes\" (MatchNum INTEGER, Ttime TEXT)")
        conn.execute("INSERT INTO \"1TeeTimes\" (MatchNum, Ttime) VALUES (1, '08:00 AM')")
        res = clubhouse_sheet(conn, 1, 1)
        assert res["week_num"] == 1
        assert len(res["matchups"]) > 0

    elif scenario == "fallback":
        conn.execute("INSERT INTO \"1Schedule\" (WeekNum, Match1Team1, Match1Team2) VALUES (1, 1, 2)")
        res = clubhouse_sheet(conn, 1, 1)
        assert res["week_num"] == 1
        conn.execute("UPDATE Leagues SET FirstTeeTime = NULL")
        res = clubhouse_sheet(conn, 1, 1)
        assert res["week_num"] == 1

    elif scenario == "while_loop":
        conn.execute("INSERT INTO \"1Schedule\" (WeekNum, Match1Team1, Match1Team2, Match2Team1, Match2Team2) VALUES (1, 1, 2, 3, 4)")
        conn.execute("CREATE TABLE \"1TeeTimes\" (MatchNum INTEGER, Ttime TEXT)")
        conn.execute("INSERT INTO \"1TeeTimes\" (MatchNum, Ttime) VALUES (1, '08:00 AM')")
        res = clubhouse_sheet(conn, 1, 1)
        assert res["week_num"] == 1
        conn.execute("DELETE FROM \"1TeeTimes\"")
        conn.execute("UPDATE Leagues SET FirstTeeTime = NULL")
        res = clubhouse_sheet(conn, 1, 1)
        assert res["week_num"] == 1

    elif scenario == "while_fallback":
        conn.execute("INSERT INTO \"1Schedule\" (WeekNum, Match1Team1, Match1Team2, Match2Team1, Match2Team2) VALUES (1, 1, 2, 3, 4)")
        conn.execute("CREATE TABLE \"1TeeTimes\" (MatchNum INTEGER, Ttime TEXT)")
        conn.execute("INSERT INTO \"1TeeTimes\" (MatchNum, Ttime) VALUES (1, '')")
        res = clubhouse_sheet(conn, 1, 1)
        assert res["week_num"] == 1

def test_score_ecgc_2person_match_diff_zero():
    from app.match_engine import score_ecgc_2person_match

    a_entries = {
        "team_name": "Team 1",
        "player1": {"PlayerID": 1, "PlayerFirst": "A", "PlayerLast": "A", "TeamID": 1, "Handicap": 10, "Gross": 36, "AdjGross": 36, "holes": [4]*9, "adj_holes": [4]*9, "played": True, "nine": "front"},
        "player2": {"PlayerID": 2, "PlayerFirst": "B", "PlayerLast": "B", "TeamID": 1, "Handicap": 10, "Gross": 36, "AdjGross": 36, "holes": [4]*9, "adj_holes": [4]*9, "played": True, "nine": "front"}
    }
    b_entries = {
        "team_name": "Team 2",
        "player1": {"PlayerID": 3, "PlayerFirst": "C", "PlayerLast": "C", "TeamID": 2, "Handicap": 10, "Gross": 36, "AdjGross": 36, "holes": [4]*9, "adj_holes": [4]*9, "played": True, "nine": "front"},
        "player2": {"PlayerID": 4, "PlayerFirst": "D", "PlayerLast": "D", "TeamID": 2, "Handicap": 10, "Gross": 36, "AdjGross": 36, "holes": [4]*9, "adj_holes": [4]*9, "played": True, "nine": "front"}
    }

    res = score_ecgc_2person_match(a_entries, b_entries, hole_ranks=[i for i in range(1, 10)], pars=[4]*9, rules={"points_per_hole_win": 1.0, "points_per_hole_tie": 0.5, "net_bonus_pts": 1.0, "net_even_pts": 0.0, "net_penalty_pts": -1.0})

    assert res["status"] == "scored"
    assert res["team_a"]["hole_points"] == 4.5

def test_compute_ecgc_pt_fallthrough():
    from app.match_engine import compute_ecgc_pt
    res = compute_ecgc_pt(35.5, net_bonus_below_max=35, net_even_min=36, net_even_max=36, net_penalty_above_min=37)
    assert res == 0.0


def test_compute_ecgc_pt_missing_args():
    from app.match_engine import compute_ecgc_pt
    res = compute_ecgc_pt(35.0)
    assert res == 1.0
