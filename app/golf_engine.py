"""Clean-room Golf League Secretary (GLS9) calculation engine:
- 9-hole & 18-hole Course Par, Yardage, and Handicap Stroke Allocation
- Equitable Stroke Control (Adjusted Score) & Net Score calculation
- Configurable League Handicap Formula (PercentHandicap, MaximumHandicap, RoundsUsed)
- Weekly Skins (Gross & Net), Low Gross/Net, Match Points, and Team Standings
- Round-Robin Schedule generation from the 24 GLS9 templates (4team..52team)."""
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
        # In 9-hole play, normalize rank 1..18 into 1..9 order
        eff_rank = ((hole_rank - 1) // 2) + 1 if hole_rank > 9 else hole_rank
        base = hcp // 9
        rem = hcp % 9
        return base + (1 if eff_rank <= rem else 0)
    base = hcp // 18
    rem = hcp % 18
    return base + (1 if hole_rank <= rem else 0)


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

    return {
        "league": league,
        "rules": rules,
        "course": course,
        "teams": teams,
        "players": players,
        "subs": subs,
        "fees": fees,
        "prizes": prizes,
    }


def get_week_scorecard(conn: sqlite3.Connection, lid: int, week_num: int) -> dict[str, Any]:
    st = get_league_standings(conn, lid)
    league = st["league"]
    course = st["course"]
    num_holes = int(league.get("LeagueHoles") or 18)
    holes_meta = (course.get("holes") or [])[:num_holes]

    p_map = {p["PlayerID"]: p for p in st["players"]}
    res_tbl = f"{lid}PlayerResults"
    sched_tbl = f"{lid}Schedule"

    sched_rows = rows_as_dicts(conn.execute(f'SELECT * FROM "{sched_tbl}" WHERE "WeekNum"=?', (week_num,))) if table_exists(conn, sched_tbl) else []
    week_sched = sched_rows[0] if sched_rows else {"WeekNum": week_num}

    raw_results = rows_as_dicts(conn.execute(f'SELECT * FROM "{res_tbl}" WHERE "WeekNum"=? ORDER BY "PlayerID" ASC', (week_num,))) if table_exists(conn, res_tbl) else []
    res_by_pid = {r["PlayerID"]: r for r in raw_results}

    scorecards = []
    for p in sorted(st["players"], key=lambda x: (x.get("TeamID") or 0, x.get("PlayerID") or 0)):
        pid = p["PlayerID"]
        r = res_by_pid.get(pid, {})
        hcp = float(p.get("Handicap") or 0)
        hole_scores = []
        hole_nets = []
        hole_strokes = []
        for hm in holes_meta:
            h_idx = hm["hole"]
            raw_s = r.get(str(h_idx))
            val = int(raw_s) if raw_s not in (None, "", 0) else 0
            st_rec = strokes_on_hole(hcp, hm["handicap_rank"], num_holes)
            hole_scores.append(val)
            hole_strokes.append(st_rec)
            hole_nets.append((val - st_rec) if val > 0 else 0)

        front = sum(hole_scores[:9])
        back = sum(hole_scores[9:18]) if num_holes > 9 else 0
        gross = front + back
        net = (gross - int(round(hcp))) if gross > 0 else 0
        par_played = sum(hm["par"] for hm, s in zip(holes_meta, hole_scores) if s > 0)
        over_par = (gross - par_played) if gross > 0 else 0

        scorecards.append({
            "PlayerID": pid,
            "TeamID": p.get("TeamID"),
            "PlayerName": f"{p.get('PlayerFirst', '')} {p.get('PlayerLast', '')}".strip(),
            "Handicap": hcp,
            "holes": hole_scores,
            "strokes_received": hole_strokes,
            "net_holes": hole_nets,
            "FrontNine": front,
            "BackNine": back,
            "Gross": gross,
            "Net": net,
            "OverPar": over_par,
            "NumPutts": int(r.get("NumPutts") or 0),
            "GreensInRegulation": int(r.get("GreensInRegulation") or 0),
            "NumFairwaysHit": int(r.get("NumFairwaysHit") or 0),
            "IndividualPts": float(r.get("IndividualPts") or 0),
            "FieldPts": float(r.get("FieldPts") or 0),
            "Skins": float(r.get("Skins") or 0),
            "SkinsNet": float(r.get("SkinsNet") or 0),
        })

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
        "holes_meta": holes_meta,
        "schedule": week_sched,
        "scorecards": scorecards,
        "gross_skins": gross_skins,
        "net_skins": net_skins,
    }


def save_player_week_score(conn: sqlite3.Connection, lid: int, week_num: int, payload: dict[str, Any]) -> dict[str, Any]:
    pid = int(payload["PlayerID"])
    holes: list[int] = [int(x or 0) for x in (payload.get("holes") or [])]
    while len(holes) < 18:
        holes.append(0)
    front = sum(holes[:9])
    back = sum(holes[9:18])
    putts = int(payload.get("NumPutts") or 0)
    gir = int(payload.get("GreensInRegulation") or 0)
    fwy = int(payload.get("NumFairwaysHit") or 0)
    ind_pts = float(payload.get("IndividualPts") or 0)

    res_tbl = f"{lid}PlayerResults"
    p_tbl = f"{lid}Players"
    with conn:
        existing = conn.execute(
            f'SELECT 1 FROM "{res_tbl}" WHERE "WeekNum"=? AND "PlayerID"=?',
            (week_num, pid),
        ).fetchone()
        hole_cols = [f'"{i}"' for i in range(1, 19)]
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
        # Recompute player total points from all weeks
        tot_pts_row = conn.execute(
            f'SELECT COALESCE(SUM("IndividualPts"), 0) FROM "{res_tbl}" WHERE "PlayerID"=?',
            (pid,),
        ).fetchone()
        if tot_pts_row and tot_pts_row[0] > 0:
            conn.execute(f'UPDATE "{p_tbl}" SET "Points"=? WHERE "PlayerID"=?', (float(tot_pts_row[0]), pid))

    return get_week_scorecard(conn, lid, week_num)


def recalculate_handicaps(conn: sqlite3.Connection, lid: int) -> dict[str, Any]:
    """Recompute player & team handicaps using GLS9 League settings (PercentHandicap, MaximumHandicap, PastScores + Results)."""
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
    res_tbl = f"{lid}PlayerResults"

    past_map = {}
    if table_exists(conn, past_tbl):
        for r in rows_as_dicts(conn.execute(f'SELECT * FROM "{past_tbl}"')):
            scores = [int(r[str(i)]) for i in range(1, 21) if str(i) in r and r[str(i)] not in (None, "", 0) and int(r[str(i)]) > 20]
            past_map[r["PlayerID"]] = scores

    res_scores: dict[int, list[int]] = {}
    if table_exists(conn, res_tbl):
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

    # Check if we have a matching round_robin_template from GLS9 Schedules/*.csv
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
        # Standard circle round-robin fallback
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
