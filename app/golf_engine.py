"""Clean-room Golf League Secretary (GLS9) V2 Calculation Engine:
- 9-hole & 18-hole Course Par, Yardage, and Handicap Stroke Allocation
- Equitable Stroke Control (ESC / *AdjScores) & Modified Stableford calculation
- Automated Head-to-Head Match Play (*MatchSetup ID1..ID16 + *Schedule auto-pairing, 0.5x tie-splitting)
- Individual Flight Field Points (IndPtsNetField / IndNetFieldDiff for Flight leagues like League 11)
- Weekly Skins (Gross & Net), Team Match Rollups (*TeamResults), and Printable Clubhouse Report
- Configurable League Handicap Formula (PercentHandicap, MaximumHandicap, ESC-adjusted rounds)
- Round-Robin Schedule generation from the 25 GLS9 templates (4team..52team)."""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime, timedelta
from typing import Any


def rows_as_dicts(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    r = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return r is not None


def get_courses(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    courses = rows_as_dicts(conn.execute('SELECT * FROM "Courses" ORDER BY "CourseID"'))
    pars = {r["CourseID"]: r for r in rows_as_dicts(conn.execute('SELECT * FROM "CoursePar"'))}
    caps = {r["CourseID"]: r for r in rows_as_dicts(conn.execute('SELECT * FROM "CourseHandicap"'))}
    yards = {r["CourseID"]: r for r in rows_as_dicts(conn.execute('SELECT * FROM "CourseYards"'))}
    for c in courses:
        cid = c["CourseID"]
        p_row = pars.get(cid, {})
        h_row = caps.get(cid, {})
        y_row = yards.get(cid, {})
        holes = []
        for h in range(1, 19):
            k_par = f"Hole{h:02d}Par"
            k_cap = f"Hole{h:02d}Cap"
            k_yd = f"Hole{h:02d}Yards"
            holes.append({
                "hole": h,
                "par": int(p_row.get(k_par) or 4),
                "handicap_rank": int(h_row.get(k_cap) or h),
                "yards": int(y_row.get(k_yd) or 350),
            })
        c["holes"] = holes
        c["front_par"] = sum(x["par"] for x in holes[:9])
        c["back_par"] = sum(x["par"] for x in holes[9:18])
        c["total_par"] = c["front_par"] + c["back_par"]
    return courses


def strokes_on_hole(player_hcp: float, hole_rank: int, num_holes: int = 18) -> int:
    """Calculate handicap strokes received on a hole given player handicap and hole rank."""
    hcp = max(0, int(round(float(player_hcp or 0))))
    if hcp <= 0:
        return 0
    if num_holes == 9:
        eff_rank = ((hole_rank - 1) // 2) + 1 if hole_rank > 9 else hole_rank
        base = hcp // 9
        rem = hcp % 9
        return base + (1 if eff_rank <= rem else 0)
    base = hcp // 18
    rem = hcp % 18
    return base + (1 if hole_rank <= rem else 0)


def apply_esc_cap(score: int, par: int, player_hcp: float, adjust_mode: int = 1, num_holes: int = 18) -> int:
    """Apply GLS9 Equitable Stroke Control (ESC) cap to a single hole score (AGY-F3 / CLD-F2).
    adjust_mode=0: no cap; adjust_mode=1: Double Bogey max (par+2); adjust_mode=2: USGA ESC by handicap."""
    if score <= 0:
        return 0
    if adjust_mode <= 0:
        return score
    if adjust_mode == 1:
        return min(score, par + 2)
    # USGA ESC (normalized to 18-hole equivalent handicap)
    hcp18 = float(player_hcp or 0) * (2.0 if num_holes == 9 else 1.0)
    if hcp18 <= 9:
        cap = par + 2
    elif hcp18 <= 19:
        cap = 7
    elif hcp18 <= 29:
        cap = 8
    elif hcp18 <= 39:
        cap = 9
    else:
        cap = 10
    return min(score, cap)


def hole_stableford_pts(score: int, par: int) -> int:
    """Modified Stableford points for a hole (Eagle+ = 4, Birdie = 2, Par = 1, Bogey = 0, Double+ = -1)."""
    if score <= 0:
        return 0
    diff = score - par
    if diff <= -3:
        return 5
    if diff == -2:
        return 4
    if diff == -1:
        return 2
    if diff == 0:
        return 1
    if diff == 1:
        return 0
    return -1


def build_rules_summary(league: dict[str, Any], rules: dict[str, Any], fees: list[dict[str, Any]]) -> dict[str, Any]:
    """Normalize ground-truth Leagues + LeagueRules + *LeagueFees columns for UI & reports (AGY-F1)."""
    hole_pts = float(rules.get("IndPtsNet") or rules.get("IndPtsAct") or 1.0)
    ind_match_pts = float(rules.get("IndPtsHolesMatch") or rules.get("IndPtsNetMatch") or rules.get("IndPtsActMatch") or 2.0)
    team_match_pts = float(rules.get("TeamPtsNetMatch") or rules.get("TeamPtsHolesMatch") or rules.get("TeamPtsActMatch") or 4.0)
    field_top_pts = float(rules.get("IndPtsNetField") or rules.get("IndPtsActField") or 0.0)
    field_step = float(rules.get("IndNetFieldDiff") or rules.get("IndActFieldDiff") or 2.0)

    sample_fee = fees[0] if fees else {}
    divs = [league.get(f"Div{i}") for i in range(1, 5) if league.get(f"Div{i}") not in (None, "", "NA")]

    return {
        "LeagueDay": league.get("LeagueDay") or "Weekly",
        "FirstTeeTime": league.get("FirstTeeTime") or "05:00 PM",
        "MinsBetweenGroups": int(league.get("MinsBetweenGroups") or 9),
        "NumManTeams": int(league.get("NumManTeams") or 2),
        "PercentHandicap": float(league.get("PercentHandicap") or 90),
        "MaximumHandicap": float(league.get("MaximumHandicap") or 18),
        "AdjustScores": int(league.get("AdjustScores") or 1),
        "AdjustScoresLabel": "USGA ESC by Hcp" if int(league.get("AdjustScores") or 1) == 2 else "Double Bogey Max",
        "SubPercent": float(league.get("SubPercent") or 100),
        "HolePts": hole_pts,
        "IndMatchPts": ind_match_pts,
        "TeamMatchPts": team_match_pts,
        "FieldTopPts": field_top_pts,
        "FieldStepPts": field_step,
        "PlayerForfeitPts": float(rules.get("PlayerForfeit") or 0),
        "TeamForfeitPts": float(rules.get("TeamForfeit") or 0),
        "PresentPlayerPts": float(rules.get("PresentPlayerPts") or 0),
        "PresentTeamPts": float(rules.get("PresentTeamPts") or 0),
        "GreenFees": float(sample_fee.get("GreenFees") or 0),
        "LeagueFee": float(sample_fee.get("LeagueFee") or 0),
        "SkinsFee": float(sample_fee.get("SkinsFee") or 0),
        "BanquetFee": float(sample_fee.get("BanquetFee") or 0),
        "Divisions": divs or ["Open Flight"],
    }


def get_league_standings(conn: sqlite3.Connection, lid: int) -> dict[str, Any]:
    leagues = rows_as_dicts(conn.execute('SELECT * FROM "Leagues" WHERE "LeagueID"=?', (lid,)))
    if not leagues:
        raise KeyError(f"League {lid} not found")
    league = leagues[0]
    rules_rows = rows_as_dicts(conn.execute('SELECT * FROM "LeagueRules" WHERE "LeagueID"=?', (lid,)))
    rules = rules_rows[0] if rules_rows else {}

    p_tbl = f"{lid}Players"
    t_tbl = f"{lid}Teams"
    s_tbl = f"{lid}Subs"
    f_tbl = f"{lid}LeagueFees"
    pr_tbl = f"{lid}PlayerPrizes"

    players = rows_as_dicts(conn.execute(f'SELECT * FROM "{p_tbl}" ORDER BY "Points" DESC, "Handicap" ASC')) if table_exists(conn, p_tbl) else []
    teams = rows_as_dicts(conn.execute(f'SELECT * FROM "{t_tbl}" ORDER BY "Points" DESC, "PrevPts" DESC')) if table_exists(conn, t_tbl) else []
    subs = rows_as_dicts(conn.execute(f'SELECT * FROM "{s_tbl}" ORDER BY "SubID" ASC')) if table_exists(conn, s_tbl) else []
    fees = rows_as_dicts(conn.execute(f'SELECT * FROM "{f_tbl}" ORDER BY "PlayerID" ASC')) if table_exists(conn, f_tbl) else []
    prizes = rows_as_dicts(conn.execute(f'SELECT * FROM "{pr_tbl}" ORDER BY "WeekNum" ASC')) if table_exists(conn, pr_tbl) else []

    courses = {c["CourseID"]: c for c in get_courses(conn)}
    course = courses.get(league.get("CourseID")) or (list(courses.values())[0] if courses else {})
    rules_summary = build_rules_summary(league, rules, fees)

    return {
        "league": league,
        "rules": rules,
        "rules_summary": rules_summary,
        "course": course,
        "teams": teams,
        "players": players,
        "subs": subs,
        "fees": fees,
        "prizes": prizes,
    }


def _resolve_week_pairings(
    conn: sqlite3.Connection,
    lid: int,
    week_num: int,
    players: list[dict[str, Any]],
    week_sched: dict[str, Any],
) -> list[tuple[int, int]]:
    """Resolve head-to-head player pairings from *MatchSetup (ID1..ID16) or auto-pair from *Schedule teams."""
    ms_tbl = f"{lid}MatchSetup"
    pairs: list[tuple[int, int]] = []
    if table_exists(conn, ms_tbl):
        rows = rows_as_dicts(conn.execute(f'SELECT * FROM "{ms_tbl}" WHERE "WeekNum"=?', (week_num,)))
        if rows:
            ms = rows[0]
            for i in range(1, 32, 2):
                a = int(ms.get(f"ID{i}") or 0)
                b = int(ms.get(f"ID{i+1}") or 0)
                if a > 0 and b > 0:
                    pairs.append((a, b))
    if pairs:
        return pairs

    # Fallback: pair opposing teams' players ordered by handicap ascending
    by_team: dict[int, list[dict[str, Any]]] = {}
    for p in players:
        tid = int(p.get("TeamID") or 0)
        by_team.setdefault(tid, []).append(p)
    for tid in by_team:
        by_team[tid].sort(key=lambda x: (float(x.get("Handicap") or 0), int(x.get("PlayerID") or 0)))

    for m_idx in (1, 2):
        t1 = int(week_sched.get(f"Match{m_idx}Team1") or 0)
        t2 = int(week_sched.get(f"Match{m_idx}Team2") or 0)
        if t1 > 0 and t2 > 0 and t1 in by_team and t2 in by_team:
            for pa, pb in zip(by_team[t1], by_team[t2]):
                pairs.append((int(pa["PlayerID"]), int(pb["PlayerID"])))
    return pairs


def _compute_matchups(
    pairs: list[tuple[int, int]],
    card_by_pid: dict[int, dict[str, Any]],
    holes_meta: list[dict[str, Any]],
    rules_summary: dict[str, Any],
    num_holes: int,
) -> list[dict[str, Any]]:
    """Compute head-to-head hole-by-hole match play results with 0.5x tie-splitting (AGY-F2 / CDX-F1)."""
    hole_pts = float(rules_summary.get("HolePts") or 1.0)
    match_bonus = float(rules_summary.get("IndMatchPts") or 2.0)
    matchups: list[dict[str, Any]] = []

    for pid_a, pid_b in pairs:
        ca = card_by_pid.get(pid_a)
        cb = card_by_pid.get(pid_b)
        if not ca or not cb:
            continue
        hcp_a = float(ca.get("Handicap") or 0)
        hcp_b = float(cb.get("Handicap") or 0)
        low_hcp = min(hcp_a, hcp_b)
        diff_a = max(0.0, hcp_a - low_hcp)
        diff_b = max(0.0, hcp_b - low_hcp)

        holes_won_a = 0
        holes_won_b = 0
        holes_halved = 0
        pts_a = 0.0
        pts_b = 0.0
        hole_details = []

        both_played = ca["Gross"] > 0 and cb["Gross"] > 0
        if both_played:
            for idx, hm in enumerate(holes_meta):
                sa = ca["holes"][idx]
                sb = cb["holes"][idx]
                if sa <= 0 or sb <= 0:
                    continue
                str_a = strokes_on_hole(diff_a, hm["handicap_rank"], num_holes)
                str_b = strokes_on_hole(diff_b, hm["handicap_rank"], num_holes)
                net_a = sa - str_a
                net_b = sb - str_b
                if net_a < net_b:
                    holes_won_a += 1
                    pts_a += hole_pts
                    winner = "A"
                elif net_b < net_a:
                    holes_won_b += 1
                    pts_b += hole_pts
                    winner = "B"
                else:
                    holes_halved += 1
                    pts_a += 0.5 * hole_pts
                    pts_b += 0.5 * hole_pts
                    winner = "HALVED"
                hole_details.append({"hole": hm["hole"], "netA": net_a, "netB": net_b, "winner": winner})

            if holes_won_a > holes_won_b:
                pts_a += match_bonus
                status = f"{ca['PlayerName']} wins +{holes_won_a - holes_won_b} UP"
            elif holes_won_b > holes_won_a:
                pts_b += match_bonus
                status = f"{cb['PlayerName']} wins +{holes_won_b - holes_won_a} UP"
            else:
                pts_a += 0.5 * match_bonus
                pts_b += 0.5 * match_bonus
                status = "All Square (Halved)"
        else:
            status = "Awaiting Scores"

        matchups.append({
            "PlayerA_ID": pid_a,
            "PlayerA_Name": ca["PlayerName"],
            "PlayerA_Team": ca["TeamID"],
            "PlayerA_Hcp": hcp_a,
            "PlayerA_Gross": ca["Gross"],
            "PlayerA_Net": ca["Net"],
            "PlayerB_ID": pid_b,
            "PlayerB_Name": cb["PlayerName"],
            "PlayerB_Team": cb["TeamID"],
            "PlayerB_Hcp": hcp_b,
            "PlayerB_Gross": cb["Gross"],
            "PlayerB_Net": cb["Net"],
            "holes_won_a": holes_won_a,
            "holes_won_b": holes_won_b,
            "holes_halved": holes_halved,
            "computed_pts_a": round(pts_a, 2),
            "computed_pts_b": round(pts_b, 2),
            "status": status,
            "hole_details": hole_details,
        })
    return matchups


def _compute_field_points(scorecards: list[dict[str, Any]], rules_summary: dict[str, Any]) -> dict[int, float]:
    """Compute stepped Field Points (IndPtsNetField / IndNetFieldDiff) with tie-splitting (CDX-F2)."""
    top_pts = float(rules_summary.get("FieldTopPts") or 0.0)
    step = float(rules_summary.get("FieldStepPts") or 2.0)
    if top_pts <= 0:
        return {}
    active = [c for c in scorecards if c["Gross"] > 0]
    active.sort(key=lambda c: c["Net"])
    n = len(active)
    slot_pts = [max(0.0, top_pts - i * step) for i in range(n)]
    out: dict[int, float] = {}
    i = 0
    while i < n:
        j = i
        while j < n and active[j]["Net"] == active[i]["Net"]:
            j += 1
        avg_p = sum(slot_pts[i:j]) / (j - i)
        for k in range(i, j):
            out[int(active[k]["PlayerID"])] = round(avg_p, 2)
        i = j
    return out


def get_week_scorecard(conn: sqlite3.Connection, lid: int, week_num: int) -> dict[str, Any]:
    st = get_league_standings(conn, lid)
    league = st["league"]
    rules_summary = st["rules_summary"]
    course = st["course"]
    num_holes = int(league.get("LeagueHoles") or 18)
    adjust_mode = int(league.get("AdjustScores") or 1)
    holes_meta = (course.get("holes") or [])[:num_holes]

    res_tbl = f"{lid}PlayerResults"
    sched_tbl = f"{lid}Schedule"
    tr_tbl = f"{lid}TeamResults"

    sched_rows = rows_as_dicts(conn.execute(f'SELECT * FROM "{sched_tbl}" WHERE "WeekNum"=?', (week_num,))) if table_exists(conn, sched_tbl) else []
    week_sched = sched_rows[0] if sched_rows else {"WeekNum": week_num}

    raw_results = rows_as_dicts(conn.execute(f'SELECT * FROM "{res_tbl}" WHERE "WeekNum"=? ORDER BY "PlayerID" ASC', (week_num,))) if table_exists(conn, res_tbl) else []
    res_by_pid = {r["PlayerID"]: r for r in raw_results}

    team_results = rows_as_dicts(conn.execute(f'SELECT * FROM "{tr_tbl}" WHERE "WeekNum"=? ORDER BY "TeamID" ASC', (week_num,))) if table_exists(conn, tr_tbl) else []

    scorecards = []
    for p in sorted(st["players"], key=lambda x: (x.get("TeamID") or 0, x.get("PlayerID") or 0)):
        pid = p["PlayerID"]
        r = res_by_pid.get(pid, {})
        hcp = float(p.get("Handicap") or 0)
        hole_scores = []
        hole_adj = []
        hole_nets = []
        hole_strokes = []
        stable_gross = 0
        stable_net = 0
        for hm in holes_meta:
            h_idx = hm["hole"]
            raw_s = r.get(str(h_idx))
            val = int(raw_s) if raw_s not in (None, "", 0) else 0
            st_rec = strokes_on_hole(hcp, hm["handicap_rank"], num_holes)
            net_val = (val - st_rec) if val > 0 else 0
            adj_val = apply_esc_cap(val, hm["par"], hcp, adjust_mode, num_holes)
            hole_scores.append(val)
            hole_adj.append(adj_val)
            hole_strokes.append(st_rec)
            hole_nets.append(net_val)
            if val > 0:
                stable_gross += hole_stableford_pts(val, hm["par"])
                stable_net += hole_stableford_pts(net_val, hm["par"])

        front = sum(hole_scores[:9])
        back = sum(hole_scores[9:18]) if num_holes > 9 else 0
        gross = front + back
        adj_gross = sum(hole_adj)
        net = (gross - int(round(hcp))) if gross > 0 else 0
        par_played = sum(hm["par"] for hm, s in zip(holes_meta, hole_scores) if s > 0)
        over_par = (gross - par_played) if gross > 0 else 0

        scorecards.append({
            "PlayerID": pid,
            "TeamID": p.get("TeamID"),
            "PlayerName": f"{p.get('PlayerFirst', '')} {p.get('PlayerLast', '')}".strip(),
            "Handicap": hcp,
            "holes": hole_scores,
            "adj_holes": hole_adj,
            "strokes_received": hole_strokes,
            "net_holes": hole_nets,
            "FrontNine": front,
            "BackNine": back,
            "Gross": gross,
            "AdjGross": adj_gross,
            "ESC_CappedStrokes": max(0, gross - adj_gross),
            "Net": net,
            "OverPar": over_par,
            "StablefordGross": stable_gross,
            "StablefordNet": stable_net,
            "NumPutts": int(r.get("NumPutts") or 0),
            "GreensInRegulation": int(r.get("GreensInRegulation") or 0),
            "NumFairwaysHit": int(r.get("NumFairwaysHit") or 0),
            "IndividualPts": float(r.get("IndividualPts") or 0),
            "FieldPts": float(r.get("FieldPts") or 0),
            "Skins": float(r.get("Skins") or 0),
            "SkinsNet": float(r.get("SkinsNet") or 0),
        })

    card_by_pid = {c["PlayerID"]: c for c in scorecards}
    pairs = _resolve_week_pairings(conn, lid, week_num, st["players"], week_sched)
    matchups = _compute_matchups(pairs, card_by_pid, holes_meta, rules_summary, num_holes)

    # Calculate weekly Skins (Gross & Net) across players with recorded scores
    active_cards = [c for c in scorecards if c["Gross"] > 0]
    gross_skins: list[dict[str, Any]] = []
    net_skins: list[dict[str, Any]] = []
    for idx, hm in enumerate(holes_meta):
        h_num = hm["hole"]
        g_vals = [(c["holes"][idx], c["PlayerName"], c["PlayerID"]) for c in active_cards if c["holes"][idx] > 0]
        if g_vals:
            min_g = min(v[0] for v in g_vals)
            winners_g = [v for v in g_vals if v[0] == min_g]
            if len(winners_g) == 1:
                gross_skins.append({"hole": h_num, "score": min_g, "par": hm["par"], "player": winners_g[0][1], "PlayerID": winners_g[0][2]})
        n_vals = [(c["net_holes"][idx], c["PlayerName"], c["PlayerID"]) for c in active_cards if c["holes"][idx] > 0]
        if n_vals:
            min_n = min(v[0] for v in n_vals)
            winners_n = [v for v in n_vals if v[0] == min_n]
            if len(winners_n) == 1:
                net_skins.append({"hole": h_num, "net_score": min_n, "par": hm["par"], "player": winners_n[0][1], "PlayerID": winners_n[0][2]})

    return {
        "league_id": lid,
        "league_name": league.get("LeagueName"),
        "week_num": week_num,
        "num_holes": num_holes,
        "course": course,
        "rules_summary": rules_summary,
        "holes_meta": holes_meta,
        "schedule": week_sched,
        "scorecards": scorecards,
        "matchups": matchups,
        "team_results": team_results,
        "gross_skins": gross_skins,
        "net_skins": net_skins,
    }


def auto_score_week_matches(conn: sqlite3.Connection, lid: int, week_num: int) -> dict[str, Any]:
    """Compute and persist Head-to-Head Match Points, Field Points, *TeamResults, and Season Totals (AGY-F2 / CDX-F1..F3)."""
    sc = get_week_scorecard(conn, lid, week_num)
    rules_summary = sc["rules_summary"]
    matchups = sc["matchups"]
    scorecards = sc["scorecards"]
    week_sched = sc["schedule"]

    pts_by_pid: dict[int, float] = {}
    for m in matchups:
        if m["PlayerA_Gross"] > 0 and m["PlayerB_Gross"] > 0:
            pts_by_pid[m["PlayerA_ID"]] = m["computed_pts_a"]
            pts_by_pid[m["PlayerB_ID"]] = m["computed_pts_b"]

    field_by_pid = _compute_field_points(scorecards, rules_summary)

    res_tbl = f"{lid}PlayerResults"
    p_tbl = f"{lid}Players"
    tr_tbl = f"{lid}TeamResults"
    t_tbl = f"{lid}Teams"

    with conn:
        for pid, pts in pts_by_pid.items():
            conn.execute(
                f'UPDATE "{res_tbl}" SET "IndividualPts"=? WHERE "WeekNum"=? AND "PlayerID"=?',
                (pts, week_num, pid),
            )
        for pid, fpts in field_by_pid.items():
            if pid not in pts_by_pid:
                conn.execute(
                    f'UPDATE "{res_tbl}" SET "FieldPts"=?, "IndividualPts"=? WHERE "WeekNum"=? AND "PlayerID"=?',
                    (fpts, fpts, week_num, pid),
                )
            else:
                conn.execute(
                    f'UPDATE "{res_tbl}" SET "FieldPts"=? WHERE "WeekNum"=? AND "PlayerID"=?',
                    (fpts, week_num, pid),
                )

        # Roll up team results for the week
        if table_exists(conn, tr_tbl) and table_exists(conn, t_tbl):
            team_cards: dict[int, list[dict[str, Any]]] = {}
            for c in scorecards:
                if c["Gross"] > 0 and c.get("TeamID"):
                    team_cards.setdefault(int(c["TeamID"]), []).append(c)

            team_match_bonus = float(rules_summary.get("TeamMatchPts") or 4.0)
            team_bonus_by_tid: dict[int, float] = {}
            for m_idx in (1, 2):
                t1 = int(week_sched.get(f"Match{m_idx}Team1") or 0)
                t2 = int(week_sched.get(f"Match{m_idx}Team2") or 0)
                if t1 in team_cards and t2 in team_cards:
                    n1 = sum(x["Net"] for x in team_cards[t1])
                    n2 = sum(x["Net"] for x in team_cards[t2])
                    if n1 < n2:
                        team_bonus_by_tid[t1] = team_match_bonus
                        team_bonus_by_tid[t2] = 0.0
                    elif n2 < n1:
                        team_bonus_by_tid[t2] = team_match_bonus
                        team_bonus_by_tid[t1] = 0.0
                    else:
                        team_bonus_by_tid[t1] = 0.5 * team_match_bonus
                        team_bonus_by_tid[t2] = 0.5 * team_match_bonus

            for tid, cards in team_cards.items():
                t_act = sum(x["Gross"] for x in cards)
                t_net = sum(x["Net"] for x in cards)
                ind_sum = sum(pts_by_pid.get(x["PlayerID"], x["IndividualPts"]) for x in cards)
                m_pts = team_bonus_by_tid.get(tid, 0.0)
                tot_t_pts = round(ind_sum + m_pts, 2)
                exists_tr = conn.execute(
                    f'SELECT 1 FROM "{tr_tbl}" WHERE "WeekNum"=? AND "TeamID"=?',
                    (week_num, tid),
                ).fetchone()
                if exists_tr:
                    conn.execute(
                        f'UPDATE "{tr_tbl}" SET "TeamPts"=?, "MatchPts"=?, "TeamActual"=?, "TeamNet"=? WHERE "WeekNum"=? AND "TeamID"=?',
                        (tot_t_pts, m_pts, t_act, t_net, week_num, tid),
                    )
                else:
                    conn.execute(
                        f'INSERT INTO "{tr_tbl}" ("WeekNum","TeamID","TeamPts","MatchPts","FieldPts","TeamActual","TeamNet","SubPts","UserDefinedPts") VALUES (?,?,?,?,0,?,?,0,0)',
                        (week_num, tid, tot_t_pts, m_pts, t_act, t_net),
                    )

            # Update season *Teams.Points
            for tr_row in rows_as_dicts(conn.execute(f'SELECT "TeamID", COALESCE(SUM("TeamPts"),0) AS s FROM "{tr_tbl}" GROUP BY "TeamID"')):
                if tr_row["s"] > 0:
                    conn.execute(f'UPDATE "{t_tbl}" SET "Points"=? WHERE "TeamID"=?', (round(float(tr_row["s"]), 2), tr_row["TeamID"]))

        # Recompute season *Players.Points
        for pr_row in rows_as_dicts(conn.execute(f'SELECT "PlayerID", COALESCE(SUM("IndividualPts"),0) AS s FROM "{res_tbl}" GROUP BY "PlayerID"')):
            if pr_row["s"] > 0:
                conn.execute(f'UPDATE "{p_tbl}" SET "Points"=? WHERE "PlayerID"=?', (round(float(pr_row["s"]), 2), pr_row["PlayerID"]))

    return get_week_scorecard(conn, lid, week_num)


def save_player_week_score(conn: sqlite3.Connection, lid: int, week_num: int, payload: dict[str, Any]) -> dict[str, Any]:
    st = get_league_standings(conn, lid)
    league = st["league"]
    course = st["course"]
    num_holes = int(league.get("LeagueHoles") or 18)
    adjust_mode = int(league.get("AdjustScores") or 1)
    holes_meta = (course.get("holes") or [])[:18]

    pid = int(payload["PlayerID"])
    p_row = next((p for p in st["players"] if int(p["PlayerID"]) == pid), {})
    hcp = float(p_row.get("Handicap") or 0)

    holes: list[int] = [int(x or 0) for x in (payload.get("holes") or [])]
    while len(holes) < 18:
        holes.append(0)
    adj_holes = [
        apply_esc_cap(holes[i], holes_meta[i]["par"] if i < len(holes_meta) else 4, hcp, adjust_mode, num_holes)
        for i in range(18)
    ]

    front = sum(holes[:9])
    back = sum(holes[9:18])
    adj_front = sum(adj_holes[:9])
    adj_back = sum(adj_holes[9:18])
    putts = int(payload.get("NumPutts") or 0)
    gir = int(payload.get("GreensInRegulation") or 0)
    fwy = int(payload.get("NumFairwaysHit") or 0)
    ind_pts = float(payload.get("IndividualPts") or 0)

    res_tbl = f"{lid}PlayerResults"
    adj_tbl = f"{lid}AdjScores"
    hole_cols = [f'"{i}"' for i in range(1, 19)]

    with conn:
        existing = conn.execute(
            f'SELECT 1 FROM "{res_tbl}" WHERE "WeekNum"=? AND "PlayerID"=?',
            (week_num, pid),
        ).fetchone()
        if existing:
            set_clause = ", ".join(f'{c}=?' for c in hole_cols) + ', "FrontNine"=?, "BackNine"=?, "NumPutts"=?, "GreensInRegulation"=?, "NumFairwaysHit"=?, "IndividualPts"=?'
            conn.execute(
                f'UPDATE "{res_tbl}" SET {set_clause} WHERE "WeekNum"=? AND "PlayerID"=?',
                (*holes[:18], front, back, putts, gir, fwy, ind_pts, week_num, pid),
            )
        else:
            cols_str = '"WeekNum", "PlayerID", ' + ", ".join(hole_cols) + ', "FrontNine", "BackNine", "NumPutts", "GreensInRegulation", "NumFairwaysHit", "IndividualPts", "Sub", "Forfeit"'
            q_marks = ", ".join("?" for _ in range(26))
            conn.execute(
                f'INSERT INTO "{res_tbl}" ({cols_str}) VALUES ({q_marks})',
                (week_num, pid, *holes[:18], front, back, putts, gir, fwy, ind_pts, 0, 0),
            )

        # Synchronize ESC-adjusted total into *AdjScores matrix (WeekNum, ID{pid}) (AGY-F3 / CDX-F3)
        if table_exists(conn, adj_tbl):
            adj_cols = {d[1] for d in conn.execute(f'PRAGMA table_info("{adj_tbl}")').fetchall()}
            pid_col = f"ID{pid}"
            if pid_col in adj_cols:
                ex_adj = conn.execute(
                    f'SELECT 1 FROM "{adj_tbl}" WHERE "WeekNum"=?',
                    (week_num,),
                ).fetchone()
                if ex_adj:
                    conn.execute(
                        f'UPDATE "{adj_tbl}" SET "{pid_col}"=? WHERE "WeekNum"=?',
                        (adj_front + adj_back, week_num),
                    )
                else:
                    conn.execute(
                        f'INSERT INTO "{adj_tbl}" ("WeekNum", "{pid_col}") VALUES (?, ?)',
                        (week_num, adj_front + adj_back),
                    )

    # Automatically recompute week match play & field points
    return auto_score_week_matches(conn, lid, week_num)


def recalculate_handicaps(conn: sqlite3.Connection, lid: int) -> dict[str, Any]:
    """Recompute player & team handicaps using GLS9 League settings and ESC-adjusted scores (*AdjScores + *PastScores)."""
    st = get_league_standings(conn, lid)
    league = st["league"]
    course = st["course"]
    num_holes = int(league.get("LeagueHoles") or 18)
    pct = float(league.get("PercentHandicap") or 90) / 100.0
    max_hcp = float(league.get("MaximumHandicap") or (18 if num_holes == 9 else 36))
    par_target = int(course.get("front_par") or 36) if num_holes == 9 else int(course.get("total_par") or 72)

    p_tbl = f"{lid}Players"
    t_tbl = f"{lid}Teams"
    past_tbl = f"{lid}PastScores"
    adj_tbl = f"{lid}AdjScores"
    res_tbl = f"{lid}PlayerResults"

    past_map = {}
    if table_exists(conn, past_tbl):
        for r in rows_as_dicts(conn.execute(f'SELECT * FROM "{past_tbl}"')):
            scores = [int(r[str(i)]) for i in range(1, 21) if str(i) in r and r[str(i)] not in (None, "", 0) and int(r[str(i)]) > 20]
            past_map[r["PlayerID"]] = scores

    # Prefer ESC-adjusted scores from *AdjScores (ID{pid}), fallback to *PlayerResults
    res_scores: dict[int, list[int]] = {}
    if table_exists(conn, adj_tbl):
        for r in rows_as_dicts(conn.execute(f'SELECT * FROM "{adj_tbl}" ORDER BY "WeekNum" ASC')):
            for k, val in r.items():
                if k.startswith("ID") and k[2:].isdigit() and val not in (None, "", 0) and int(val) > 20:
                    res_scores.setdefault(int(k[2:]), []).append(int(val))
    elif table_exists(conn, res_tbl):
        for r in rows_as_dicts(conn.execute(f'SELECT * FROM "{res_tbl}" ORDER BY "WeekNum" ASC')):
            pid = r["PlayerID"]
            tot = int(r.get("FrontNine") or 0) + (int(r.get("BackNine") or 0) if num_holes > 9 else 0)
            if tot > 20:
                res_scores.setdefault(pid, []).append(tot)

    updated = []
    with conn:
        for p in st["players"]:
            pid = p["PlayerID"]
            rounds = (past_map.get(pid, []) + res_scores.get(pid, []))[-10:]
            if rounds:
                avg_over = sum(r - par_target for r in rounds) / len(rounds)
                new_hcp = max(0.0, min(max_hcp, round(avg_over * pct, 1)))
                conn.execute(f'UPDATE "{p_tbl}" SET "Handicap"=? WHERE "PlayerID"=?', (new_hcp, pid))
                updated.append({"PlayerID": pid, "PlayerName": f"{p.get('PlayerFirst','')} {p.get('PlayerLast','')}".strip(), "rounds_used": len(rounds), "new_handicap": new_hcp})

        # Update team handicaps
        p_hcp = {r["PlayerID"]: float(r.get("Handicap") or 0) for r in rows_as_dicts(conn.execute(f'SELECT * FROM "{p_tbl}"'))}
        for t in st["teams"]:
            tid = t["TeamID"]
            members = [t.get("PlayerA"), t.get("PlayerB"), t.get("PlayerC"), t.get("PlayerD")]
            t_hcps = [p_hcp[m] for m in members if m and m in p_hcp]
            if t_hcps:
                conn.execute(f'UPDATE "{t_tbl}" SET "Handicap"=? WHERE "TeamID"=?', (round(sum(t_hcps), 1), tid))

    return {"league_id": lid, "updated_players": len(updated), "updates": updated}


def generate_schedule(conn: sqlite3.Connection, lid: int, weeks: int = 16, start_date: str = "2026-05-05") -> list[dict[str, Any]]:
    st = get_league_standings(conn, lid)
    num_teams = max(4, len(st["teams"]))
    if num_teams % 2 == 1:
        num_teams += 1
    sched_tbl = f"{lid}Schedule"
    course_id = int(st["league"].get("CourseID") or 1)

    tpl_row = conn.execute(
        "SELECT raw_csv FROM round_robin_templates WHERE num_teams=?",
        (num_teams,),
    ).fetchone()
    pairings_per_week: list[list[tuple[int, int]]] = []
    if tpl_row and tpl_row[0]:
        for ln in csv.reader(io.StringIO(tpl_row[0])):
            nums = [int(x.strip()) for x in ln if x.strip().isdigit()]
            if len(nums) >= 4:
                wk_pairs = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
                pairings_per_week.append(wk_pairs)

    if not pairings_per_week:
        teams_list = list(range(1, num_teams + 1))
        for w in range(weeks):
            wk_pairs = []
            for i in range(num_teams // 2):
                wk_pairs.append((teams_list[i], teams_list[num_teams - 1 - i]))
            pairings_per_week.append(wk_pairs)
            teams_list = [teams_list[0]] + [teams_list[-1]] + teams_list[1:-1]

    dt = datetime.strptime(start_date[:10], "%Y-%m-%d")
    with conn:
        conn.execute(f'DELETE FROM "{sched_tbl}"')
        for w in range(1, weeks + 1):
            pairs = pairings_per_week[(w - 1) % len(pairings_per_week)]
            m1t1, m1t2 = pairs[0] if len(pairs) > 0 else (1, 2)
            m2t1, m2t2 = pairs[1] if len(pairs) > 1 else (3, 4)
            half = 1 if w <= (weeks // 2) else 2
            date_str = (dt + timedelta(days=7 * (w - 1))).strftime("%m/%d/%y 00:00:00")
            conn.execute(
                f'INSERT INTO "{sched_tbl}" ("WeekNum","Date","DateType","CourseID","SchedUsed","Half","Weather","Match1Team1","Match1Team2","Match2Team1","Match2Team2") '
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (w, date_str, 1, course_id, -1, half, "Clear", m1t1, m1t2, m2t1, m2t2),
            )

    return rows_as_dicts(conn.execute(f'SELECT * FROM "{sched_tbl}" ORDER BY "WeekNum" ASC'))
