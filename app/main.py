"""Golf League Secretary (GLS9) Clean-Room Modern Web Studio (:8104).
Reconstructed from /workspace/knowledge-base/gls9-golfsoft-bundle/dossier.md."""
from __future__ import annotations

import math
import os
import re
import sqlite3
import subprocess
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Path as PathParam, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import golf_engine, mdb_migrator

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "gls9.db"
DEFAULT_MDB = Path("/tmp/GLS9/Database/Gls90db.mdb")
DEFAULT_SCHEDULES = Path("/tmp/GLS9/Schedules")


MAX_MDB_UPLOAD_BYTES = int(os.environ.get("GLS9_MAX_MDB_BYTES", str(64 * 1024 * 1024)))
# Jet 3/4 (.mdb) and ACE (.accdb) files carry this signature at byte offset 4.
_MDB_MAGICS = (b"Standard Jet DB", b"Standard ACE DB")
_EMAIL_RE = re.compile(r"^[^@\s<>\"']{1,64}@[A-Za-z0-9.-]{1,252}\.[A-Za-z]{2,63}$")
_PHONE_RE = re.compile(r"^[0-9+()\-. xX#]{0,32}$")

LeagueId = Annotated[int, PathParam(ge=1, le=99999, description="League ID")]
WeekNum = Annotated[int, PathParam(ge=1, le=golf_engine.MAX_SCHEDULE_WEEKS, description="Week number (1-52)")]


def _clean_text(value: str, *, field: str, max_len: int, required: bool) -> str:
    """Normalise free text: NFC, strip, reject control characters and over-long values.

    HTML metacharacters are *not* stripped (names like O'Brien or "Smith & Sons" are
    legitimate); the SPA escapes every value on output instead."""
    v = unicodedata.normalize("NFC", value or "").strip()
    if any(unicodedata.category(ch).startswith("C") for ch in v):
        raise ValueError(f"{field} must not contain control characters")
    if required and not v:
        raise ValueError(f"{field} is required")
    if len(v) > max_len:
        raise ValueError(f"{field} must be at most {max_len} characters")
    return v


def _finite(v: float, field: str) -> float:
    if not math.isfinite(v):
        raise ValueError(f"{field} must be a finite number")
    return v


class ScoreSaveReq(BaseModel):
    model_config = ConfigDict(extra="ignore")

    PlayerID: int = Field(ge=1, le=10_000_000)
    holes: list[Annotated[int, Field(ge=0, le=golf_engine.MAX_HOLE_SCORE)]] = Field(max_length=18)
    NumPutts: int = Field(default=0, ge=0, le=100)
    GreensInRegulation: int = Field(default=0, ge=0, le=18)
    NumFairwaysHit: int = Field(default=0, ge=0, le=18)
    IndividualPts: float = Field(default=0.0, ge=-1000, le=1000)

    @field_validator("IndividualPts")
    @classmethod
    def _pts_finite(cls, v: float) -> float:
        return _finite(v, "IndividualPts")


class PlayerUpsertReq(BaseModel):
    model_config = ConfigDict(extra="ignore")

    PlayerID: int | None = Field(default=None, ge=1, le=10_000_000)
    TeamID: int = Field(default=1, ge=1, le=999)
    PlayerFirst: str
    PlayerLast: str
    Handicap: float = Field(default=0.0, ge=-10, le=54)
    Division: str | float | None = None
    Points: float = Field(default=0.0, ge=-100_000, le=100_000)
    Money: float = Field(default=0.0, ge=-1_000_000, le=1_000_000)
    EMail: str = ""
    HomePhone: str = ""

    @field_validator("PlayerFirst", "PlayerLast")
    @classmethod
    def _names(cls, v: str, info) -> str:
        return _clean_text(v, field=info.field_name, max_len=40, required=True)

    @field_validator("Handicap", "Points", "Money")
    @classmethod
    def _nums_finite(cls, v: float, info) -> float:
        return _finite(v, info.field_name)

    @field_validator("EMail")
    @classmethod
    def _email(cls, v: str) -> str:
        v = _clean_text(v, field="EMail", max_len=254, required=False)
        if v and not _EMAIL_RE.match(v):
            raise ValueError("EMail is not a valid email address")
        return v

    @field_validator("HomePhone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = _clean_text(v, field="HomePhone", max_len=32, required=False)
        if not _PHONE_RE.match(v):
            raise ValueError("HomePhone may only contain digits, spaces and + ( ) - . x #")
        return v


class ScheduleGenReq(BaseModel):
    model_config = ConfigDict(extra="ignore")

    weeks: int = Field(default=16, ge=1, le=golf_engine.MAX_SCHEDULE_WEEKS)
    start_date: date = date(2026, 5, 5)


_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


def create_app(db_path: Path | None = None, mdb_seed: Path | None = None, schedules_dir: Path | None = None) -> FastAPI:
    db_file = db_path or Path(os.environ.get("GLS9_DB_PATH", str(DEFAULT_DB)))
    mdb_file = mdb_seed or Path(os.environ.get("GLS9_MDB_PATH", str(DEFAULT_MDB)))
    sched_dir = schedules_dir or Path(os.environ.get("GLS9_SCHEDULES_DIR", str(DEFAULT_SCHEDULES)))

    if not db_file.exists() and mdb_file.exists():
        mdb_migrator.migrate_mdb_to_sqlite(mdb_file, db_file, sched_dir)

    app = FastAPI(title="Golf League Secretary — Modern Web Edition (GLS9 Clean-Room)", version="2.0.0")
    app.state.db_file = db_file

    @contextmanager
    def get_conn():
        """Per-request connection: commit on success, roll back on error, ALWAYS close.

        (``with sqlite3.connect(...) as conn`` only manages the transaction - it never
        closes the connection, which leaked one file handle per request.)"""
        conn = sqlite3.connect(str(app.state.db_file), timeout=10)
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def require_league(conn: sqlite3.Connection, lid: int) -> None:
        if not golf_engine.table_exists(conn, "Leagues") or conn.execute(
            'SELECT 1 FROM "Leagues" WHERE "LeagueID"=?', (lid,)
        ).fetchone() is None:
            raise HTTPException(status_code=404, detail=f"League {lid} not found")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        path = request.url.path
        # Swagger UI (/docs) loads its own CDN assets, so the strict CSP applies to the SPA + API only.
        if not (path.startswith("/docs") or path.startswith("/redoc") or path == "/openapi.json"):
            response.headers.setdefault("Content-Security-Policy", _CSP)
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError):
        # FastAPI's default handler echoes the offending input back; a JSON NaN/Infinity
        # input then crashes the error serialiser (500). Return only loc/msg/type.
        errors = [
            {"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(golf_engine.NotFoundError)
    async def _not_found(_: Request, exc: golf_engine.NotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(golf_engine.InvalidInputError)
    async def _invalid_input(_: Request, exc: golf_engine.InvalidInputError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(sqlite3.Error)
    async def _db_error(_: Request, exc: sqlite3.Error):
        # Never leak SQL / schema details to the client.
        return JSONResponse(status_code=500, content={"detail": "Database error"})

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
            out_leagues = []
            for lg in leagues:
                lid = golf_engine.safe_int(lg.get("LeagueID"), -1)
                if lid < 1 or str(lg.get("LeagueID")).strip() not in (str(lid), f"{lid}.0"):
                    continue  # skip corrupt rows; LeagueID is interpolated into table names
                out_leagues.append(lg)
                lg["CourseName"] = courses.get(lg.get("CourseID"), "Unknown Course")
                p_tbl = f"{lid}Players"
                t_tbl = f"{lid}Teams"
                s_tbl = f"{lid}Schedule"
                lg["player_count"] = conn.execute(f'SELECT COUNT(*) FROM "{p_tbl}"').fetchone()[0] if golf_engine.table_exists(conn, p_tbl) else 0
                lg["team_count"] = conn.execute(f'SELECT COUNT(*) FROM "{t_tbl}"').fetchone()[0] if golf_engine.table_exists(conn, t_tbl) else 0
                lg["week_count"] = conn.execute(f'SELECT COUNT(*) FROM "{s_tbl}"').fetchone()[0] if golf_engine.table_exists(conn, s_tbl) else 0
        return {"leagues": out_leagues}

    @app.get("/api/leagues/{lid}/standings")
    def league_standings(lid: LeagueId):
        with get_conn() as conn:
            require_league(conn, lid)
            return golf_engine.get_league_standings(conn, lid)

    @app.get("/api/leagues/{lid}/week/{week_num}")
    def week_scorecard(lid: LeagueId, week_num: WeekNum):
        with get_conn() as conn:
            require_league(conn, lid)
            return golf_engine.get_week_scorecard(conn, lid, week_num)

    @app.post("/api/leagues/{lid}/week/{week_num}/scores")
    def save_week_score(lid: LeagueId, week_num: WeekNum, req: ScoreSaveReq):
        with get_conn() as conn:
            require_league(conn, lid)
            if not golf_engine.table_exists(conn, f"{lid}PlayerResults"):
                raise HTTPException(status_code=404, detail=f"League {lid} has no results table")
            return golf_engine.save_player_week_score(conn, lid, week_num, req.model_dump())

    @app.post("/api/leagues/{lid}/week/{week_num}/auto-score-matches")
    def auto_score_week(lid: LeagueId, week_num: WeekNum):
        with get_conn() as conn:
            require_league(conn, lid)
            if not golf_engine.table_exists(conn, f"{lid}PlayerResults") or not golf_engine.table_exists(conn, f"{lid}Players"):
                raise HTTPException(status_code=404, detail=f"League {lid} has no results table")
            return golf_engine.auto_score_week_matches(conn, lid, week_num)

    @app.get("/api/leagues/{lid}/week/{week_num}/report")
    def week_clubhouse_report(lid: LeagueId, week_num: WeekNum):
        with get_conn() as conn:
            require_league(conn, lid)
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
    def recalc_hcps(lid: LeagueId):
        with get_conn() as conn:
            require_league(conn, lid)
            if not golf_engine.table_exists(conn, f"{lid}Players"):
                raise HTTPException(status_code=404, detail=f"League {lid} has no players table")
            return golf_engine.recalculate_handicaps(conn, lid)

    @app.get("/api/leagues/{lid}/schedule")
    def get_schedule(lid: LeagueId):
        with get_conn() as conn:
            require_league(conn, lid)
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
    def gen_schedule(lid: LeagueId, req: ScheduleGenReq):
        with get_conn() as conn:
            require_league(conn, lid)
            sched = golf_engine.generate_schedule(conn, lid, req.weeks, req.start_date)
            return {"league_id": lid, "generated_weeks": len(sched), "schedule": sched}

    @app.post("/api/leagues/{lid}/players")
    def upsert_player(lid: LeagueId, req: PlayerUpsertReq):
        with get_conn() as conn:
            require_league(conn, lid)
            p_tbl = f"{lid}Players"
            t_tbl = f"{lid}Teams"
            if not golf_engine.table_exists(conn, p_tbl):
                raise HTTPException(status_code=404, detail=f"League {lid} has no players table")
            # Team leagues must reference an existing team; individual leagues (no *Teams rows)
            # use TeamID as a free grouping number.
            if golf_engine.table_exists(conn, t_tbl) and conn.execute(f'SELECT COUNT(*) FROM "{t_tbl}"').fetchone()[0] > 0:
                if conn.execute(f'SELECT 1 FROM "{t_tbl}" WHERE "TeamID"=?', (req.TeamID,)).fetchone() is None:
                    raise HTTPException(status_code=422, detail=f"Team {req.TeamID} does not exist in league {lid}")
            with conn:
                if req.PlayerID:
                    if conn.execute(f'SELECT 1 FROM "{p_tbl}" WHERE "PlayerID"=?', (req.PlayerID,)).fetchone() is None:
                        raise HTTPException(status_code=404, detail=f"Player {req.PlayerID} not found in league {lid}")
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
        if not re.fullmatch(r"[A-Za-z0-9_]{1,128}", table_name or ""):
            raise HTTPException(status_code=404, detail="Table not found")
        clean = table_name
        with get_conn() as conn:
            if not golf_engine.table_exists(conn, clean):
                raise HTTPException(status_code=404, detail="Table not found")
            rows = golf_engine.rows_as_dicts(conn.execute(f'SELECT * FROM "{clean}" LIMIT 200'))
            return {"table": clean, "row_count": len(rows), "rows": rows}

    @app.post("/api/import/mdb")
    def import_mdb(file: UploadFile = File(...)):
        fd, tmp = tempfile.mkstemp(suffix=".mdb")
        try:
            size = 0
            head = b""
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = file.file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_MDB_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_MDB_UPLOAD_BYTES // (1024 * 1024)} MB limit")
                    if len(head) < 32:
                        head += chunk[: 32 - len(head)]
                    out.write(chunk)
            if size == 0:
                raise HTTPException(status_code=400, detail="Uploaded file is empty")
            if not any(head[4:4 + len(m)] == m for m in _MDB_MAGICS):
                raise HTTPException(status_code=400, detail="Uploaded file is not a Microsoft Access (.mdb/.accdb) database")
            try:
                res = mdb_migrator.migrate_mdb_to_sqlite(Path(tmp), app.state.db_file, sched_dir)
            except FileNotFoundError:
                raise HTTPException(status_code=503, detail="mdbtools (mdb-tables / mdb-export) is not installed on the server")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, UnicodeDecodeError):
                raise HTTPException(status_code=400, detail="Could not read the uploaded .mdb file")
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
