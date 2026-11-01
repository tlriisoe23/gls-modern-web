"""GLS9 V2 Match-Play, ESC, Stableford, Field-Points & Team-Rollup engine.

Clean-room reconstruction of the Golf League Secretary (Gls90.exe / Gls90db.mdb Jet 3.5)
weekly scoring pipeline.  Everything in this module is driven by the real schema:

  Leagues         LeagueHoles, NumManTeams, LeagueScoring, AdjustScores, Divisions, Div1..Div4,
                  FirstTeeTime, MinsBetweenGroups, SubPercent
  LeagueRules     IndPtsNet, IndPtsAct, IndPtsNetMatch, IndPtsActMatch, IndPtsHolesMatch,
                  IndActHolesMatch, FieldTopPts, FieldStepPts, TeamPtsNetMatch,
                  TeamPtsActMatch, TeamPtsHolesMatch, PlayerForfeit, PresentPlayerPts,
                  UseIndPts, IndSubPts
  StablefordPts   Net/Act DEagle..Triple point matrix (all-zero => Modified Stableford default)
  <lid>MatchSetup ID1..IDn weekly foursome layout: [a, b, c, d] => a vs c, b vs d
  <lid>PlayerResults OpponentID, IndividualPts, FieldPts, Sub, Forfeit, hole columns "1".."18"
  <lid>SubResults  substitute hole scores + SubCap used when PlayerResults.Sub = 1
  <lid>TeamResults WeekNum, TeamID, TeamPts, MatchPts, FieldPts, TeamActual, TeamNet
  <lid>AdjScores / ActScores / AdjOverPar / Handicaps  weekly per-player snapshots (ID<pid>)
  <lid>SchedNine   which nine (1 = front, 2 = back) each match plays in 9-hole leagues

Rules that could not be confirmed against the (synthetic) sample database are documented
in docs/CROSS_SQUAD_MATRIX.md and exposed via GET /api/leagues/{lid}/rules so a league
secretary can see exactly how points are computed.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from .golf_engine import rows_as_dicts, table_exists

# ---------------------------------------------------------------------------
# Pure calculation helpers (no DB)
# ---------------------------------------------------------------------------

ADJUST_MODES = {
    0: "none",
    1: "none",            # sample League 9: AdjScores == ActScores for every player
    2: "double_bogey",    # sample League 10/11: AdjScores replays exactly with par+2 cap
    3: "usga_esc",        # USGA Equitable Stroke Control by course handicap
}

MODIFIED_STABLEFORD_DEFAULT = {
    "DEagle": 8, "Eagle": 5, "Birdie": 2, "Par": 0, "Bogie": -1, "Double": -3, "Triple": -3,
}

SCORING_MODES = {
    1: "stroke_play_field",     # individual league: per-hole pts + round pts + field pts
    2: "hole_by_hole_match",    # per-hole pts (IndPtsNet/IndPtsAct) + round pts (IndPtsNetMatch)
    3: "hole_by_hole_match",
    4: "nines_plus_match",      # IndPtsNet per nine + IndPtsHolesMatch for 18-hole holes-won match
}


def esc_cap(par: int, hcp: float, mode: int) -> int | None:
    """Maximum hole score allowed under the league's AdjustScores mode (None = no cap)."""
    m = ADJUST_MODES.get(int(mode or 0), "none")
    if m == "none":
        return None
    if m == "double_bogey":
        return par + 2
    h = int(round(hcp or 0))
    if h <= 9:
        return par + 2
    if h <= 19:
        return 7
    if h <= 29:
        return 8
    if h <= 39:
        return 9
    return 10


def apply_esc(holes: list[int], pars: list[int], hcp: float, mode: int) -> list[int]:
    out = []
    for s, p in zip(holes, pars):
        if not s or s <= 0:
            out.append(0)
            continue
        cap = esc_cap(p, hcp, mode)
        out.append(min(s, cap) if cap is not None else s)
    return out


def nine_ranks(caps18: list[int], nine: str) -> list[int]:
    """Re-rank the 9 played holes 1..9 by their 18-hole stroke index (fixes V1 (rank-1)//2 bug)."""
    idx = range(0, 9) if nine != "back" else range(9, 18)
    pairs = sorted(idx, key=lambda i: caps18[i])
    rank = {i: k + 1 for k, i in enumerate(pairs)}
    return [rank[i] for i in idx]


def strokes_per_hole(hcp: float, ranks: list[int], num_holes: int) -> list[int]:
    h = max(0, int(round(float(hcp or 0))))
    base, rem = divmod(h, num_holes)
    return [base + (1 if r <= rem else 0) for r in ranks]


def stableford_points(net_or_gross: list[int], pars: list[int], matrix: dict[str, int]) -> int:
    total = 0
    for s, p in zip(net_or_gross, pars):
        if not s:
            continue
        d = s - p
        if d <= -3:
            total += matrix["DEagle"]
        elif d == -2:
            total += matrix["Eagle"]
        elif d == -1:
            total += matrix["Birdie"]
        elif d == 0:
            total += matrix["Par"]
        elif d == 1:
            total += matrix["Bogie"]
        elif d == 2:
            total += matrix["Double"]
        else:
            total += matrix["Triple"]
    return total


def split_points(a: float, b: float, pts: float) -> tuple[float, float]:
    """Lower value wins `pts`; ties split evenly (CDX-F1)."""
    if pts <= 0:
        return 0.0, 0.0
    if a < b:
        return float(pts), 0.0
    if b < a:
        return 0.0, float(pts)
    return pts / 2.0, pts / 2.0


def holes_won(a: list[int], b: list[int]) -> tuple[float, float, list[str]]:
    """Hole-by-hole comparison. Returns (a_won, b_won, per-hole winner codes 'A'/'B'/'T'/'-')."""
    aw = bw = 0.0
    codes = []
    for x, y in zip(a, b):
        if not x or not y:
            codes.append("-")
            continue
        if x < y:
            aw += 1
            codes.append("A")
        elif y < x:
            bw += 1
            codes.append("B")
        else:
            aw += 0.5
            bw += 0.5
            codes.append("T")
    return aw, bw, codes


def field_points(entries: list[tuple[int, float]], first: float, diff: float) -> dict[int, float]:
    """entries = [(PlayerID, net)], award first, first-diff, first-2*diff ... >= 0; ties share places."""
    out: dict[int, float] = {}
    if first <= 0 or not entries:
        return out
    ordered = sorted(entries, key=lambda e: e[1])
    place = 0
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        n = j - i + 1
        pool = sum(max(0.0, first - diff * (place + k)) for k in range(n))
        share = round(pool / n, 2)
        for k in range(i, j + 1):
            out[ordered[k][0]] = share
        place += n
        i = j + 1
    return out


def tee_times(first: str | None, mins: int | None, groups: int) -> list[str]:
    try:
        base = datetime.strptime((first or "05:30 PM").strip().upper(), "%I:%M %p")
    except ValueError:
        try:
            base = datetime.strptime((first or "17:30").strip(), "%H:%M")
        except ValueError:
            base = datetime.strptime("05:30 PM", "%I:%M %p")
    step = int(mins or 10)
    return [(base + timedelta(minutes=step * i)).strftime("%I:%M %p").lstrip("0") for i in range(groups)]


# ---------------------------------------------------------------------------
# League context
# ---------------------------------------------------------------------------

def load_league_context(conn: sqlite3.Connection, lid: int) -> dict[str, Any]:
    from .golf_engine import get_league_standings  # local import to avoid cycle

    st = get_league_standings(conn, lid)
    league = st["league"]
    rules = st["rules"]
    course = st["course"]
    num_holes = int(league.get("LeagueHoles") or 18)
    holes = course.get("holes") or []
    pars18 = [h["par"] for h in holes] or [4] * 18
    caps18 = [h["handicap_rank"] for h in holes] or list(range(1, 19))
    sf_rows = rows_as_dicts(conn.execute('SELECT * FROM "StablefordPts" WHERE "LeagueID"=?', (lid,))) if table_exists(conn, "StablefordPts") else []
    sf = sf_rows[0] if sf_rows else {}
    sf_cfg = {k: int(sf.get(f"Net{k}") or 0) for k in MODIFIED_STABLEFORD_DEFAULT}
    sf_source = "StablefordPts"
    if not any(sf_cfg.values()):
        sf_cfg = dict(MODIFIED_STABLEFORD_DEFAULT)
        sf_source = "default_modified_stableford"
    scoring = int(league.get("LeagueScoring") or 2)
    return {
        **st,
        "num_holes": num_holes,
        "pars18": pars18,
        "caps18": caps18,
        "adjust_mode": int(league.get("AdjustScores") or 0),
        "adjust_mode_name": ADJUST_MODES.get(int(league.get("AdjustScores") or 0), "none"),
        "scoring_mode": scoring,
        "scoring_mode_name": SCORING_MODES.get(scoring, "hole_by_hole_match"),
        "stableford": sf_cfg,
        "stableford_source": sf_source,
        "num_man_teams": int(league.get("NumManTeams") or 1),
        "divisions": [league.get(k) for k in ("Div1", "Div2", "Div3", "Div4") if league.get(k) and str(league.get(k)).upper() != "NA"],
    }


def rules_summary(ctx: dict[str, Any]) -> dict[str, Any]:
    r = ctx["rules"]
    g = lambda k: float(r.get(k) or 0)  # noqa: E731
    top = g("FieldTopPts") or g("IndPtsNetField")
    step = g("FieldStepPts") or g("IndNetFieldDiff")
    mode = ctx["scoring_mode_name"]
    lines = []
    if mode == "nines_plus_match":
        lines.append(f"{g('IndPtsNet'):g} pt per nine (low net), {g('IndPtsHolesMatch'):g} pts for the 18-hole net holes-won match")
    else:
        if g("IndPtsNet"):
            lines.append(f"{g('IndPtsNet'):g} pt per net hole won (ties split)")
        if g("IndPtsAct"):
            lines.append(f"{g('IndPtsAct'):g} pts per gross hole won (ties split)")
        if g("IndPtsNetMatch"):
            lines.append(f"{g('IndPtsNetMatch'):g} pts for low net round (ties split)")
        if g("IndPtsActMatch"):
            lines.append(f"{g('IndPtsActMatch'):g} pts for low gross round")
    if top:
        lines.append(f"Field points {top:g} / -{step:g} per place on net")
    if g("TeamPtsNetMatch"):
        lines.append(f"Team: {g('TeamPtsNetMatch'):g} pts low team net")
    if g("TeamPtsHolesMatch"):
        lines.append(f"Team: {g('TeamPtsHolesMatch'):g} pts aggregate net holes won")
    if g("PlayerForfeit"):
        lines.append(f"Forfeit: opponent receives {g('PlayerForfeit'):g}")
    rule_vals = {k: r.get(k) for k in (
        "IndPtsNet", "IndPtsAct", "IndPtsNetMatch", "IndPtsActMatch", "IndPtsHolesMatch", "IndActHolesMatch",
        "FieldTopPts", "FieldStepPts", "TeamPtsNet", "TeamPtsNetMatch", "TeamPtsActMatch", "TeamPtsHolesMatch",
        "PlayerForfeit", "TeamForfeit", "PresentPlayerPts", "PresentTeamPts", "UseIndPts", "IndSubPts")}
    rule_vals["IndPtsNetField"] = r.get("IndPtsNetField")
    rule_vals["IndNetFieldDiff"] = r.get("IndNetFieldDiff")
    return {
        "scoring_mode": ctx["scoring_mode"],
        "scoring_mode_name": mode,
        "adjust_mode": ctx["adjust_mode"],
        "adjust_mode_name": ctx["adjust_mode_name"],
        "stableford": ctx["stableford"],
        "stableford_source": ctx["stableford_source"],
        "divisions": ctx["divisions"],
        "first_tee_time": ctx["league"].get("FirstTeeTime"),
        "mins_between_groups": ctx["league"].get("MinsBetweenGroups"),
        "num_man_teams": ctx["num_man_teams"],
        "sub_percent": ctx["league"].get("SubPercent"),
        "human_rules": lines,
        "rule_values": rule_vals,
    }


# ---------------------------------------------------------------------------
# Weekly data loading
# ---------------------------------------------------------------------------

def _hole_cols(row: dict[str, Any]) -> list[int]:
    return [int(row.get(str(i)) or 0) for i in range(1, 19)]


def detect_nine(holes18: list[int], num_holes: int, default: str = "front") -> str:
    if num_holes >= 18:
        return "both"
    f = any(holes18[:9])
    b = any(holes18[9:])
    if b and not f:
        return "back"
    if f and not b:
        return "front"
    return default


def scheduled_nine(conn: sqlite3.Connection, lid: int, week_num: int) -> str:
    """9-hole leagues: SchedNine.Match1 (1=front, 2=back) is the default nine for the week."""
    tbl = f"{lid}SchedNine"
    if not table_exists(conn, tbl):
        return "front"
    rows = rows_as_dicts(conn.execute(f'SELECT * FROM "{tbl}" WHERE "WeekNum"=?', (week_num,)))
    if not rows:
        return "front"
    return "back" if int(rows[0].get("Match1") or 1) == 2 else "front"


def load_week_entries(conn: sqlite3.Connection, ctx: dict[str, Any], lid: int, week_num: int) -> dict[int, dict[str, Any]]:
    """Per-player weekly entry: raw holes (sub-aware), handicap used, nine played, ESC-adjusted holes, nets."""
    res_tbl = f"{lid}PlayerResults"
    sub_tbl = f"{lid}SubResults"
    subs_tbl = f"{lid}Subs"
    num_holes = ctx["num_holes"]
    p_map = {p["PlayerID"]: p for p in ctx["players"]}
    results = rows_as_dicts(conn.execute(f'SELECT * FROM "{res_tbl}" WHERE "WeekNum"=?', (week_num,))) if table_exists(conn, res_tbl) else []
    sub_rows = {r["PlayerID"]: r for r in rows_as_dicts(conn.execute(f'SELECT * FROM "{sub_tbl}" WHERE "WeekNum"=?', (week_num,)))} if table_exists(conn, sub_tbl) else {}
    subs = {s["SubID"]: s for s in rows_as_dicts(conn.execute(f'SELECT * FROM "{subs_tbl}"'))} if table_exists(conn, subs_tbl) else {}
    default_nine = scheduled_nine(conn, lid, week_num) if num_holes == 9 else "both"
    sub_pct = float(ctx["league"].get("SubPercent") or 100) / 100.0

    entries: dict[int, dict[str, Any]] = {}
    for r in results:
        pid = r["PlayerID"]
        p = p_map.get(pid)
        if not p:
            continue
        holes18 = _hole_cols(r)
        hcp = float(p.get("Handicap") or 0)
        is_sub = int(r.get("Sub") or 0) == 1
        sub_name = None
        if is_sub and pid in sub_rows:
            sr = sub_rows[pid]
            holes18 = _hole_cols(sr)
            s = subs.get(sr.get("SubID"))
            sub_name = f"{s.get('SubFirst','')} {s.get('SubLast','')}".strip() if s else f"Sub #{sr.get('SubID')}"
            sub_cap_val = sr.get("SubCap")
            s_handicap = float((s or {}).get("SubHandicap") or 0)
            hcp = float(sub_cap_val) if sub_cap_val is not None else (s_handicap * sub_pct)
        nine = detect_nine(holes18, num_holes, default_nine)
        if nine == "front":
            holes = holes18[:9]
            pars = ctx["pars18"][:9]
            ranks = nine_ranks(ctx["caps18"], "front")
        elif nine == "back":
            holes = holes18[9:18]
            pars = ctx["pars18"][9:18]
            ranks = nine_ranks(ctx["caps18"], "back")
        else:
            holes = holes18[:18]
            pars = ctx["pars18"][:18]
            ranks = ctx["caps18"][:18]
        played = all(h > 0 for h in holes)
        adj = apply_esc(holes, pars, hcp, ctx["adjust_mode"])
        strokes = strokes_per_hole(hcp, ranks, len(holes))
        net_holes = [(a - s) if a > 0 else 0 for a, s in zip(adj, strokes)]
        gross = sum(holes)
        adj_gross = sum(adj)
        net = adj_gross - int(round(hcp)) if played else 0
        entries[pid] = {
            "PlayerID": pid,
            "TeamID": p.get("TeamID"),
            "PlayerName": f"{p.get('PlayerFirst','')} {p.get('PlayerLast','')}".strip(),
            "Division": p.get("Division"),
            "Handicap": hcp,
            "is_sub": is_sub,
            "sub_name": sub_name,
            "forfeit": int(r.get("Forfeit") or 0) == 1,
            "OpponentID": r.get("OpponentID"),
            "nine": nine,
            "holes": holes,
            "pars": pars,
            "adj_holes": adj,
            "strokes": strokes,
            "net_holes": net_holes,
            "played": played,
            "Gross": gross if played else 0,
            "AdjGross": adj_gross if played else 0,
            "Net": net,
            "Stableford": stableford_points(net_holes, pars, ctx["stableford"]) if played else 0,
            "StablefordGross": stableford_points(adj, pars, ctx["stableford"]) if played else 0,
        }
    return entries


# ---------------------------------------------------------------------------
# Pairings
# ---------------------------------------------------------------------------

def matchsetup_pairs(conn: sqlite3.Connection, lid: int, week_num: int) -> list[tuple[int, int]]:
    """<lid>MatchSetup row => foursomes [a,b,c,d] => (a,c),(b,d). Two-ball leftovers => (a,b)."""
    tbl = f"{lid}MatchSetup"
    if not table_exists(conn, tbl):
        return []
    rows = rows_as_dicts(conn.execute(f'SELECT * FROM "{tbl}" WHERE "WeekNum"=?', (week_num,)))
    if not rows:
        return []
    ids = []
    i = 1
    while f"ID{i}" in rows[0]:
        ids.append(int(rows[0].get(f"ID{i}") or 0))
        i += 1
    ids = [x for x in ids if x > 0]
    pairs: list[tuple[int, int]] = []
    for k in range(0, len(ids), 4):
        grp = ids[k:k + 4]
        if len(grp) == 4:
            pairs.append((grp[0], grp[2]))
            pairs.append((grp[1], grp[3]))
        elif len(grp) >= 2:
            pairs.append((grp[0], grp[1]))
    return pairs


def auto_pairs(ctx: dict[str, Any], conn: sqlite3.Connection, lid: int, week_num: int, entries: dict[int, dict[str, Any]]) -> list[tuple[int, int]]:
    """Fallback pairing: team-vs-team by handicap order from <lid>Schedule, or handicap-adjacent for individual leagues."""
    pairs: list[tuple[int, int]] = []
    sched_tbl = f"{lid}Schedule"
    sched = rows_as_dicts(conn.execute(f'SELECT * FROM "{sched_tbl}" WHERE "WeekNum"=?', (week_num,))) if table_exists(conn, sched_tbl) else []
    by_team: dict[int, list[dict[str, Any]]] = {}
    for p in ctx["players"]:
        by_team.setdefault(int(p.get("TeamID") or 0), []).append(p)
    used: set[int] = set()
    if sched and ctx["num_man_teams"] > 1:
        row = sched[0]
        m = 1
        while f"Match{m}Team1" in row:
            t1, t2 = row.get(f"Match{m}Team1"), row.get(f"Match{m}Team2")
            m += 1
            if not t1 or not t2:
                continue
            a = sorted(by_team.get(int(t1), []), key=lambda p: float(p.get("Handicap") or 0))
            b = sorted(by_team.get(int(t2), []), key=lambda p: float(p.get("Handicap") or 0))
            for x, y in zip(a, b):
                pairs.append((x["PlayerID"], y["PlayerID"]))
                used.update((x["PlayerID"], y["PlayerID"]))
        if pairs:
            return pairs
    ordered = sorted(ctx["players"], key=lambda p: (float(p.get("Handicap") or 0), p["PlayerID"]))
    ordered = [p for p in ordered if p["PlayerID"] not in used]
    for k in range(0, len(ordered) - 1, 2):
        pairs.append((ordered[k]["PlayerID"], ordered[k + 1]["PlayerID"]))
    return pairs


def resolve_pairs(ctx: dict[str, Any], conn: sqlite3.Connection, lid: int, week_num: int, entries: dict[int, dict[str, Any]]) -> tuple[list[tuple[int, int]], str]:
    # 1. explicit reciprocal OpponentID in PlayerResults
    pairs: list[tuple[int, int]] = []
    seen: set[int] = set()
    for pid, e in entries.items():
        opp = e.get("OpponentID")
        if opp and int(opp) > 0 and int(opp) in entries and pid not in seen and int(opp) not in seen:
            if int(entries[int(opp)].get("OpponentID") or 0) in (pid, 0):
                pairs.append((pid, int(opp)))
                seen.update((pid, int(opp)))
    if pairs:
        return pairs, "PlayerResults.OpponentID"
    ms = matchsetup_pairs(conn, lid, week_num)
    if ms:
        return ms, f"{lid}MatchSetup"
    return auto_pairs(ctx, conn, lid, week_num, entries), "auto_handicap_order"


# ---------------------------------------------------------------------------
# Match scoring
# ---------------------------------------------------------------------------

def score_match(ctx: dict[str, Any], a: dict[str, Any] | None, b: dict[str, Any] | None, pid_a: int, pid_b: int) -> dict[str, Any]:
    r = ctx["rules"]
    g = lambda k: float(r.get(k) or 0)  # noqa: E731
    mode = ctx["scoring_mode_name"]
    p_map = {p["PlayerID"]: p for p in ctx["players"]}

    def stub(pid: int) -> dict[str, Any]:
        p = p_map.get(pid, {})
        return {"PlayerID": pid, "TeamID": p.get("TeamID"), "PlayerName": f"{p.get('PlayerFirst','')} {p.get('PlayerLast','')}".strip() or f"Player #{pid}",
                "Handicap": float(p.get("Handicap") or 0), "played": False, "forfeit": False, "Gross": 0, "AdjGross": 0, "Net": 0,
                "holes": [], "adj_holes": [], "net_holes": [], "strokes": [], "Stableford": 0, "is_sub": False, "sub_name": None, "nine": "front"}

    A = a or stub(pid_a)
    B = b or stub(pid_b)
    out: dict[str, Any] = {"a": {}, "b": {}, "holes": [], "status": "scored", "breakdown": []}
    pts_a = pts_b = 0.0
    hw_a = hw_b = 0.0

    forfeit_pts = g("PlayerForfeit")
    present_pts = g("PresentPlayerPts") or forfeit_pts
    if A["played"] and B["played"] and not A["forfeit"] and not B["forfeit"]:
        holes_a = A["net_holes"]
        holes_b = B["net_holes"]
        hw_a, hw_b, codes = holes_won(holes_a, holes_b)
        gw_a, gw_b, _ = holes_won(A["adj_holes"], B["adj_holes"])
        if mode == "nines_plus_match":
            n = len(holes_a)
            if n >= 18:
                fa, fb = split_points(sum(holes_a[:9]), sum(holes_b[:9]), g("IndPtsNet"))
                ba, bb = split_points(sum(holes_a[9:]), sum(holes_b[9:]), g("IndPtsNet"))
                out["breakdown"].append({"item": "Front nine net", "a": fa, "b": fb})
                out["breakdown"].append({"item": "Back nine net", "a": ba, "b": bb})
                pts_a += fa + ba
                pts_b += fb + bb
            else:
                fa, fb = split_points(sum(holes_a), sum(holes_b), g("IndPtsNet"))
                out["breakdown"].append({"item": "Nine net", "a": fa, "b": fb})
                pts_a += fa
                pts_b += fb
            ma, mb = split_points(-hw_a, -hw_b, g("IndPtsHolesMatch"))
            out["breakdown"].append({"item": f"Holes-won match ({hw_a:g}-{hw_b:g})", "a": ma, "b": mb})
            pts_a += ma
            pts_b += mb
            if g("IndPtsNetMatch"):
                ra, rb = split_points(A["Net"], B["Net"], g("IndPtsNetMatch"))
                out["breakdown"].append({"item": "Low net round", "a": ra, "b": rb})
                pts_a += ra
                pts_b += rb
        else:
            if g("IndPtsNet"):
                out["breakdown"].append({"item": f"Net holes won x{g('IndPtsNet'):g}", "a": hw_a * g("IndPtsNet"), "b": hw_b * g("IndPtsNet")})
                pts_a += hw_a * g("IndPtsNet")
                pts_b += hw_b * g("IndPtsNet")
            if g("IndPtsAct"):
                out["breakdown"].append({"item": f"Gross holes won x{g('IndPtsAct'):g}", "a": gw_a * g("IndPtsAct"), "b": gw_b * g("IndPtsAct")})
                pts_a += gw_a * g("IndPtsAct")
                pts_b += gw_b * g("IndPtsAct")
            if g("IndPtsNetMatch"):
                ra, rb = split_points(A["Net"], B["Net"], g("IndPtsNetMatch"))
                out["breakdown"].append({"item": "Low net round", "a": ra, "b": rb})
                pts_a += ra
                pts_b += rb
            if g("IndPtsActMatch"):
                ra, rb = split_points(A["AdjGross"], B["AdjGross"], g("IndPtsActMatch"))
                out["breakdown"].append({"item": "Low gross round", "a": ra, "b": rb})
                pts_a += ra
                pts_b += rb
            if g("IndPtsHolesMatch"):
                ma, mb = split_points(-hw_a, -hw_b, g("IndPtsHolesMatch"))
                out["breakdown"].append({"item": f"Holes-won match ({hw_a:g}-{hw_b:g})", "a": ma, "b": mb})
                pts_a += ma
                pts_b += mb
        out["holes"] = [
            {"hole": i + 1, "a": A["holes"][i], "b": B["holes"][i], "a_net": holes_a[i], "b_net": holes_b[i], "winner": codes[i]}
            for i in range(len(holes_a))
        ]
    elif A["forfeit"] and not B["forfeit"]:
        pts_b = forfeit_pts
        out["status"] = "forfeit_a"
        out["breakdown"].append({"item": "Forfeit", "a": 0, "b": pts_b})
    elif B["forfeit"] and not A["forfeit"]:
        pts_a = forfeit_pts
        out["status"] = "forfeit_b"
        out["breakdown"].append({"item": "Forfeit", "a": pts_a, "b": 0})
    elif A["played"] and not B["played"]:
        pts_a = present_pts
        out["status"] = "absent_b"
        out["breakdown"].append({"item": "Opponent absent", "a": pts_a, "b": 0})
    elif B["played"] and not A["played"]:
        pts_b = present_pts
        out["status"] = "absent_a"
        out["breakdown"].append({"item": "Opponent absent", "a": 0, "b": pts_b})
    else:
        out["status"] = "no_scores"

    for side, E, pts, hw in (("a", A, pts_a, hw_a), ("b", B, pts_b, hw_b)):
        out[side] = {
            "PlayerID": E["PlayerID"], "PlayerName": E["PlayerName"], "TeamID": E.get("TeamID"), "Handicap": E["Handicap"],
            "Gross": E["Gross"], "AdjGross": E["AdjGross"], "Net": E["Net"], "Stableford": E.get("Stableford", 0),
            "holes_won": hw, "IndividualPts": round(pts, 2), "played": E["played"], "forfeit": E["forfeit"],
            "is_sub": E.get("is_sub", False), "sub_name": E.get("sub_name"), "nine": E.get("nine"),
        }
    return out


def compute_week(conn: sqlite3.Connection, lid: int, week_num: int) -> dict[str, Any]:
    """Pure computation of a week's matches, field points and team results (no writes)."""
    ctx = load_league_context(conn, lid)
    entries = load_week_entries(conn, ctx, lid, week_num)
    pairs, pair_source = resolve_pairs(ctx, conn, lid, week_num, entries)
    r = ctx["rules"]
    g = lambda k: float(r.get(k) or 0)  # noqa: E731

    matches = []
    ind_pts: dict[int, float] = {}
    holes_won_by_player: dict[int, float] = {}
    for pa, pb in pairs:
        m = score_match(ctx, entries.get(pa), entries.get(pb), pa, pb)
        matches.append(m)
        ind_pts[pa] = m["a"]["IndividualPts"]
        ind_pts[pb] = m["b"]["IndividualPts"]
        holes_won_by_player[pa] = m["a"]["holes_won"]
        holes_won_by_player[pb] = m["b"]["holes_won"]

    # Field points (per division when the league uses flights)
    fld: dict[int, float] = {}
    top = g("FieldTopPts") or g("IndPtsNetField")
    step = g("FieldStepPts") or g("IndNetFieldDiff")
    if top > 0:
        groups: dict[Any, list[tuple[int, float]]] = {}
        for pid, e in entries.items():
            if e["played"]:
                key = e.get("Division") if len(ctx["divisions"]) > 1 else None
                groups.setdefault(key, []).append((pid, e["Net"]))
        for grp in groups.values():
            fld.update(field_points(grp, top, step))

    # Team results
    team_results = []
    if ctx["num_man_teams"] > 1 and ctx["teams"]:
        sched_tbl = f"{lid}Schedule"
        sched = rows_as_dicts(conn.execute(f'SELECT * FROM "{sched_tbl}" WHERE "WeekNum"=?', (week_num,))) if table_exists(conn, sched_tbl) else []
        t_names = {t["TeamID"]: t.get("TeamName") for t in ctx["teams"]}
        members: dict[int, list[int]] = {}
        for e in entries.values():
            members.setdefault(int(e.get("TeamID") or 0), []).append(e["PlayerID"])
        for p in ctx["players"]:
            members.setdefault(int(p.get("TeamID") or 0), [])
            if p["PlayerID"] not in members[int(p.get("TeamID") or 0)]:
                members[int(p.get("TeamID") or 0)].append(p["PlayerID"])

        def team_agg(tid: int) -> dict[str, Any]:
            played = [entries[p] for p in members.get(tid, []) if p in entries and entries[p]["played"]]
            return {
                "TeamID": tid, "TeamName": t_names.get(tid, f"Team {tid}"),
                "TeamActual": sum(e["AdjGross"] for e in played),
                "TeamNet": sum(e["Net"] for e in played),
                "players_played": len(played),
                "ind_pts": round(sum(ind_pts.get(p, 0.0) for p in members.get(tid, [])), 2),
                "holes_won": sum(holes_won_by_player.get(p, 0.0) for p in members.get(tid, [])),
            }

        team_pairs: list[tuple[int, int]] = []
        if sched:
            row = sched[0]
            m_idx = 1
            while f"Match{m_idx}Team1" in row:
                t1, t2 = int(row.get(f"Match{m_idx}Team1") or 0), int(row.get(f"Match{m_idx}Team2") or 0)
                if t1 and t2:
                    team_pairs.append((t1, t2))
                m_idx += 1
        paired = {t for pr in team_pairs for t in pr}
        for t1, t2 in team_pairs:
            A, B = team_agg(t1), team_agg(t2)
            both = A["players_played"] > 0 and B["players_played"] > 0
            ma = mb = 0.0
            bd = []
            if both:
                x, y = split_points(A["TeamNet"], B["TeamNet"], g("TeamPtsNetMatch"))
                bd.append({"item": "Low team net", "a": x, "b": y}); ma += x; mb += y
                x, y = split_points(A["TeamActual"], B["TeamActual"], g("TeamPtsActMatch"))
                bd.append({"item": "Low team gross", "a": x, "b": y}); ma += x; mb += y
                x, y = split_points(-A["holes_won"], -B["holes_won"], g("TeamPtsHolesMatch"))
                bd.append({"item": f"Aggregate net holes won ({A['holes_won']:g}-{B['holes_won']:g})", "a": x, "b": y}); ma += x; mb += y
            elif A["players_played"] > 0:
                ma = g("TeamForfeit") or g("PresentTeamPts")
            elif B["players_played"] > 0:
                mb = g("TeamForfeit") or g("PresentTeamPts")
            use_ind = int(r.get("UseIndPts") or 0) == 1 or not any((g("TeamPtsNetMatch"), g("TeamPtsActMatch"), g("TeamPtsHolesMatch")))
            for T, mp, opp in ((A, ma, t2), (B, mb, t1)):
                team_results.append({**T, "OpponentTeamID": opp, "MatchPts": round(mp, 2),
                                     "TeamPts": round(mp + (T["ind_pts"] if use_ind else 0.0), 2), "breakdown": bd})
        for t in ctx["teams"]:
            if t["TeamID"] not in paired:
                T = team_agg(t["TeamID"])
                team_results.append({**T, "OpponentTeamID": None, "MatchPts": 0.0, "TeamPts": T["ind_pts"], "breakdown": []})

    return {
        "league_id": lid,
        "week_num": week_num,
        "scoring_mode_name": ctx["scoring_mode_name"],
        "adjust_mode_name": ctx["adjust_mode_name"],
        "pair_source": pair_source,
        "matches": matches,
        "field_points": sorted(
            [{"PlayerID": pid, "PlayerName": entries[pid]["PlayerName"], "Net": entries[pid]["Net"], "Division": entries[pid].get("Division"), "FieldPts": pts}
             for pid, pts in fld.items()], key=lambda x: (-x["FieldPts"], x["Net"])),
        "team_results": team_results,
        "entries": {pid: {k: v for k, v in e.items() if k not in ("pars",)} for pid, e in entries.items()},
        "_ctx": ctx,
        "_ind_pts": ind_pts,
        "_fld": fld,
    }


# ---------------------------------------------------------------------------
# Persist (CDX-F3: single transaction; snapshots + rollups)
# ---------------------------------------------------------------------------

def _snapshot(conn: sqlite3.Connection, tbl: str, week_num: int, values: dict[int, Any]) -> None:
    if not table_exists(conn, tbl) or not values:
        return
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{tbl}")')]
    id_cols = [c for c in cols if c.startswith("ID")]
    exists = conn.execute(f'SELECT 1 FROM "{tbl}" WHERE "WeekNum"=?', (week_num,)).fetchone()
    if not exists:
        conn.execute(f'INSERT INTO "{tbl}" ("WeekNum") VALUES (?)', (week_num,))
    sets, params = [], []
    for pid, v in values.items():
        col = f"ID{pid}"
        if col in id_cols:
            sets.append(f'"{col}"=?')
            params.append(v)
    if sets:
        conn.execute(f'UPDATE "{tbl}" SET {", ".join(sets)} WHERE "WeekNum"=?', (*params, week_num))


def auto_score_week(conn: sqlite3.Connection, lid: int, week_num: int) -> dict[str, Any]:
    res = compute_week(conn, lid, week_num)
    ctx = res.pop("_ctx")
    ind_pts = res.pop("_ind_pts")
    fld = res.pop("_fld")
    res_tbl = f"{lid}PlayerResults"
    tr_tbl = f"{lid}TeamResults"
    p_tbl = f"{lid}Players"
    t_tbl = f"{lid}Teams"
    par_total = sum(ctx["pars18"][:ctx["num_holes"]]) if ctx["num_holes"] >= 18 else None

    with conn:
        # Opponents + individual/field points
        for m in res["matches"]:
            for side, other in (("a", "b"), ("b", "a")):
                pid = m[side]["PlayerID"]
                opp = m[other]["PlayerID"]
                if conn.execute(f'SELECT 1 FROM "{res_tbl}" WHERE "WeekNum"=? AND "PlayerID"=?', (week_num, pid)).fetchone():
                    conn.execute(f'UPDATE "{res_tbl}" SET "OpponentID"=?, "IndividualPts"=? WHERE "WeekNum"=? AND "PlayerID"=?',
                                 (opp, m[side]["IndividualPts"], week_num, pid))
        for pid, e in res["entries"].items():
            conn.execute(f'UPDATE "{res_tbl}" SET "FieldPts"=? WHERE "WeekNum"=? AND "PlayerID"=?', (fld.get(pid, 0.0), week_num, pid))
        # Snapshots (AdjScores / ActScores / AdjOverPar / Handicaps)
        played = {pid: e for pid, e in res["entries"].items() if e["played"]}
        _snapshot(conn, f"{lid}AdjScores", week_num, {pid: e["AdjGross"] for pid, e in played.items()})
        _snapshot(conn, f"{lid}ActScores", week_num, {pid: e["Gross"] for pid, e in played.items()})
        _snapshot(conn, f"{lid}Handicaps", week_num, {pid: e["Handicap"] for pid, e in played.items()})
        _snapshot(conn, f"{lid}AdjOverPar", week_num, {pid: e["AdjGross"] - sum(e["adj_holes"] and ctx["pars18"][:9] if e["nine"] == "front" else ctx["pars18"][9:18] if e["nine"] == "back" else ctx["pars18"][:18]) for pid, e in played.items()})
        # Team results
        if table_exists(conn, tr_tbl):
            for t in res["team_results"]:
                row = conn.execute(f'SELECT 1 FROM "{tr_tbl}" WHERE "WeekNum"=? AND "TeamID"=?', (week_num, t["TeamID"])).fetchone()
                vals = (t["TeamPts"], t["MatchPts"], 0, t["TeamActual"], t["TeamNet"])
                if row:
                    conn.execute(f'UPDATE "{tr_tbl}" SET "TeamPts"=?, "MatchPts"=?, "FieldPts"=?, "TeamActual"=?, "TeamNet"=? WHERE "WeekNum"=? AND "TeamID"=?',
                                 (*vals, week_num, t["TeamID"]))
                else:
                    conn.execute(f'INSERT INTO "{tr_tbl}" ("WeekNum","TeamID","TeamPts","MatchPts","FieldPts","TeamActual","TeamNet","SubPts","UserDefinedPts") VALUES (?,?,?,?,?,?,?,0,0)',
                                 (week_num, t["TeamID"], *vals))
        # Season roll-ups
        for row in conn.execute(f'SELECT "PlayerID", COALESCE(SUM("IndividualPts"),0)+COALESCE(SUM("FieldPts"),0) FROM "{res_tbl}" GROUP BY "PlayerID"').fetchall():
            conn.execute(f'UPDATE "{p_tbl}" SET "Points"=? WHERE "PlayerID"=?', (round(float(row[1]), 2), row[0]))
        if table_exists(conn, tr_tbl) and table_exists(conn, t_tbl):
            for row in conn.execute(f'SELECT "TeamID", COALESCE(SUM("TeamPts"),0) FROM "{tr_tbl}" GROUP BY "TeamID"').fetchall():
                conn.execute(f'UPDATE "{t_tbl}" SET "Points"=? WHERE "TeamID"=?', (round(float(row[1]), 2), row[0]))
    res["persisted"] = True
    res["par_total"] = par_total
    return res


# ---------------------------------------------------------------------------
# Clubhouse sheet (AGY-F4 / CDX-F4)
# ---------------------------------------------------------------------------

def clubhouse_sheet(conn: sqlite3.Connection, lid: int, week_num: int) -> dict[str, Any]:
    from .golf_engine import get_week_scorecard

    res = compute_week(conn, lid, week_num)
    ctx = res.pop("_ctx")
    res.pop("_ind_pts", None)
    res.pop("_fld", None)
    sc = get_week_scorecard(conn, lid, week_num)
    sched = sc.get("schedule") or {}
    tt_tbl = f"{lid}TeeTimes"
    tt_rows = rows_as_dicts(conn.execute(f'SELECT * FROM "{tt_tbl}" ORDER BY "MatchNum"')) if table_exists(conn, tt_tbl) else []
    groups = max(1, (len(res["matches"]) + 1) // 2)
    times = [r.get("Ttime") for r in tt_rows if r.get("Ttime")] or tee_times(ctx["league"].get("FirstTeeTime"), ctx["league"].get("MinsBetweenGroups"), groups)
    while len(times) < groups:
        times.append(str(times[-1]) if times else "")
    for i, m in enumerate(res["matches"]):
        m["tee_time"] = times[i // 2] if times else None
        m["group"] = i // 2 + 1
    leaders = sorted(ctx["players"], key=lambda p: (-float(p.get("Points") or 0), float(p.get("Handicap") or 0)))[:12]
    return {
        "league": {k: ctx["league"].get(k) for k in ("LeagueID", "LeagueName", "LeagueNickname", "LeagueDay", "LeagueHoles", "NumManTeams", "FirstTeeTime", "MinsBetweenGroups")},
        "course": {"CourseName": ctx["course"].get("CourseName"), "total_par": ctx["course"].get("total_par"), "front_par": ctx["course"].get("front_par"), "back_par": ctx["course"].get("back_par")},
        "week_num": week_num,
        "date": sched.get("Date"),
        "weather": sched.get("Weather"),
        "nine": scheduled_nine(conn, lid, week_num) if ctx["num_holes"] == 9 else "both",
        "rules": rules_summary(ctx)["human_rules"],
        "matchups": res["matches"],
        "pair_source": res["pair_source"],
        "team_results": res["team_results"],
        "team_standings": [{k: t.get(k) for k in ("TeamID", "TeamName", "Points", "PrevPts", "Handicap", "Money")} for t in ctx["teams"]],
        "individual_leaders": [{"PlayerID": p["PlayerID"], "PlayerName": f"{p.get('PlayerFirst','')} {p.get('PlayerLast','')}".strip(), "TeamID": p.get("TeamID"), "Handicap": p.get("Handicap"), "Points": p.get("Points")} for p in leaders],
        "field_points": res["field_points"],
        "gross_skins": sc.get("gross_skins", []),
        "net_skins": sc.get("net_skins", []),
        "stableford": sorted([{"PlayerID": pid, "PlayerName": e["PlayerName"], "Stableford": e["Stableford"], "Net": e["Net"]} for pid, e in res["entries"].items() if e["played"]], key=lambda x: (-x["Stableford"], x["Net"])),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
