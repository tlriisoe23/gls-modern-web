"""ECGC Historical Data Importer for Golf League Secretary Modern Web.

Imports Edwards County Golf Course (Kinsley, KS) and 18 historical
season-divisions (2018-2026 Men's Twilight League and Women's League)
from /workspace/ecgc-modern/data/ecgc.sqlite and brackets.json into gls9.db.
Populates both normalized ECGC archive/analytics tables and native GLS9
per-league tables (<lid>Teams, <lid>Players, <lid>Schedule, <lid>PlayerResults, etc.).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_ECGC_SQLITE = Path("/workspace/ecgc-modern/data/ecgc.sqlite")
DEFAULT_BRACKETS_JSON = Path("/workspace/ecgc-modern/public/assets/brackets/brackets.json")

ECGC_COURSE_ID = 5
ECGC_COURSE_NAME = "Edwards County Golf Course"
ECGC_PARS = [4, 4, 4, 3, 5, 5, 4, 3, 4]
ECGC_HOLE_CAPS = [13, 1, 9, 7, 11, 5, 3, 15, 17]
ECGC_HOLE_RANKS = [7, 1, 5, 4, 6, 3, 2, 8, 9]  # Rank 1=Hole 2, Rank 9=Hole 9
ECGC_BLUE_YARDS = [307, 384, 313, 199, 481, 519, 392, 166, 272]
ECGC_WHITE_YARDS = [300, 374, 301, 192, 472, 513, 384, 156, 268]
ECGC_RED_YARDS = [293, 298, 227, 183, 435, 405, 310, 146, 253]

# 18 Season-Divisions mapping (Year, slug, gls_league_id, name, day, holes, weeks)
SEASON_DIVISIONS = [
    (2018, "mens", 20181, "2018 ECGC Men's League & Tournaments", "Wednesday", 9, 16),
    (2018, "womens", 20182, "2018 ECGC Women's League & Tournaments", "Tuesday", 9, 10),
    (2019, "mens", 20191, "2019 ECGC Men's Twilight League", "Wednesday", 9, 16),
    (2019, "womens", 20192, "2019 ECGC Women's League", "Tuesday", 9, 10),
    (2020, "mens", 20201, "2020 ECGC Men's Twilight League", "Wednesday", 9, 16),
    (2020, "womens", 20202, "2020 ECGC Women's League", "Tuesday", 9, 10),
    (2021, "mens", 20211, "2021 ECGC Men's Twilight League", "Wednesday", 9, 16),
    (2021, "womens", 20212, "2021 ECGC Women's League", "Tuesday", 9, 10),
    (2022, "mens", 20221, "2022 ECGC Men's Twilight League", "Wednesday", 9, 16),
    (2022, "womens", 20222, "2022 ECGC Women's League", "Tuesday", 9, 10),
    (2023, "mens", 20231, "2023 ECGC Men's Twilight League", "Wednesday", 9, 16),
    (2023, "womens", 20232, "2023 ECGC Women's League", "Tuesday", 9, 10),
    (2024, "mens", 20241, "2024 ECGC Men's Twilight League", "Wednesday", 9, 16),
    (2024, "womens", 20242, "2024 ECGC Women's League", "Tuesday", 9, 10),
    (2025, "mens", 20251, "2025 ECGC Men's Twilight League", "Wednesday", 9, 16),
    (2025, "womens", 20252, "2025 ECGC Women's League", "Tuesday", 9, 10),
    (2026, "mens", 20261, "2026 ECGC Men's Twilight League", "Wednesday", 9, 16),
    (2026, "womens", 20262, "2026 ECGC Women's League", "Tuesday", 9, 12),
]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    )
    return cur.fetchone() is not None


def ensure_ecgc_course(conn: sqlite3.Connection) -> dict[str, Any]:
    """Ensure Edwards County Golf Course (Kinsley, KS) and its tees exist in Courses and CourseTees."""
    # 1. CourseTees table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS CourseTees (
            TeeID INTEGER PRIMARY KEY AUTOINCREMENT,
            CourseID INTEGER NOT NULL,
            TeeName TEXT NOT NULL,
            Rating REAL NOT NULL,
            Slope INTEGER NOT NULL,
            TotalYards INTEGER NOT NULL,
            FrontYards INTEGER NOT NULL,
            BackYards INTEGER DEFAULT 0,
            Par INTEGER NOT NULL,
            Color TEXT
        )
    """)

    # 2. Courses row
    conn.execute('DELETE FROM "Courses" WHERE "CourseID"=?', (ECGC_COURSE_ID,))
    if True:
        conn.execute(
            """
            INSERT INTO "Courses" (
                "CourseID", "CourseName", "NumHoles", "Nine1Name", "Nine1Rating", "Nine1Slope",
                "Nine2Name", "Nine2Rating", "Nine2Slope", "Nine3Name", "Nine3Rating", "Nine3Slope",
                "Nine4Name", "Nine4Rating", "Nine4Slope", "Tees", "SlopeRating", "CourseRating",
                "CourseStreet", "CourseCity", "CourseState", "CourseZip", "CoursePhone", "CourseFax", "ProName"
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ECGC_COURSE_ID,
                ECGC_COURSE_NAME,
                9,
                "9-Hole Course",
                34.4,
                113,
                "NA",
                0,
                0,
                "3rd Nine",
                0,
                0,
                "4th Nine",
                0,
                0,
                "Blue",
                113,
                34.4,
                "1044 O Rd",
                "Kinsley",
                "KS",
                "67547",
                "(620) 659-3351",
                None,
                "Blake Cramer",
            ),
        )

    # 3. CoursePar
    if table_exists(conn, "CoursePar"):
        conn.execute('DELETE FROM "CoursePar" WHERE "CourseID"=?', (ECGC_COURSE_ID,))
        par_cols = [f"Hole{h:02d}Par" for h in range(1, 37)]
        par_vals = ECGC_PARS + [0] * 27
        placeholders = ",".join(["?"] * 37)
        conn.execute(
            f'INSERT INTO "CoursePar" ("CourseID", {", ".join(f"{c}" for c in par_cols)}) VALUES ({placeholders})',
            [ECGC_COURSE_ID] + par_vals,
        )

    # 4. CourseHandicap
    if table_exists(conn, "CourseHandicap"):
        conn.execute('DELETE FROM "CourseHandicap" WHERE "CourseID"=?', (ECGC_COURSE_ID,))
        cap_cols = [f"Hole{h:02d}Cap" for h in range(1, 37)]
        cap_vals = ECGC_HOLE_CAPS + [0] * 27
        placeholders = ",".join(["?"] * 37)
        conn.execute(
            f'INSERT INTO "CourseHandicap" ("CourseID", {", ".join(f"{c}" for c in cap_cols)}) VALUES ({placeholders})',
            [ECGC_COURSE_ID] + cap_vals,
        )

    # 5. CourseYards
    if table_exists(conn, "CourseYards"):
        conn.execute('DELETE FROM "CourseYards" WHERE "CourseID"=?', (ECGC_COURSE_ID,))
        yd_cols = [f"Hole{h:02d}Yards" for h in range(1, 37)]
        yd_vals = ECGC_BLUE_YARDS + [0] * 27
        placeholders = ",".join(["?"] * 37)
        conn.execute(
            f'INSERT INTO "CourseYards" ("CourseID", {", ".join(f"{c}" for c in yd_cols)}) VALUES ({placeholders})',
            [ECGC_COURSE_ID] + yd_vals,
        )

    # 6. CourseTees rows
    conn.execute('DELETE FROM CourseTees WHERE CourseID=?', (ECGC_COURSE_ID,))
    tees_data = [
        (ECGC_COURSE_ID, "Blue", 34.4, 113, 3033, 3033, 0, 36, "#1d4ed8"),
        (ECGC_COURSE_ID, "White", 34.0, 111, 2960, 2960, 0, 36, "#475569"),
        (ECGC_COURSE_ID, "Red", 34.5, 112, 2550, 2550, 0, 36, "#b91c1c"),
    ]
    conn.executemany(
        """
        INSERT INTO CourseTees (CourseID, TeeName, Rating, Slope, TotalYards, FrontYards, BackYards, Par, Color)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tees_data,
    )

    return {
        "course_id": ECGC_COURSE_ID,
        "name": ECGC_COURSE_NAME,
        "tees": ["Blue", "White", "Red"],
        "par": 36,
    }


def ensure_normalized_ecgc_tables(conn: sqlite3.Connection) -> None:
    """Create normalized ECGC archive, analytics, bracket, and rules tables in gls9.db."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ecgc_seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_year INTEGER NOT NULL,
            league_slug TEXT NOT NULL,
            league_name TEXT NOT NULL,
            gls_league_id INTEGER NOT NULL UNIQUE,
            weekday TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            event_count INTEGER DEFAULT 0,
            team_count INTEGER DEFAULT 0,
            player_count INTEGER DEFAULT 0,
            champion_team TEXT,
            runner_up_team TEXT,
            UNIQUE(season_year, league_slug)
        );

        CREATE TABLE IF NOT EXISTS ecgc_players (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            primary_division TEXT NOT NULL DEFAULT 'mens',
            active_flag INTEGER NOT NULL DEFAULT 1,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS ecgc_teams (
            id INTEGER PRIMARY KEY,
            season_year INTEGER NOT NULL,
            league_slug TEXT NOT NULL,
            team_number INTEGER,
            team_name TEXT NOT NULL,
            division_half TEXT,
            final_rank INTEGER,
            total_points REAL DEFAULT 0,
            gls_league_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS ecgc_team_members (
            id INTEGER PRIMARY KEY,
            team_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            season_year INTEGER NOT NULL,
            league_slug TEXT NOT NULL,
            role TEXT DEFAULT 'player'
        );

        CREATE TABLE IF NOT EXISTS ecgc_events (
            id INTEGER PRIMARY KEY,
            season_year INTEGER NOT NULL,
            league_slug TEXT NOT NULL,
            event_code TEXT NOT NULL,
            week_number INTEGER NOT NULL,
            stage TEXT NOT NULL DEFAULT 'regular',
            event_title TEXT NOT NULL,
            event_date TEXT,
            course_par_json TEXT NOT NULL,
            hole_handicap_json TEXT NOT NULL,
            source_url TEXT,
            gls_league_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS ecgc_matches (
            id INTEGER PRIMARY KEY,
            event_id INTEGER NOT NULL,
            season_year INTEGER NOT NULL,
            league_slug TEXT NOT NULL,
            match_number INTEGER NOT NULL,
            team_a_id INTEGER,
            team_a_name TEXT NOT NULL,
            team_a_points REAL DEFAULT 0,
            team_b_id INTEGER,
            team_b_name TEXT NOT NULL,
            team_b_points REAL DEFAULT 0,
            winner_label TEXT,
            result_summary TEXT,
            gls_league_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS ecgc_rounds (
            id INTEGER PRIMARY KEY,
            event_id INTEGER NOT NULL,
            match_id INTEGER,
            season_year INTEGER NOT NULL,
            league_slug TEXT NOT NULL,
            team_id INTEGER,
            team_name TEXT,
            player_id INTEGER,
            player_name TEXT NOT NULL,
            handicap REAL,
            gross_total INTEGER,
            net_total INTEGER,
            over_under TEXT,
            points_adjustment REAL DEFAULT 0,
            gls_league_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS ecgc_hole_scores (
            id INTEGER PRIMARY KEY,
            round_id INTEGER NOT NULL,
            hole_number INTEGER NOT NULL,
            par INTEGER NOT NULL,
            gross_score INTEGER NOT NULL,
            net_score INTEGER NOT NULL,
            strokes_received INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS ecgc_standings (
            id INTEGER PRIMARY KEY,
            season_id INTEGER,
            season_year INTEGER NOT NULL,
            league_slug TEXT NOT NULL,
            half_label TEXT NOT NULL,
            split_name TEXT NOT NULL,
            rank INTEGER NOT NULL,
            team_id INTEGER,
            team_name TEXT NOT NULL,
            players_label TEXT NOT NULL,
            points REAL NOT NULL,
            gross_avg REAL NOT NULL,
            net_avg REAL NOT NULL,
            games_behind REAL DEFAULT 0,
            wins REAL DEFAULT 0,
            losses REAL DEFAULT 0,
            ties REAL DEFAULT 0,
            hole_scores_json TEXT DEFAULT '[]',
            gls_league_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS ecgc_brackets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_year INTEGER NOT NULL,
            league_slug TEXT NOT NULL,
            title TEXT NOT NULL,
            source_url TEXT,
            local_path TEXT,
            playoff_champion TEXT,
            playoff_runner_up TEXT,
            playoff_finalists TEXT,
            rounds_count INTEGER DEFAULT 4
        );

        CREATE TABLE IF NOT EXISTS league_rules_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league_id INTEGER NOT NULL UNIQUE,
            rule_type TEXT NOT NULL DEFAULT 'ecgc_2person_match',
            holes_count INTEGER NOT NULL DEFAULT 9,
            points_per_hole_win REAL NOT NULL DEFAULT 1.0,
            points_per_hole_tie REAL NOT NULL DEFAULT 0.5,
            match_hole_points_total REAL NOT NULL DEFAULT 9.0,
            net_bonus_enabled INTEGER NOT NULL DEFAULT 1,
            net_bonus_below_max INTEGER NOT NULL DEFAULT 35,
            net_bonus_pts REAL NOT NULL DEFAULT 1.0,
            net_even_min INTEGER NOT NULL DEFAULT 36,
            net_even_max INTEGER NOT NULL DEFAULT 36,
            net_even_pts REAL NOT NULL DEFAULT 0.0,
            net_penalty_above_min INTEGER NOT NULL DEFAULT 37,
            net_penalty_pts REAL NOT NULL DEFAULT -1.0,
            handicap_progression_mode TEXT NOT NULL DEFAULT 'weekly_pt',
            plus_handicaps_enabled INTEGER NOT NULL DEFAULT 1,
            unplayed_round_score INTEGER NOT NULL DEFAULT -36
        );
    """)


def import_ecgc_data(
    gls_conn: sqlite3.Connection,
    ecgc_sqlite_path: Path = DEFAULT_ECGC_SQLITE,
    brackets_json_path: Path = DEFAULT_BRACKETS_JSON,
) -> dict[str, Any]:
    """Perform the complete import of ECGC course, archive, brackets, rules, and 18 GLS9 leagues."""
    if not ecgc_sqlite_path.exists():
        raise FileNotFoundError(f"ECGC SQLite database not found at {ecgc_sqlite_path}")

    # Step 1: Ensure Course and Tees
    course_info = ensure_ecgc_course(gls_conn)

    # Step 2: Ensure Normalized Tables
    ensure_normalized_ecgc_tables(gls_conn)

    # Step 3: Connect to ecgc.sqlite and copy archive data
    src_conn = sqlite3.connect(str(ecgc_sqlite_path))
    src_conn.row_factory = sqlite3.Row

    # Copy ecgc_players (128 canonical players)
    players_rows = src_conn.execute("SELECT * FROM league_players").fetchall()
    gls_conn.execute("DELETE FROM ecgc_players")
    gls_conn.executemany(
        """
        INSERT INTO ecgc_players (id, slug, display_name, first_name, last_name, primary_division, active_flag, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["id"],
                r["slug"],
                r["display_name"],
                r["first_name"],
                r["last_name"],
                r["primary_division"],
                r["active_flag"],
                r["created_at"],
            )
            for r in players_rows
        ],
    )

    # Build mapping (season_year, league_slug) -> gls_league_id
    year_div_to_lid = {
        (s[0], s[1]): s[2] for s in SEASON_DIVISIONS
    }

    # Copy ecgc_teams (244 teams)
    teams_rows = src_conn.execute("SELECT * FROM league_teams").fetchall()
    gls_conn.execute("DELETE FROM ecgc_teams")
    gls_conn.executemany(
        """
        INSERT INTO ecgc_teams (id, season_year, league_slug, team_number, team_name, division_half, final_rank, total_points, gls_league_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["id"],
                r["season_year"],
                r["league_slug"],
                r["team_number"],
                r["team_name"],
                r["division_half"],
                r["final_rank"],
                float(r["total_points"] or 0),
                year_div_to_lid.get((r["season_year"], r["league_slug"])),
            )
            for r in teams_rows
        ],
    )

    # Copy ecgc_team_members (472 explicit roster memberships + 161 round/substitute appearances = 633 total)
    members_rows = src_conn.execute("SELECT * FROM league_team_members").fetchall()
    gls_conn.execute("DELETE FROM ecgc_team_members")
    seen_tp = set()
    member_tuples = []
    max_mid = 0
    for r in members_rows:
        mid = int(r["id"])
        max_mid = max(max_mid, mid)
        seen_tp.add((int(r["team_id"]), int(r["player_id"])))
        member_tuples.append((mid, r["team_id"], r["player_id"], r["season_year"], r["league_slug"], r["role"] or "member"))

    extra_rows = src_conn.execute("""
        SELECT DISTINCT team_id, player_id, season_year, league_slug,
               CASE WHEN team_name LIKE '%SUB%' THEN 'substitute' ELSE 'sub_or_alt' END AS role
        FROM league_rounds
        WHERE team_id IS NOT NULL AND player_id IS NOT NULL
        ORDER BY season_year, league_slug, team_id, player_id
    """).fetchall()
    for r in extra_rows:
        key = (int(r["team_id"]), int(r["player_id"]))
        if key not in seen_tp:
            seen_tp.add(key)
            max_mid += 1
            member_tuples.append((max_mid, r["team_id"], r["player_id"], r["season_year"], r["league_slug"], r["role"]))

    gls_conn.executemany(
        """
        INSERT INTO ecgc_team_members (id, team_id, player_id, season_year, league_slug, role)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        member_tuples,
    )

    # Copy ecgc_events (206 events)
    events_rows = src_conn.execute("SELECT * FROM league_events").fetchall()
    gls_conn.execute("DELETE FROM ecgc_events")
    gls_conn.executemany(
        """
        INSERT INTO ecgc_events (id, season_year, league_slug, event_code, week_number, stage, event_title, event_date, course_par_json, hole_handicap_json, source_url, gls_league_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["id"],
                r["season_year"],
                r["league_slug"],
                r["event_code"],
                r["week_number"],
                r["stage"],
                r["event_title"],
                r["event_date"],
                r["course_par_json"],
                r["hole_handicap_json"],
                r["source_url"],
                year_div_to_lid.get((r["season_year"], r["league_slug"])),
            )
            for r in events_rows
        ],
    )

    # Copy ecgc_matches (1,611 matches)
    matches_rows = src_conn.execute("SELECT * FROM league_matches").fetchall()
    gls_conn.execute("DELETE FROM ecgc_matches")
    gls_conn.executemany(
        """
        INSERT INTO ecgc_matches (id, event_id, season_year, league_slug, match_number, team_a_id, team_a_name, team_a_points, team_b_id, team_b_name, team_b_points, winner_label, result_summary, gls_league_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["id"],
                r["event_id"],
                r["season_year"],
                r["league_slug"],
                r["match_number"],
                r["team_a_id"],
                r["team_a_name"],
                float(r["team_a_points"] or 0),
                r["team_b_id"],
                r["team_b_name"],
                float(r["team_b_points"] or 0),
                r["winner_label"],
                r["result_summary"],
                year_div_to_lid.get((r["season_year"], r["league_slug"])),
            )
            for r in matches_rows
        ],
    )

    # Copy ecgc_rounds (5,521 rounds)
    rounds_rows = src_conn.execute("SELECT * FROM league_rounds").fetchall()
    gls_conn.execute("DELETE FROM ecgc_rounds")
    gls_conn.executemany(
        """
        INSERT INTO ecgc_rounds (id, event_id, match_id, season_year, league_slug, team_id, team_name, player_id, player_name, handicap, gross_total, net_total, over_under, points_adjustment, gls_league_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["id"],
                r["event_id"],
                r["match_id"],
                r["season_year"],
                r["league_slug"],
                r["team_id"],
                r["team_name"],
                r["player_id"],
                r["player_name"],
                float(r["handicap"]) if r["handicap"] is not None else None,
                r["gross_total"],
                r["net_total"],
                r["over_under"],
                float(r["points_adjustment"] or 0),
                year_div_to_lid.get((r["season_year"], r["league_slug"])),
            )
            for r in rounds_rows
        ],
    )

    # Copy ecgc_hole_scores (49,689 hole scores)
    hole_rows = src_conn.execute("SELECT * FROM league_hole_scores").fetchall()
    gls_conn.execute("DELETE FROM ecgc_hole_scores")
    gls_conn.executemany(
        """
        INSERT INTO ecgc_hole_scores (id, round_id, hole_number, par, gross_score, net_score, strokes_received)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["id"],
                r["round_id"],
                r["hole_number"],
                r["par"],
                r["gross_score"],
                r["net_score"],
                r["strokes_received"],
            )
            for r in hole_rows
        ],
    )

    # Copy ecgc_standings (698 standings)
    standings_rows = src_conn.execute("SELECT * FROM league_standings").fetchall()
    gls_conn.execute("DELETE FROM ecgc_standings")
    gls_conn.executemany(
        """
        INSERT INTO ecgc_standings (id, season_id, season_year, league_slug, half_label, split_name, rank, team_id, team_name, players_label, points, gross_avg, net_avg, games_behind, wins, losses, ties, hole_scores_json, gls_league_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["id"],
                r["season_id"],
                r["season_year"],
                r["league_slug"],
                r["half_label"],
                r["split_name"],
                r["rank"],
                r["team_id"],
                r["team_name"],
                r["players_label"],
                float(r["points"] or 0),
                float(r["gross_avg"] or 0),
                float(r["net_avg"] or 0),
                float(r["games_behind"] or 0),
                float(r["wins"] or 0),
                float(r["losses"] or 0),
                float(r["ties"] or 0),
                r["hole_scores_json"] or "[]",
                year_div_to_lid.get((r["season_year"], r["league_slug"])),
            )
            for r in standings_rows
        ],
    )

    # Backfill gross_avg and net_avg from authentic ecgc_rounds where source standings had 0.0
    gls_conn.execute(
        """
        UPDATE ecgc_standings
        SET 
          gross_avg = COALESCE((
            SELECT ROUND(AVG(r.gross_total), 1)
            FROM ecgc_rounds r
            WHERE r.season_year = ecgc_standings.season_year
              AND r.league_slug = ecgc_standings.league_slug
              AND r.team_id = ecgc_standings.team_id
              AND r.gross_total > 0
          ), gross_avg),
          net_avg = COALESCE((
            SELECT ROUND(AVG(r.net_total), 1)
            FROM ecgc_rounds r
            WHERE r.season_year = ecgc_standings.season_year
              AND r.league_slug = ecgc_standings.league_slug
              AND r.team_id = ecgc_standings.team_id
              AND r.net_total > 0
          ), net_avg)
        WHERE gross_avg = 0.0 OR gross_avg IS NULL;
        """
    )

    # Copy ecgc_brackets (11 brackets from brackets.json)
    gls_conn.execute("DELETE FROM ecgc_brackets")
    gls_conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('ecgc_seasons', 'ecgc_brackets', 'ecgc_team_members', 'league_rules_config')")
    brackets_data = []
    if brackets_json_path.exists():
        with open(brackets_json_path, encoding="utf-8") as bf:
            b_list = json.load(bf)
            for b in b_list:
                brackets_data.append((
                    b.get("id"),
                    b.get("year", 2026),
                    b.get("league_slug", "mens"),
                    b.get("title", "Playoff Bracket"),
                    b.get("source_url", ""),
                    b.get("local_path", ""),
                    b.get("playoff_champion", ""),
                    b.get("playoff_runner_up", ""),
                    b.get("playoff_finalists", ""),
                    4,
                ))
    if brackets_data:
        gls_conn.executemany(
            """
            INSERT INTO ecgc_brackets (id, season_year, league_slug, title, source_url, local_path, playoff_champion, playoff_runner_up, playoff_finalists, rounds_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            brackets_data,
        )

    # Step 4: Populate ecgc_seasons & league_rules_config for all 18 season-divisions
    gls_conn.execute("DELETE FROM ecgc_seasons")
    gls_conn.execute("DELETE FROM league_rules_config WHERE league_id >= 20180")

    seasons_data = []
    rules_data = []

    for year, slug, lid, title, day, holes, weeks in SEASON_DIVISIONS:
        # Check team and player counts
        t_cnt = gls_conn.execute(
            "SELECT COUNT(*) FROM ecgc_teams WHERE season_year=? AND league_slug=?",
            (year, slug),
        ).fetchone()[0]
        e_cnt = gls_conn.execute(
            "SELECT COUNT(*) FROM ecgc_events WHERE season_year=? AND league_slug=?",
            (year, slug),
        ).fetchone()[0]
        p_cnt = gls_conn.execute(
            "SELECT COUNT(DISTINCT player_id) FROM ecgc_rounds WHERE season_year=? AND league_slug=? AND player_id IS NOT NULL",
            (year, slug),
        ).fetchone()[0]
        if p_cnt == 0 and t_cnt > 0:
            p_cnt = t_cnt * 2

        # Check bracket for champions
        br = gls_conn.execute(
            "SELECT playoff_champion, playoff_runner_up FROM ecgc_brackets WHERE season_year=? AND league_slug=?",
            (year, slug),
        ).fetchone()
        champ = br[0] if br and br[0] else ""
        runup = br[1] if br and br[1] else ""

        seasons_data.append((
            year,
            slug,
            title,
            lid,
            day,
            f"{year}-04-15" if slug == "mens" else f"{year}-05-01",
            f"{year}-08-20" if slug == "mens" else f"{year}-07-30",
            e_cnt,
            t_cnt,
            p_cnt,
            champ,
            runup,
        ))

        rules_data.append((
            lid,
            "ecgc_2person_match",
            holes,
            1.0,
            0.5,
            9.0,
            1,
            35,
            1.0,
            36,
            36,
            0.0,
            37,
            -1.0,
            "weekly_pt",
            1,
            -36,
        ))

    gls_conn.executemany(
        """
        INSERT INTO ecgc_seasons (season_year, league_slug, league_name, gls_league_id, weekday, start_date, end_date, event_count, team_count, player_count, champion_team, runner_up_team)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        seasons_data,
    )

    gls_conn.executemany(
        """
        INSERT INTO league_rules_config (league_id, rule_type, holes_count, points_per_hole_win, points_per_hole_tie, match_hole_points_total, net_bonus_enabled, net_bonus_below_max, net_bonus_pts, net_even_min, net_even_max, net_even_pts, net_penalty_above_min, net_penalty_pts, handicap_progression_mode, plus_handicaps_enabled, unplayed_round_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rules_data,
    )

    # Step 5: Populate native GLS9 tables for each of the 18 leagues
    populate_native_gls9_leagues(gls_conn)

    return {
        "status": "ok",
        "seasons_count": len(SEASON_DIVISIONS),
        "players_count": len(players_rows),
        "teams_count": len(teams_rows),
        "events_count": len(events_rows),
        "matches_count": len(matches_rows),
        "rounds_count": len(rounds_rows),
        "hole_scores_count": len(hole_rows),
        "standings_count": len(standings_rows),
        "brackets_count": len(brackets_data),
        "course": course_info,
        "default_active_league_id": 20261,  # 2026 ECGC Men's Twilight League
    }


def populate_native_gls9_leagues(conn: sqlite3.Connection) -> None:
    """Create and populate native GLS9 tables (<lid>Teams, <lid>Players, <lid>Schedule, etc.)

    for all 18 season-divisions so standard GLS9 engine functions work natively.
    """
    for year, slug, lid, title, day, holes, weeks in SEASON_DIVISIONS:
        # 1. Upsert into Leagues
        conn.execute('DELETE FROM "Leagues" WHERE "LeagueID"=?', (lid,))
        conn.execute(
            """
            INSERT INTO "Leagues" (
                "LeagueID", "LeagueName", "CourseID", "LeaguePres", "LeagueSec", "LeagueVP", "LeagueTreas",
                "LeagueNickname", "LeagueHoles", "NumManTeams", "LeagueDay", "NumPlayers", "ExtraPlayers",
                "SplitSeason", "WeeksPlayed", "DataEntry", "LeagueScoring", "LeagueType", "LeagueFormat",
                "MatchSetup", "TrackPutts", "TrackFairways", "TrackGreens", "SpecificTeeTimes", "Divisions",
                "Div1", "Div2", "Div3", "Div4", "FirstTeeTime", "MinsBetweenGroups", "RoundsUsed",
                "AdjustScores", "PercentHandicap", "MaximumHandicap", "HandicapFormula", "PastScores",
                "PastWks", "PastRnds", "NumCount", "OfLastNum", "SubPercent", "SubUsed", "SubMoney",
                "RegMatches", "PositionRnds", "NoCountRnds", "NoGolfWks"
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lid,
                title,
                ECGC_COURSE_ID,
                None,
                None,
                None,
                None,
                f"ECGC-{year}-{'M' if slug == 'mens' else 'W'}",
                holes,
                2,
                day,
                32,
                1,
                1,
                weeks,
                1,
                2,  # Team match play
                1,
                1,
                0,
                0,
                0,
                0,
                1,
                1,
                "Championship",
                "NA",
                "NA",
                "NA",
                "06:00 PM",
                10,
                2,
                1,
                100,
                54,
                1,
                1,
                0,
                0,
                0,
                0,
                100,
                2,
                0,
                16,
                None,
                None,
                None,
            ),
        )

        # 2. Upsert into LeagueRules
        if table_exists(conn, "LeagueRules"):
            conn.execute('DELETE FROM "LeagueRules" WHERE "LeagueID"=?', (lid,))
            conn.execute(
                """
                INSERT INTO "LeagueRules" (
                    "LeagueID", "IndPtsNet", "IndPtsAct", "IndPtsNetNine", "IndPtsActNine", "IndPtsHolesNine",
                    "IndActHolesNine", "IndPtsNetMatch", "IndPtsActMatch", "IndPtsHolesMatch", "IndActHolesMatch",
                    "TeamPtsNet", "TeamPtsAct", "TeamPtsNetNine", "TeamPtsActNine", "TeamBBPtsNet", "TeamBBPtsAct",
                    "TeamBBNetNine", "TeamBBActNine", "TeamPtsHolesNine", "TeamActHolesNine", "TeamPtsNetMatch",
                    "TeamPtsActMatch", "TeamBBNetMatch", "TeamBBActMatch", "TeamPtsHolesMatch", "TeamActHolesMatch",
                    "IndStableNetNine", "IndStableNetMatch", "IndStableActNine", "IndStableActMatch", "FutureUse1",
                    "FutureUse2", "IndPtsNetField", "IndNetFieldDiff", "TeamPtsNetField", "TeamNetFieldDiff",
                    "IndPtsActField", "IndActFieldDiff", "TeamPtsActField", "TeamActFieldDiff", "4FitPlayerPts",
                    "4FitTeamPts", "PlayerForfeit", "PlayerPenalty", "TeamForfeit", "PresentTeamPts",
                    "PresentPlayerPts", "TeamPenalty", "AbsentTeamPts", "AbsentPlayerPts", "UseIndPts",
                    "IndSubPts", "TeamSubPts", "IndUDPts", "TeamUDPts"
                ) VALUES (?, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 0, 0, NULL, NULL, NULL, NULL, NULL, NULL, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 5, 3, 9, 6, 5, 0, 0, 1, 1, 0, 0, 0)
                """,
                (lid,),
            )

        # 3. Create per-league tables
        t_tbl = f"{lid}Teams"
        p_tbl = f"{lid}Players"
        s_tbl = f"{lid}Schedule"
        pr_tbl = f"{lid}PlayerResults"
        tr_tbl = f"{lid}TeamResults"
        ms_tbl = f"{lid}MatchSetup"
        tt_tbl = f"{lid}TeeTimes"
        subs_tbl = f"{lid}Subs"
        subres_tbl = f"{lid}SubResults"
        fees_tbl = f"{lid}LeagueFees"
        past_tbl = f"{lid}PastScores"
        adj_tbl = f"{lid}AdjScores"
        act_tbl = f"{lid}ActScores"
        hcp_tbl = f"{lid}Handicaps"
        aop_tbl = f"{lid}AdjOverPar"
        sn_tbl = f"{lid}SchedNine"
        prz_tbl = f"{lid}PlayerPrizes"

        conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS "{t_tbl}" (
                "TeamID" INTEGER PRIMARY KEY,
                "TeamName" TEXT NOT NULL,
                "TeamSponsor" TEXT,
                "PlayerA" INTEGER,
                "PlayerB" INTEGER,
                "PlayerC" INTEGER,
                "PlayerD" INTEGER,
                "Handicap" REAL,
                "Division" INTEGER DEFAULT 1,
                "1stHalfPts" REAL DEFAULT 0,
                "2ndHalfPts" REAL DEFAULT 0,
                "FinalPts" REAL DEFAULT 0,
                "Points" REAL DEFAULT 0,
                "PrevPts" REAL DEFAULT 0,
                "Money" REAL DEFAULT 0,
                "InMoney" INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS "{p_tbl}" (
                "PlayerID" INTEGER PRIMARY KEY,
                "TeamID" INTEGER DEFAULT 1,
                "PlayerFirst" TEXT NOT NULL,
                "PlayerLast" TEXT NOT NULL,
                "Street" TEXT,
                "City" TEXT,
                "State" TEXT,
                "Zip" TEXT,
                "HomePhone" TEXT,
                "WorkPhone" TEXT,
                "FaxPhone" TEXT,
                "EMail" TEXT,
                "Handicap" REAL DEFAULT 0,
                "Division" INTEGER DEFAULT 1,
                "1stHalfPts" REAL DEFAULT 0,
                "2ndHalfPts" REAL DEFAULT 0,
                "FinalPts" REAL DEFAULT 0,
                "Points" REAL DEFAULT 0,
                "PrevPts" REAL DEFAULT 0,
                "Money" REAL DEFAULT 0,
                "InMoney" INTEGER DEFAULT 1,
                "YearEndMoney" REAL,
                "YearEndAward" TEXT,
                "Remarks" TEXT
            );

            CREATE TABLE IF NOT EXISTS "{s_tbl}" (
                "WeekNum" INTEGER PRIMARY KEY,
                "Date" TEXT,
                "DateType" INTEGER DEFAULT 1,
                "CourseID" INTEGER DEFAULT 5,
                "SchedUsed" INTEGER DEFAULT -1,
                "Half" INTEGER DEFAULT 1,
                "Weather" TEXT,
                "Match1Team1" INTEGER, "Match1Team2" INTEGER,
                "Match2Team1" INTEGER, "Match2Team2" INTEGER,
                "Match3Team1" INTEGER, "Match3Team2" INTEGER,
                "Match4Team1" INTEGER, "Match4Team2" INTEGER,
                "Match5Team1" INTEGER, "Match5Team2" INTEGER,
                "Match6Team1" INTEGER, "Match6Team2" INTEGER,
                "Match7Team1" INTEGER, "Match7Team2" INTEGER,
                "Match8Team1" INTEGER, "Match8Team2" INTEGER,
                "Match9Team1" INTEGER, "Match9Team2" INTEGER,
                "Match10Team1" INTEGER, "Match10Team2" INTEGER,
                "Match11Team1" INTEGER, "Match11Team2" INTEGER
            );

            CREATE TABLE IF NOT EXISTS "{pr_tbl}" (
                "WeekNum" INTEGER NOT NULL,
                "PlayerID" INTEGER NOT NULL,
                "1" INTEGER, "2" INTEGER, "3" INTEGER, "4" INTEGER, "5" INTEGER,
                "6" INTEGER, "7" INTEGER, "8" INTEGER, "9" INTEGER, "10" INTEGER,
                "11" INTEGER, "12" INTEGER, "13" INTEGER, "14" INTEGER, "15" INTEGER,
                "16" INTEGER, "17" INTEGER, "18" INTEGER,
                "FrontNine" INTEGER, "BackNine" INTEGER,
                "OpponentID" INTEGER, "IndividualPts" REAL DEFAULT 0, "FieldPts" REAL DEFAULT 0,
                "NumPutts" INTEGER, "GreensInRegulation" INTEGER, "NumFairwaysHit" INTEGER,
                "Sub" INTEGER DEFAULT 0, "Forfeit" INTEGER DEFAULT 0,
                "Skins" INTEGER DEFAULT 0, "SkinsNet" INTEGER DEFAULT 0,
                "LowAct" INTEGER DEFAULT 0, "LowNet" INTEGER DEFAULT 0,
                "TeamSkins" INTEGER DEFAULT 0, "TeamSkinsNet" INTEGER DEFAULT 0,
                "LowTeamAct" INTEGER DEFAULT 0, "LowTeamNet" INTEGER DEFAULT 0,
                "BestballAct" INTEGER DEFAULT 0, "BestballNet" INTEGER DEFAULT 0,
                "SubPts" REAL DEFAULT 0, "OtherMoney" REAL DEFAULT 0, "UserDefinedPts" REAL DEFAULT 0,
                PRIMARY KEY ("WeekNum", "PlayerID")
            );

            CREATE TABLE IF NOT EXISTS "{tr_tbl}" (
                "WeekNum" INTEGER NOT NULL,
                "TeamID" INTEGER NOT NULL,
                "TeamPts" REAL DEFAULT 0,
                "MatchPts" REAL DEFAULT 0,
                "FieldPts" REAL DEFAULT 0,
                "TeamActual" INTEGER DEFAULT 0,
                "TeamNet" INTEGER DEFAULT 0,
                "SubPts" REAL DEFAULT 0,
                "UserDefinedPts" REAL DEFAULT 0,
                PRIMARY KEY ("WeekNum", "TeamID")
            );

            CREATE TABLE IF NOT EXISTS "{ms_tbl}" (
                "ID" INTEGER PRIMARY KEY AUTOINCREMENT,
                "MatchNum" INTEGER NOT NULL,
                "Team1" INTEGER,
                "Team2" INTEGER
            );

            CREATE TABLE IF NOT EXISTS "{tt_tbl}" (
                "MatchNum" INTEGER PRIMARY KEY,
                "TeeTime" TEXT
            );

            CREATE TABLE IF NOT EXISTS "{subs_tbl}" (
                "SubID" INTEGER PRIMARY KEY,
                "SubFirst" TEXT, "SubLast" TEXT, "Handicap" REAL, "Points" REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS "{subres_tbl}" (
                "WeekNum" INTEGER, "SubID" INTEGER, "PlayerID" INTEGER, "TeamID" INTEGER,
                PRIMARY KEY ("WeekNum", "SubID")
            );

            CREATE TABLE IF NOT EXISTS "{fees_tbl}" (
                "FeeID" INTEGER PRIMARY KEY, "FeeName" TEXT, "FeeAmount" REAL
            );

            CREATE TABLE IF NOT EXISTS "{past_tbl}" (
                "PlayerID" INTEGER PRIMARY KEY, "Scores" TEXT
            );

            CREATE TABLE IF NOT EXISTS "{adj_tbl}" (
                "WeekNum" INTEGER, "PlayerID" INTEGER, "Score" INTEGER,
                PRIMARY KEY ("WeekNum", "PlayerID")
            );

            CREATE TABLE IF NOT EXISTS "{act_tbl}" (
                "WeekNum" INTEGER, "PlayerID" INTEGER, "Score" INTEGER,
                PRIMARY KEY ("WeekNum", "PlayerID")
            );

            CREATE TABLE IF NOT EXISTS "{hcp_tbl}" (
                "WeekNum" INTEGER, "PlayerID" INTEGER, "Hcp" REAL,
                PRIMARY KEY ("WeekNum", "PlayerID")
            );

            CREATE TABLE IF NOT EXISTS "{aop_tbl}" (
                "WeekNum" INTEGER, "PlayerID" INTEGER, "Score" INTEGER,
                PRIMARY KEY ("WeekNum", "PlayerID")
            );

            CREATE TABLE IF NOT EXISTS "{sn_tbl}" (
                "WeekNum" INTEGER PRIMARY KEY, "NinePlayed" TEXT DEFAULT 'front'
            );

            CREATE TABLE IF NOT EXISTS "{prz_tbl}" (
                "PrizeID" INTEGER PRIMARY KEY AUTOINCREMENT, "WeekNum" INTEGER, "PlayerID" INTEGER, "Amount" REAL, "Reason" TEXT
            );
        """)

        # Clear existing data for this league
        conn.execute(f'DELETE FROM "{t_tbl}"')
        conn.execute(f'DELETE FROM "{p_tbl}"')
        conn.execute(f'DELETE FROM "{s_tbl}"')
        conn.execute(f'DELETE FROM "{pr_tbl}"')
        conn.execute(f'DELETE FROM "{tr_tbl}"')
        conn.execute(f'DELETE FROM "{ms_tbl}"')
        conn.execute(f'DELETE FROM "{tt_tbl}"')

        # 4. Populate Teams from ecgc_teams & ecgc_standings
        t_rows = conn.execute(
            "SELECT * FROM ecgc_teams WHERE season_year=? AND league_slug=? ORDER BY team_number ASC",
            (year, slug),
        ).fetchall()
        for tr in t_rows:
            tid = tr[3] or tr[0]  # team_number or id
            tname = tr[4]

            # Find standings points
            fin_pts = 0.0
            h1_pts = 0.0
            h2_pts = 0.0
            st_fin = conn.execute(
                "SELECT points FROM ecgc_standings WHERE season_year=? AND league_slug=? AND team_id=? AND split_name='final'",
                (year, slug, tr[0]),
            ).fetchone()
            if st_fin:
                fin_pts = float(st_fin[0] or 0)
            st_h1 = conn.execute(
                "SELECT points FROM ecgc_standings WHERE season_year=? AND league_slug=? AND team_id=? AND split_name='first'",
                (year, slug, tr[0]),
            ).fetchone()
            if st_h1:
                h1_pts = float(st_h1[0] or 0)
            st_h2 = conn.execute(
                "SELECT points FROM ecgc_standings WHERE season_year=? AND league_slug=? AND team_id=? AND split_name='second'",
                (year, slug, tr[0]),
            ).fetchone()
            if st_h2:
                h2_pts = float(st_h2[0] or 0)

            # Find 2 team players
            m_players = conn.execute(
                "SELECT player_id FROM ecgc_team_members WHERE team_id=? ORDER BY id ASC LIMIT 2",
                (tr[0],),
            ).fetchall()
            p1 = m_players[0][0] if len(m_players) > 0 else None
            p2 = m_players[1][0] if len(m_players) > 1 else None

            conn.execute(
                f"""
                INSERT INTO "{t_tbl}" (
                    "TeamID", "TeamName", "PlayerA", "PlayerB", "Division",
                    "1stHalfPts", "2ndHalfPts", "FinalPts", "Points", "PrevPts"
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (tid, tname, p1, p2, h1_pts, h2_pts, fin_pts, fin_pts, fin_pts),
            )

        # 5. Populate Players from ecgc_players & ecgc_rounds
        season_players = conn.execute(
            """
            SELECT DISTINCT p.id, p.display_name, p.first_name, p.last_name
            FROM ecgc_players p
            JOIN ecgc_rounds r ON r.player_id = p.id
            WHERE r.season_year=? AND r.league_slug=?
            """,
            (year, slug),
        ).fetchall()

        for pr in season_players:
            pid = pr[0]
            pfirst = pr[2] or (pr[1].split()[0] if pr[1] else "Golfer")
            plast = pr[3] or (
                " ".join(pr[1].split()[1:]) if pr[1] and len(pr[1].split()) > 1 else ""
            )

            # Get latest handicap and team
            last_round = conn.execute(
                """
                SELECT team_id, handicap, points_adjustment
                FROM ecgc_rounds
                WHERE player_id=? AND season_year=? AND league_slug=?
                ORDER BY event_id DESC LIMIT 1
                """,
                (pid, year, slug),
            ).fetchone()

            # Find canonical team_number for team_id
            assigned_team = 1
            hcp = 0.0
            if last_round:
                orig_tid = last_round[0]
                t_row = conn.execute(
                    "SELECT team_number FROM ecgc_teams WHERE id=?", (orig_tid,)
                ).fetchone()
                if t_row and t_row[0]:
                    assigned_team = t_row[0]
                hcp = float(last_round[1] or 0)

            # Calculate total PT points for player
            total_pts = conn.execute(
                """
                SELECT SUM(points_adjustment)
                FROM ecgc_rounds
                WHERE player_id=? AND season_year=? AND league_slug=?
                """,
                (pid, year, slug),
            ).fetchone()[0] or 0.0

            conn.execute(
                f"""
                INSERT INTO "{p_tbl}" (
                    "PlayerID", "TeamID", "PlayerFirst", "PlayerLast", "Handicap",
                    "Division", "Points", "PrevPts"
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (pid, assigned_team, pfirst, plast, hcp, float(total_pts), float(total_pts)),
            )

        # 6. Populate Schedule from ecgc_events & ecgc_matches
        ev_rows = conn.execute(
            "SELECT * FROM ecgc_events WHERE season_year=? AND league_slug=? ORDER BY week_number ASC",
            (year, slug),
        ).fetchall()

        for ev in ev_rows:
            ev_id = ev[0]
            wk = ev[4]  # week_number
            dt = ev[7] or f"{year}-05-01"
            half = 1 if wk <= 8 else 2

            # Find matches for this event
            m_list = conn.execute(
                "SELECT team_a_id, team_b_id FROM ecgc_matches WHERE event_id=? ORDER BY match_number ASC",
                (ev_id,),
            ).fetchall()

            # Map up to 11 matches to team numbers
            match_cols: list[int | None] = []
            for m_item in m_list:
                ta = conn.execute(
                    "SELECT team_number FROM ecgc_teams WHERE id=?", (m_item[0],)
                ).fetchone()
                tb = conn.execute(
                    "SELECT team_number FROM ecgc_teams WHERE id=?", (m_item[1],)
                ).fetchone()
                match_cols.append(ta[0] if ta and ta[0] else m_item[0])
                match_cols.append(tb[0] if tb and tb[0] else m_item[1])

            # Pad to 22 slots (11 matches * 2 teams)
            while len(match_cols) < 22:
                match_cols.append(None)

            placeholders = ", ".join(["?"] * 26)
            conn.execute(
                f"""
                INSERT INTO "{s_tbl}" (
                    "WeekNum", "Date", "CourseID", "Half",
                    "Match1Team1", "Match1Team2", "Match2Team1", "Match2Team2",
                    "Match3Team1", "Match3Team2", "Match4Team1", "Match4Team2",
                    "Match5Team1", "Match5Team2", "Match6Team1", "Match6Team2",
                    "Match7Team1", "Match7Team2", "Match8Team1", "Match8Team2",
                    "Match9Team1", "Match9Team2", "Match10Team1", "Match10Team2",
                    "Match11Team1", "Match11Team2"
                ) VALUES ({placeholders})
                """,
                [wk, dt, 5, half] + match_cols[:22],
            )

        # 7. Populate PlayerResults & Hole Scores from ecgc_rounds & ecgc_hole_scores
        r_rows = conn.execute(
            """
            SELECT r.id, e.week_number, r.player_id, r.gross_total, r.points_adjustment, r.team_id
            FROM ecgc_rounds r
            JOIN ecgc_events e ON e.id = r.event_id
            WHERE r.season_year=? AND r.league_slug=?
            """,
            (year, slug),
        ).fetchall()

        for rnd in r_rows:
            rnd_id = rnd[0]
            wk_num = rnd[1]
            p_id = rnd[2]
            gross = rnd[3]
            pt_adj = float(rnd[4] or 0)

            # Get 9 hole scores
            holes = conn.execute(
                "SELECT hole_number, gross_score FROM ecgc_hole_scores WHERE round_id=? ORDER BY hole_number ASC",
                (rnd_id,),
            ).fetchall()
            hole_dict = {h[0]: h[1] for h in holes}

            conn.execute(
                f"""
                INSERT OR REPLACE INTO "{pr_tbl}" (
                    "WeekNum", "PlayerID", "1", "2", "3", "4", "5", "6", "7", "8", "9",
                    "FrontNine", "IndividualPts"
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    wk_num,
                    p_id,
                    hole_dict.get(1),
                    hole_dict.get(2),
                    hole_dict.get(3),
                    hole_dict.get(4),
                    hole_dict.get(5),
                    hole_dict.get(6),
                    hole_dict.get(7),
                    hole_dict.get(8),
                    hole_dict.get(9),
                    gross,
                    pt_adj,
                ),
            )

        # 8. Populate TeamResults from ecgc_matches
        match_results = conn.execute(
            """
            SELECT e.week_number, m.team_a_id, m.team_a_points, m.team_b_id, m.team_b_points
            FROM ecgc_matches m
            JOIN ecgc_events e ON e.id = m.event_id
            WHERE m.season_year=? AND m.league_slug=?
            """,
            (year, slug),
        ).fetchall()

        for mr in match_results:
            wk = mr[0]
            ta_orig = mr[1]
            ta_pts = float(mr[2] or 0)
            tb_orig = mr[3]
            tb_pts = float(mr[4] or 0)

            ta_num_row = conn.execute(
                "SELECT team_number FROM ecgc_teams WHERE id=?", (ta_orig,)
            ).fetchone()
            tb_num_row = conn.execute(
                "SELECT team_number FROM ecgc_teams WHERE id=?", (tb_orig,)
            ).fetchone()

            ta_num = ta_num_row[0] if ta_num_row and ta_num_row[0] else ta_orig
            tb_num = tb_num_row[0] if tb_num_row and tb_num_row[0] else tb_orig

            if ta_num:
                conn.execute(
                    f'INSERT OR REPLACE INTO "{tr_tbl}" ("WeekNum", "TeamID", "TeamPts", "MatchPts") VALUES (?, ?, ?, ?)',
                    (wk, ta_num, ta_pts, ta_pts),
                )
            if tb_num:
                conn.execute(
                    f'INSERT OR REPLACE INTO "{tr_tbl}" ("WeekNum", "TeamID", "TeamPts", "MatchPts") VALUES (?, ?, ?, ?)',
                    (wk, tb_num, tb_pts, tb_pts),
                )

        # 9. Populate TeeTimes
        for m_num in range(1, 12):
            hr = 6 + (m_num - 1) * 10 // 60
            mn = ((m_num - 1) * 10) % 60
            tt_str = f"{hr:02d}:{mn:02d} PM"
            conn.execute(
                f'INSERT INTO "{tt_tbl}" ("MatchNum", "TeeTime") VALUES (?, ?)',
                (m_num, tt_str),
            )
            conn.execute(
                f'INSERT INTO "{ms_tbl}" ("MatchNum", "Team1", "Team2") VALUES (?, ?, ?)',
                (m_num, m_num * 2 - 1, m_num * 2),
            )
            conn.execute(
                f'INSERT OR IGNORE INTO "{sn_tbl}" ("WeekNum", "NinePlayed") VALUES (?, ?)',
                (m_num, "front"),
            )
