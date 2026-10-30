"""Golf League Secretary (GLS9) Clean-Room Modern Web Studio (:8104).
Reconstructed from /workspace/knowledge-base/gls9-golfsoft-bundle/dossier.md."""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import golf_engine, mdb_migrator

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "gls9.db"
DEFAULT_MDB = Path("/tmp/GLS9/Database/Gls90db.mdb")
DEFAULT_SCHEDULES = Path("/tmp/GLS9/Schedules")


class ScoreSaveReq(BaseModel):
    PlayerID: int
    holes: list[int]
    NumPutts: int = 0
    GreensInRegulation: int = 0
    NumFairwaysHit: int = 0
    IndividualPts: float = 0.0


class PlayerUpsertReq(BaseModel):
    PlayerID: int | None = None
    TeamID: int = 1
    PlayerFirst: str
    PlayerLast: str
    Handicap: float = 0.0
    Division: str | float | None = None
    Points: float = 0.0
    Money: float = 0.0
    EMail: str = ""
    HomePhone: str = ""


class ScheduleGenReq(BaseModel):
    weeks: int = 16
    start_date: str = "2026-05-05"


def create_app(db_path: Path | None = None, mdb_seed: Path | None = None, schedules_dir: Path | None = None) -> FastAPI:
    db_file = db_path or Path(os.environ.get("GLS9_DB_PATH", str(DEFAULT_DB)))
    mdb_file = mdb_seed or Path(os.environ.get("GLS9_MDB_PATH", str(DEFAULT_MDB)))
    sched_dir = schedules_dir or Path(os.environ.get("GLS9_SCHEDULES_DIR", str(DEFAULT_SCHEDULES)))

    if not db_file.exists() and mdb_file.exists():
        mdb_migrator.migrate_mdb_to_sqlite(mdb_file, db_file, sched_dir)

    app = FastAPI(title="Golf League Secretary — Modern Web Edition (GLS9 Clean-Room)", version="2.0.0")
    app.state.db_file = db_file

    def get_conn() -> sqlite3.Connection:
        conn = sqlite3.connect(str(app.state.db_file))
        return conn

    @app.get("/api/health")
    def health():
        with get_conn() as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
            leagues_cnt = conn.execute('SELECT COUNT(*) FROM "Leagues"').fetchone()[0] if "Leagues" in tables else 0
            courses_cnt = conn.execute('SELECT COUNT(*) FROM "Courses"').fetchone()[0] if "Courses" in tables else 0
            tpl_cnt = conn.execute('SELECT COUNT(*) FROM "round_robin_templates"').fetchone()[0] if "round_robin_templates" in tables else 0
        return {
            "status": "ok",
            "app": "gls9-modern-web",
            "version": app.version,
            "reconstructed_from": "Gls90.exe (VB6/PE32) + Gls90db.mdb (Jet 3.5)",
            "sqlite_tables_count": len(tables),
            "leagues_count": leagues_cnt,
            "courses_count": courses_cnt,
            "round_robin_templates_count": tpl_cnt,
        }

    @app.get("/api/leagues")
    def list_leagues():
        with get_conn() as conn:
            leagues = golf_engine.rows_as_dicts(conn.execute('SELECT * FROM "Leagues" ORDER BY "LeagueID" ASC'))
            courses = {c["CourseID"]: c["CourseName"] for c in golf_engine.rows_as_dicts(conn.execute('SELECT "CourseID","CourseName" FROM "Courses"'))}
            for lg in leagues:
                lid = lg["LeagueID"]
                lg["CourseName"] = courses.get(lg.get("CourseID"), "Unknown Course")
                p_tbl = f"{lid}Players"
                t_tbl = f"{lid}Teams"
                s_tbl = f"{lid}Schedule"
                lg["player_count"] = conn.execute(f'SELECT COUNT(*) FROM "{p_tbl}"').fetchone()[0] if golf_engine.table_exists(conn, p_tbl) else 0
                lg["team_count"] = conn.execute(f'SELECT COUNT(*) FROM "{t_tbl}"').fetchone()[0] if golf_engine.table_exists(conn, t_tbl) else 0
                lg["week_count"] = conn.execute(f'SELECT COUNT(*) FROM "{s_tbl}"').fetchone()[0] if golf_engine.table_exists(conn, s_tbl) else 0
        return {"leagues": leagues}

    @app.get("/api/leagues/{lid}/standings")
    def league_standings(lid: int):
        with get_conn() as conn:
            try:
                return golf_engine.get_league_standings(conn, lid)
            except KeyError as e:
                raise HTTPException(status_code=404, detail=str(e))

    @app.get("/api/leagues/{lid}/week/{week_num}")
    def week_scorecard(lid: int, week_num: int):
        with get_conn() as conn:
            try:
                return golf_engine.get_week_scorecard(conn, lid, week_num)
            except KeyError as e:
                raise HTTPException(status_code=404, detail=str(e))

    @app.post("/api/leagues/{lid}/week/{week_num}/scores")
    def save_week_score(lid: int, week_num: int, req: ScoreSaveReq):
        with get_conn() as conn:
            return golf_engine.save_player_week_score(conn, lid, week_num, req.model_dump())

    @app.post("/api/leagues/{lid}/week/{week_num}/auto-score-matches")
    def auto_score_week(lid: int, week_num: int):
        with get_conn() as conn:
            return golf_engine.auto_score_week_matches(conn, lid, week_num)

    @app.get("/api/leagues/{lid}/week/{week_num}/report")
    def week_clubhouse_report(lid: int, week_num: int):
        with get_conn() as conn:
            st = golf_engine.get_league_standings(conn, lid)
            sc = golf_engine.get_week_scorecard(conn, lid, week_num)
            return {
                "league": st["league"],
                "rules_summary": st["rules_summary"],
                "course": st["course"],
                "week_num": week_num,
                "teams": st["teams"],
                "players": st["players"][:10],
                "matchups": sc["matchups"],
                "team_results": sc["team_results"],
                "gross_skins": sc["gross_skins"],
                "net_skins": sc["net_skins"],
            }

    @app.post("/api/leagues/{lid}/recalculate-handicaps")
    def recalc_hcps(lid: int):
        with get_conn() as conn:
            return golf_engine.recalculate_handicaps(conn, lid)

    @app.get("/api/leagues/{lid}/schedule")
    def get_schedule(lid: int):
        with get_conn() as conn:
            s_tbl = f"{lid}Schedule"
            t_tbl = f"{lid}Teams"
            tt_tbl = f"{lid}TeeTimes"
            teams = {r["TeamID"]: r["TeamName"] for r in golf_engine.rows_as_dicts(conn.execute(f'SELECT "TeamID","TeamName" FROM "{t_tbl}"'))} if golf_engine.table_exists(conn, t_tbl) else {}
            sched = golf_engine.rows_as_dicts(conn.execute(f'SELECT * FROM "{s_tbl}" ORDER BY "WeekNum" ASC')) if golf_engine.table_exists(conn, s_tbl) else []
            tt = golf_engine.rows_as_dicts(conn.execute(f'SELECT * FROM "{tt_tbl}" ORDER BY "MatchNum" ASC')) if golf_engine.table_exists(conn, tt_tbl) else []
            for w in sched:
                w["Match1Label"] = f"Team {w.get('Match1Team1')} ({teams.get(w.get('Match1Team1'), '')}) vs Team {w.get('Match1Team2')} ({teams.get(w.get('Match1Team2'), '')})"
                w["Match2Label"] = f"Team {w.get('Match2Team1')} ({teams.get(w.get('Match2Team1'), '')}) vs Team {w.get('Match2Team2')} ({teams.get(w.get('Match2Team2'), '')})"
            return {"league_id": lid, "schedule": sched, "tee_times": tt, "teams": teams}

    @app.post("/api/leagues/{lid}/schedule/generate")
    def gen_schedule(lid: int, req: ScheduleGenReq):
        with get_conn() as conn:
            sched = golf_engine.generate_schedule(conn, lid, req.weeks, req.start_date)
            return {"league_id": lid, "generated_weeks": len(sched), "schedule": sched}

    @app.post("/api/leagues/{lid}/players")
    def upsert_player(lid: int, req: PlayerUpsertReq):
        with get_conn() as conn:
            p_tbl = f"{lid}Players"
            with conn:
                if req.PlayerID:
                    conn.execute(
                        f'UPDATE "{p_tbl}" SET "TeamID"=?, "PlayerFirst"=?, "PlayerLast"=?, "Handicap"=?, "Points"=?, "Money"=?, "EMail"=?, "HomePhone"=? WHERE "PlayerID"=?',
                        (req.TeamID, req.PlayerFirst, req.PlayerLast, req.Handicap, req.Points, req.Money, req.EMail, req.HomePhone, req.PlayerID),
                    )
                    pid = req.PlayerID
                else:
                    max_id = conn.execute(f'SELECT COALESCE(MAX("PlayerID"), 0) + 1 FROM "{p_tbl}"').fetchone()[0]
                    pid = int(max_id)
                    conn.execute(
                        f'INSERT INTO "{p_tbl}" ("PlayerID","TeamID","PlayerFirst","PlayerLast","Handicap","Points","PrevPts","Money","InMoney","EMail","HomePhone") VALUES (?,?,?,?,?,?,0,?,1,?,?)',
                        (pid, req.TeamID, req.PlayerFirst, req.PlayerLast, req.Handicap, req.Points, req.Money, req.EMail, req.HomePhone),
                    )
            return golf_engine.get_league_standings(conn, lid)

    @app.get("/api/courses")
    def list_courses():
        with get_conn() as conn:
            return {"courses": golf_engine.get_courses(conn)}

    @app.get("/api/tables")
    def list_tables():
        with get_conn() as conn:
            names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
            out = []
            for n in names:
                cnt = conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
                out.append({"name": n, "row_count": cnt})
            return {"table_count": len(out), "tables": out}

    @app.get("/api/tables/{table_name}")
    def inspect_table(table_name: str):
        clean = re.sub(r"[^A-Za-z0-9_]", "", table_name)
        with get_conn() as conn:
            if not golf_engine.table_exists(conn, clean):
                raise HTTPException(status_code=404, detail="Table not found")
            rows = golf_engine.rows_as_dicts(conn.execute(f'SELECT * FROM "{clean}" LIMIT 200'))
            return {"table": clean, "row_count": len(rows), "rows": rows}

    @app.post("/api/import/mdb")
    def import_mdb(file: UploadFile = File(...)):
        fd, tmp = tempfile.mkstemp(suffix=".mdb")
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(file.file.read())
            res = mdb_migrator.migrate_mdb_to_sqlite(Path(tmp), app.state.db_file, sched_dir)
            return {"status": "ok", **res}
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @app.get("/api/export/sqlite")
    def export_sqlite():
        return FileResponse(
            app.state.db_file,
            media_type="application/x-sqlite3",
            filename="gls9_modern.db",
        )

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
