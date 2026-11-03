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
from typing import Annotated, Any, Awaitable, Callable, Generator

from fastapi import FastAPI, File, HTTPException, Path as PathParam, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, ValidationInfo

from . import ecgc_importer, golf_engine, match_engine, mdb_migrator

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
    def _names(cls, v: str, info: ValidationInfo) -> str:
        return _clean_text(v, field=info.field_name or "Unknown", max_len=40, required=True)

    @field_validator("Handicap", "Points", "Money")
    @classmethod
    def _nums_finite(cls, v: float, info: ValidationInfo) -> float:
        return _finite(v, info.field_name or "Unknown")

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


def _validate_ecgc_rules(req: dict[str, Any]) -> None:
    """Validate dynamic rule fields before conversion or SQLite binding."""
    integer_fields = {"holes_count", "net_bonus_enabled", "net_bonus_below_max", "net_even_min", "net_even_max", "net_penalty_above_min", "plus_handicaps_enabled", "unplayed_round_score"}
    float_fields = {"points_per_hole_win", "points_per_hole_tie", "match_hole_points_total", "net_bonus_pts", "net_even_pts", "net_penalty_pts"}
    for key in integer_fields | float_fields:
        if key not in req:
            continue
        value = req[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise HTTPException(422, detail=f"{key} must be a finite number")
        if key in integer_fields and int(value) != value:
            raise HTTPException(422, detail=f"{key} must be an integer")
    for key in ("rule_type", "handicap_progression_mode"):
        if key in req and not isinstance(req[key], str):
            raise HTTPException(422, detail=f"{key} must be text")
    if req.get("holes_count", 9) != 9:
        raise HTTPException(422, detail="ECGC matches require nine holes")


_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


def create_app(db_path: Path | None = None, mdb_seed: Path | None = None, schedules_dir: Path | None = None) -> FastAPI:
    db_file = db_path or Path(os.environ.get("GLS9_DB_PATH", str(DEFAULT_DB)))
    mdb_file = mdb_seed or Path(os.environ.get("GLS9_MDB_PATH", str(DEFAULT_MDB)))
    sched_dir = schedules_dir or Path(os.environ.get("GLS9_SCHEDULES_DIR", str(DEFAULT_SCHEDULES)))

    if not db_file.exists() and mdb_file.exists():
        mdb_migrator.migrate_mdb_to_sqlite(mdb_file, db_file, sched_dir)

    # Auto-seed ECGC data if db_file exists and ECGC tables/seasons not yet populated
    if db_file.exists():
        try:
            with sqlite3.connect(str(db_file), timeout=10) as _c_init:
                has_ecgc = golf_engine.table_exists(_c_init, "ecgc_seasons") and \
                    _c_init.execute('SELECT COUNT(*) FROM ecgc_seasons').fetchone()[0] >= 18
                if not has_ecgc and ecgc_importer.DEFAULT_ECGC_SQLITE.exists():
                    ecgc_importer.import_ecgc_data(_c_init)
        except Exception:
            pass

    app = FastAPI(title="Golf League Secretary — Modern Web Edition (GLS9 Clean-Room)", version="2.0.0")
    app.state.db_file = db_file

    @contextmanager
    def get_conn() -> Generator[sqlite3.Connection, None, None]:
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
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
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
    async def _request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default handler echoes the offending input back; a JSON NaN/Infinity
        # input then crashes the error serialiser (500). Return only loc/msg/type.
        errors = [
            {"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(golf_engine.NotFoundError)
    async def _not_found(_: Request, exc: golf_engine.NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(golf_engine.InvalidInputError)
    async def _invalid_input(_: Request, exc: golf_engine.InvalidInputError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(sqlite3.Error)
    async def _db_error(_: Request, exc: sqlite3.Error) -> JSONResponse:
        # Never leak SQL / schema details to the client.
        return JSONResponse(status_code=500, content={"detail": "Database error"})

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
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
    def list_leagues() -> dict[str, Any]:
        with get_conn() as conn:
            leagues = golf_engine.rows_as_dicts(conn.execute('SELECT * FROM "Leagues" ORDER BY CASE WHEN "LeagueID"=20261 THEN 0 WHEN "LeagueID">=20180 THEN 1 ELSE 2 END, "LeagueID" DESC'))
            courses = {c["CourseID"]: c["CourseName"] for c in golf_engine.rows_as_dicts(conn.execute('SELECT "CourseID","CourseName" FROM "Courses"'))}
            out_leagues = []
            for lg in leagues:
                lid = golf_engine.safe_int(lg.get("LeagueID"), -1)
                if lid < 1 or str(lg.get("LeagueID")).strip() not in (str(lid), f"{lid}.0"):
                    continue  # skip corrupt rows; LeagueID is interpolated into table names
                out_leagues.append(lg)
                lg["CourseName"] = courses.get(lg.get("CourseID"), "Edwards County Golf Course")
                lg["LeagueHoles"] = int(lg.get("LeagueHoles") or 9)
                p_tbl = f"{lid}Players"
                t_tbl = f"{lid}Teams"
                s_tbl = f"{lid}Schedule"
                lg["player_count"] = conn.execute(f'SELECT COUNT(*) FROM "{p_tbl}"').fetchone()[0] if golf_engine.table_exists(conn, p_tbl) else 0
                lg["team_count"] = conn.execute(f'SELECT COUNT(*) FROM "{t_tbl}"').fetchone()[0] if golf_engine.table_exists(conn, t_tbl) else 0
                lg["week_count"] = conn.execute(f'SELECT COUNT(*) FROM "{s_tbl}"').fetchone()[0] if golf_engine.table_exists(conn, s_tbl) else 0
        return {"default_league_id": 20261, "default_course_id": 5, "default_holes": 9, "leagues": out_leagues}

    @app.get("/api/leagues/{lid}/standings")
    def league_standings(lid: LeagueId) -> dict[str, Any]:
        with get_conn() as conn:
            require_league(conn, lid)
            return golf_engine.get_league_standings(conn, lid)

    @app.get("/api/leagues/{lid}/week/{week_num}")
    def week_scorecard(lid: LeagueId, week_num: WeekNum) -> dict[str, Any]:
        with get_conn() as conn:
            require_league(conn, lid)
            return golf_engine.get_week_scorecard(conn, lid, week_num)

    @app.post("/api/leagues/{lid}/week/{week_num}/scores")
    def save_week_score(lid: LeagueId, week_num: WeekNum, req: ScoreSaveReq) -> dict[str, Any]:
        with get_conn() as conn:
            require_league(conn, lid)
            if not golf_engine.table_exists(conn, f"{lid}PlayerResults"):
                raise HTTPException(status_code=404, detail=f"League {lid} has no results table")
            return golf_engine.save_player_week_score(conn, lid, week_num, req.model_dump())

    @app.post("/api/leagues/{lid}/week/{week_num}/auto-score-matches")
    def auto_score_week(lid: LeagueId, week_num: WeekNum) -> dict[str, Any]:
        with get_conn() as conn:
            require_league(conn, lid)
            if not golf_engine.table_exists(conn, f"{lid}PlayerResults") or not golf_engine.table_exists(conn, f"{lid}Players"):
                raise HTTPException(status_code=404, detail=f"League {lid} has no results table")
            return golf_engine.auto_score_week_matches(conn, lid, week_num)

    @app.get("/api/leagues/{lid}/week/{week_num}/report")
    def week_clubhouse_report(lid: LeagueId, week_num: WeekNum) -> dict[str, Any]:
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
    def recalc_hcps(lid: LeagueId) -> dict[str, Any]:
        with get_conn() as conn:
            require_league(conn, lid)
            if not golf_engine.table_exists(conn, f"{lid}Players"):
                raise HTTPException(status_code=404, detail=f"League {lid} has no players table")
            return golf_engine.recalculate_handicaps(conn, lid)

    @app.get("/api/leagues/{lid}/schedule")
    def get_schedule(lid: LeagueId) -> dict[str, Any]:
        with get_conn() as conn:
            require_league(conn, lid)
            s_tbl = f"{lid}Schedule"
            t_tbl = f"{lid}Teams"
            tt_tbl = f"{lid}TeeTimes"
            teams = {r["TeamID"]: r["TeamName"] for r in golf_engine.rows_as_dicts(conn.execute(f'SELECT "TeamID","TeamName" FROM "{t_tbl}"'))} if golf_engine.table_exists(conn, t_tbl) else {}
            sched = golf_engine.rows_as_dicts(conn.execute(f'SELECT * FROM "{s_tbl}" ORDER BY "WeekNum" ASC')) if golf_engine.table_exists(conn, s_tbl) else []
            tt = golf_engine.rows_as_dicts(conn.execute(f'SELECT * FROM "{tt_tbl}" ORDER BY "MatchNum" ASC')) if golf_engine.table_exists(conn, tt_tbl) else []

            ecgc_by_wk: dict[int, list[dict[str, Any]]] = {}
            if golf_engine.table_exists(conn, "ecgc_matches") and golf_engine.table_exists(conn, "ecgc_events"):
                for em in golf_engine.rows_as_dicts(
                    conn.execute(
                        """
                        SELECT m.id AS match_id, m.match_number, m.team_a_name, m.team_a_points,
                               m.team_b_name, m.team_b_points, m.winner_label, m.result_summary, e.week_number
                        FROM ecgc_matches m
                        JOIN ecgc_events e ON e.id = m.event_id
                        WHERE m.gls_league_id = ?
                        ORDER BY e.week_number ASC, m.match_number ASC
                        """,
                        (lid,),
                    )
                ):
                    ecgc_by_wk.setdefault(int(em.get("week_number") or 0), []).append(em)

            for w in sched:
                wk_num = int(w.get("WeekNum") or 0)
                w["Match1Label"] = f"Team {w.get('Match1Team1')} ({teams.get(w.get('Match1Team1'), '')}) vs Team {w.get('Match1Team2')} ({teams.get(w.get('Match1Team2'), '')})"
                w["Match2Label"] = f"Team {w.get('Match2Team1')} ({teams.get(w.get('Match2Team1'), '')}) vs Team {w.get('Match2Team2')} ({teams.get(w.get('Match2Team2'), '')})"
                wk_matches: list[dict[str, Any]] = []
                em_list = ecgc_by_wk.get(wk_num, [])
                em_by_num = {int(x.get("match_number") or 0): x for x in em_list}
                for m_idx in range(1, 12):
                    t1 = golf_engine.safe_int(w.get(f"Match{m_idx}Team1"))
                    t2 = golf_engine.safe_int(w.get(f"Match{m_idx}Team2"))
                    em = em_by_num.get(m_idx)
                    if t1 <= 0 and t2 <= 0 and not em:
                        continue
                    t1_name = teams.get(t1) or (em.get("team_a_name") if em else f"Team {t1}")
                    t2_name = teams.get(t2) or (em.get("team_b_name") if em else f"Team {t2}")
                    wk_matches.append({
                        "match_num": m_idx,
                        "team1_id": t1,
                        "team1_name": t1_name,
                        "team2_id": t2,
                        "team2_name": t2_name,
                        "label": f"{t1_name} vs {t2_name}",
                        "match_id": em.get("match_id") if em else None,
                        "team1_pts": em.get("team_a_points") if em else None,
                        "team2_pts": em.get("team_b_points") if em else None,
                        "winner_label": em.get("winner_label") if em else None,
                    })
                w["matches"] = wk_matches
                w["matches_count"] = len(wk_matches)
            return {"league_id": lid, "schedule": sched, "tee_times": tt, "teams": teams}

    @app.post("/api/leagues/{lid}/schedule/generate")
    def gen_schedule(lid: LeagueId, req: ScheduleGenReq) -> dict[str, Any]:
        with get_conn() as conn:
            require_league(conn, lid)
            sched = golf_engine.generate_schedule(conn, lid, req.weeks, req.start_date)
            return {"league_id": lid, "generated_weeks": len(sched), "schedule": sched}

    @app.post("/api/leagues/{lid}/players")
    def upsert_player(lid: LeagueId, req: PlayerUpsertReq) -> dict[str, Any]:
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
    def list_courses() -> dict[str, Any]:
        with get_conn() as conn:
            return {"default_course_id": 5, "default_course_name": "Edwards County Golf Course", "default_holes": 9, "courses": golf_engine.get_courses(conn)}

    @app.get("/api/tables")
    def list_tables() -> dict[str, Any]:
        with get_conn() as conn:
            names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
            out = []
            for n in names:
                cnt = conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
                out.append({"name": n, "row_count": cnt})
            return {"table_count": len(out), "tables": out}

    @app.get("/api/tables/{table_name}")
    def inspect_table(table_name: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,128}", table_name or ""):
            raise HTTPException(status_code=404, detail="Table not found")
        clean = table_name
        with get_conn() as conn:
            if not golf_engine.table_exists(conn, clean):
                raise HTTPException(status_code=404, detail="Table not found")
            rows = golf_engine.rows_as_dicts(conn.execute(f'SELECT * FROM "{clean}" LIMIT 200'))
            return {"table": clean, "row_count": len(rows), "rows": rows}

    @app.post("/api/import/mdb")
    def import_mdb(file: UploadFile = File(...)) -> dict[str, Any]:
        fd, tmp = tempfile.mkstemp(suffix=".mdb")
        try:
            with os.fdopen(fd, "wb") as out:
                size = 0
                head = b""
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

    @app.post("/api/import/ecgc")
    def import_ecgc() -> dict[str, Any]:
        with get_conn() as conn:
            try:
                res = ecgc_importer.import_ecgc_data(conn)
                return {"status": "ok", **res}
            except FileNotFoundError as e:
                raise HTTPException(status_code=404, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"ECGC import failed: {str(e)}")

    @app.get("/api/ecgc/seasons")
    def list_ecgc_seasons() -> dict[str, Any]:
        with get_conn() as conn:
            if not golf_engine.table_exists(conn, "ecgc_seasons"):
                return {"count": 0, "seasons": []}
            rows = golf_engine.rows_as_dicts(conn.execute('SELECT * FROM ecgc_seasons ORDER BY season_year DESC, league_slug ASC'))
            return {"count": len(rows), "seasons": rows}

    @app.get("/api/ecgc/standings")
    def get_ecgc_standings(season_year: int | None = None, league_slug: str | None = None, league_id: int | None = None) -> dict[str, Any]:
        with get_conn() as conn:
            if not golf_engine.table_exists(conn, "ecgc_standings"):
                return {"first_half": [], "second_half": [], "final": [], "all_rows": []}
            query = "SELECT * FROM ecgc_standings WHERE 1=1"
            params: list[Any] = []
            if league_id:
                query += " AND gls_league_id = ?"
                params.append(league_id)
            if season_year:
                query += " AND season_year = ?"
                params.append(season_year)
            if league_slug:
                query += " AND league_slug = ?"
                params.append(league_slug)
            query += " ORDER BY rank ASC"
            rows = golf_engine.rows_as_dicts(conn.execute(query, params))
            first = [r for r in rows if r.get("split_name") == "first_half"]
            second = [r for r in rows if r.get("split_name") == "second_half"]
            final = [r for r in rows if r.get("split_name") == "final"]
            return {
                "season_year": season_year,
                "league_slug": league_slug,
                "first_half": first,
                "second_half": second,
                "final": final,
                "all_rows": rows,
            }

    @app.get("/api/ecgc/brackets")
    def list_ecgc_brackets(season_year: int | None = None, league_slug: str | None = None) -> dict[str, Any]:
        with get_conn() as conn:
            if not golf_engine.table_exists(conn, "ecgc_brackets"):
                return {"count": 0, "brackets": []}
            query = "SELECT * FROM ecgc_brackets WHERE 1=1"
            params: list[Any] = []
            if season_year:
                query += " AND season_year = ?"
                params.append(season_year)
            if league_slug:
                query += " AND league_slug = ?"
                params.append(league_slug)
            query += " ORDER BY season_year DESC, league_slug ASC, id ASC"
            rows = golf_engine.rows_as_dicts(conn.execute(query, params))
            return {"count": len(rows), "brackets": rows}

    @app.get("/api/ecgc/players")
    def list_ecgc_players() -> dict[str, Any]:
        with get_conn() as conn:
            if not golf_engine.table_exists(conn, "ecgc_players"):
                return {"count": 0, "players": []}
            query = """
                SELECT 
                    p.id, p.slug, p.display_name, p.first_name, p.last_name, p.primary_division, p.active_flag,
                    COUNT(r.id) as career_rounds,
                    ROUND(AVG(CASE WHEN r.gross_total > 20 THEN r.gross_total END), 1) as avg_gross,
                    ROUND(AVG(CASE WHEN r.net_total > 20 THEN r.net_total END), 1) as avg_net,
                    MIN(CASE WHEN r.gross_total > 20 THEN r.gross_total END) as best_gross,
                    MIN(CASE WHEN r.net_total > 20 THEN r.net_total END) as best_net,
                    ROUND(SUM(COALESCE(r.points_adjustment, 0.0)), 1) as total_pt_points,
                    COUNT(DISTINCT r.season_year) as seasons_played
                FROM ecgc_players p
                LEFT JOIN ecgc_rounds r ON p.id = r.player_id
                GROUP BY p.id
                ORDER BY p.last_name ASC, p.first_name ASC
            """
            rows = golf_engine.rows_as_dicts(conn.execute(query))
            return {"count": len(rows), "players": rows}

    @app.get("/api/ecgc/players/{player_id}")
    def get_ecgc_player_profile(player_id: int) -> dict[str, Any]:
        with get_conn() as conn:
            if not golf_engine.table_exists(conn, "ecgc_players"):
                raise HTTPException(status_code=404, detail="ECGC players table not found")
            p_rows = golf_engine.rows_as_dicts(conn.execute("SELECT * FROM ecgc_players WHERE id=?", (player_id,)))
            if not p_rows:
                raise HTTPException(status_code=404, detail=f"Player {player_id} not found")
            player = p_rows[0]

            season_summary = golf_engine.rows_as_dicts(conn.execute("""
                SELECT 
                    r.season_year, r.league_slug, r.team_name,
                    COUNT(r.id) as rounds_played,
                    ROUND(AVG(CASE WHEN r.gross_total > 20 THEN r.gross_total END), 1) as avg_gross,
                    ROUND(AVG(CASE WHEN r.net_total > 20 THEN r.net_total END), 1) as avg_net,
                    MIN(CASE WHEN r.gross_total > 20 THEN r.gross_total END) as best_gross,
                    ROUND(SUM(COALESCE(r.points_adjustment, 0.0)), 1) as season_pt_total,
                    ROUND(AVG(r.handicap), 1) as avg_handicap
                FROM ecgc_rounds r
                WHERE r.player_id = ?
                GROUP BY r.season_year, r.league_slug
                ORDER BY r.season_year DESC
            """, (player_id,)))

            rounds = golf_engine.rows_as_dicts(conn.execute("""
                SELECT 
                    r.id as round_id, r.event_id, r.match_id, r.season_year, r.league_slug,
                    r.team_name, r.handicap, r.gross_total, r.net_total, r.over_under, r.points_adjustment,
                    e.event_date, e.event_title, e.week_number, e.stage
                FROM ecgc_rounds r
                LEFT JOIN ecgc_events e ON r.event_id = e.id
                WHERE r.player_id = ?
                ORDER BY r.season_year DESC, e.event_date DESC, r.id DESC
                LIMIT 50
            """, (player_id,)))

            hcp_progression = [
                {"date": r.get("event_date") or f"{r.get('season_year')}-W{i+1}", "hcp": r.get("handicap"), "gross": r.get("gross_total"), "pt": r.get("points_adjustment")}
                for i, r in enumerate(reversed(rounds)) if r.get("handicap") is not None
            ]

            return {
                "player": player,
                "career_seasons": len(season_summary),
                "season_summary": season_summary,
                "rounds": rounds,
                "handicap_progression": hcp_progression,
            }

    @app.get("/api/ecgc/matches")
    def list_ecgc_matches(
        season_year: int | None = None,
        league_slug: str | None = None,
        week_number: int | None = None,
        league_id: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        with get_conn() as conn:
            if not golf_engine.table_exists(conn, "ecgc_matches"):
                return {"count": 0, "matches": []}
            query = """
                SELECT m.*, e.week_number, e.event_date, e.event_title
                FROM ecgc_matches m
                LEFT JOIN ecgc_events e ON m.event_id = e.id
                WHERE 1=1
            """
            params: list[Any] = []
            if league_id:
                query += " AND m.gls_league_id = ?"
                params.append(league_id)
            if season_year:
                query += " AND m.season_year = ?"
                params.append(season_year)
            if league_slug:
                query += " AND m.league_slug = ?"
                params.append(league_slug)
            if week_number:
                query += " AND e.week_number = ?"
                params.append(week_number)
            query += " ORDER BY m.season_year DESC, e.week_number ASC, m.match_number ASC LIMIT ?"
            params.append(limit)
            rows = golf_engine.rows_as_dicts(conn.execute(query, params))
            return {"count": len(rows), "matches": rows}

    @app.get("/api/ecgc/matches/{match_id}/breakdown")
    def get_ecgc_match_breakdown(match_id: int) -> dict[str, Any]:
        with get_conn() as conn:
            if not golf_engine.table_exists(conn, "ecgc_matches"):
                raise HTTPException(status_code=404, detail="ECGC matches table not found")
            m_rows = golf_engine.rows_as_dicts(conn.execute("SELECT * FROM ecgc_matches WHERE id=?", (match_id,)))
            if not m_rows:
                raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
            match = m_rows[0]

            rounds = golf_engine.rows_as_dicts(conn.execute("""
                SELECT * FROM ecgc_rounds WHERE match_id = ? ORDER BY team_id ASC, id ASC
            """, (match_id,)))

            round_ids = [r["id"] for r in rounds]
            hole_scores: dict[int, list[dict[str, Any]]] = {}
            if round_ids:
                placeholders = ",".join("?" for _ in round_ids)
                h_rows = golf_engine.rows_as_dicts(conn.execute(f"""
                    SELECT * FROM ecgc_hole_scores WHERE round_id IN ({placeholders}) ORDER BY hole_number ASC
                """, round_ids))
                for h in h_rows:
                    hole_scores.setdefault(h["round_id"], []).append(h)

            for r in rounds:
                r["hole_scores"] = hole_scores.get(r["id"], [])

            team_a_rounds = [r for r in rounds if r.get("team_id") == match.get("team_a_id")]
            team_b_rounds = [r for r in rounds if r.get("team_id") == match.get("team_b_id")]

            pars = [4, 4, 4, 3, 5, 5, 4, 3, 4]
            ranks = [7, 1, 5, 4, 6, 3, 2, 8, 9]

            hcp_a = sum(float(r.get("handicap") or 0) for r in team_a_rounds)
            hcp_b = sum(float(r.get("handicap") or 0) for r in team_b_rounds)
            diff = round(hcp_a - hcp_b)
            strokes_a = match_engine.strokes_per_hole(diff, ranks, 9) if diff > 0 else [0]*9
            strokes_b = match_engine.strokes_per_hole(abs(diff), ranks, 9) if diff < 0 else [0]*9

            holes_data = []
            team_a_hole_pts = 0.0
            team_b_hole_pts = 0.0

            for i in range(9):
                h_num = i + 1
                g_a = sum(
                    r["hole_scores"][i]["gross_score"]
                    for r in team_a_rounds
                    if len(r.get("hole_scores", [])) > i
                ) if team_a_rounds else 0
                g_b = sum(
                    r["hole_scores"][i]["gross_score"]
                    for r in team_b_rounds
                    if len(r.get("hole_scores", [])) > i
                ) if team_b_rounds else 0

                net_a = g_a - strokes_a[i]
                net_b = g_b - strokes_b[i]

                if net_a < net_b:
                    pts_a, pts_b, w = 1.0, 0.0, "team_a"
                elif net_b < net_a:
                    pts_a, pts_b, w = 0.0, 1.0, "team_b"
                else:
                    pts_a, pts_b, w = 0.5, 0.5, "tie"

                team_a_hole_pts += pts_a
                team_b_hole_pts += pts_b

                holes_data.append({
                    "hole_number": h_num,
                    "par": pars[i],
                    "hole_rank": ranks[i],
                    "team_a_gross": g_a,
                    "team_a_strokes": strokes_a[i],
                    "team_a_net": net_a,
                    "team_a_pts": pts_a,
                    "team_b_gross": g_b,
                    "team_b_strokes": strokes_b[i],
                    "team_b_net": net_b,
                    "team_b_pts": pts_b,
                    "winner": w,
                })

            team_a_pt = sum(float(r.get("points_adjustment") or 0) for r in team_a_rounds)
            team_b_pt = sum(float(r.get("points_adjustment") or 0) for r in team_b_rounds)

            return {
                "match": match,
                "team_a": {
                    "id": match.get("team_a_id"),
                    "name": match.get("team_a_name"),
                    "rounds": team_a_rounds,
                    "team_hcp": round(hcp_a, 1),
                    "hole_points": team_a_hole_pts,
                    "pt_bonus_total": round(team_a_pt, 1),
                    "total_points": round(team_a_hole_pts + team_a_pt, 1),
                },
                "team_b": {
                    "id": match.get("team_b_id"),
                    "name": match.get("team_b_name"),
                    "rounds": team_b_rounds,
                    "team_hcp": round(hcp_b, 1),
                    "hole_points": team_b_hole_pts,
                    "pt_bonus_total": round(team_b_pt, 1),
                    "total_points": round(team_b_hole_pts + team_b_pt, 1),
                },
                "holes": holes_data,
            }

    @app.get("/api/rules/config/{lid}")
    def get_rules_config(lid: LeagueId) -> dict[str, Any]:
        with get_conn() as conn:
            if not golf_engine.table_exists(conn, "league_rules_config"):
                raise HTTPException(status_code=404, detail="Rules config table not found")
            rows = golf_engine.rows_as_dicts(conn.execute("SELECT * FROM league_rules_config WHERE league_id=?", (lid,)))
            if not rows:
                return {
                    "league_id": lid,
                    "rule_type": "ecgc_2person_match",
                    "holes_count": 9,
                    "points_per_hole_win": 1.0,
                    "points_per_hole_tie": 0.5,
                    "match_hole_points_total": 9.0,
                    "net_bonus_enabled": 1,
                    "net_bonus_below_max": 35,
                    "net_bonus_pts": 1.0,
                    "net_even_min": 36,
                    "net_even_max": 36,
                    "net_even_pts": 0.0,
                    "net_penalty_above_min": 37,
                    "net_penalty_pts": -1.0,
                    "handicap_progression_mode": "weekly_pt",
                    "plus_handicaps_enabled": 1,
                    "unplayed_round_score": -36,
                }
            return rows[0]

    @app.post("/api/rules/config/{lid}")
    def update_rules_config(lid: LeagueId, req: dict[str, Any]) -> dict[str, Any]:
        _validate_ecgc_rules(req)
        with get_conn() as conn:
            if not conn.execute('SELECT 1 FROM Leagues WHERE LeagueID=?', (lid,)).fetchone():
                raise HTTPException(404, detail="League not found")
            if not golf_engine.table_exists(conn, "league_rules_config"):
                raise HTTPException(status_code=404, detail="Rules config table not found")
            with conn:
                conn.execute("""
                    INSERT INTO league_rules_config (
                        league_id, rule_type, holes_count, points_per_hole_win, points_per_hole_tie,
                        match_hole_points_total, net_bonus_enabled, net_bonus_below_max, net_bonus_pts,
                        net_even_min, net_even_max, net_even_pts, net_penalty_above_min, net_penalty_pts,
                        handicap_progression_mode, plus_handicaps_enabled, unplayed_round_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(league_id) DO UPDATE SET
                        rule_type = excluded.rule_type,
                        holes_count = excluded.holes_count,
                        points_per_hole_win = excluded.points_per_hole_win,
                        points_per_hole_tie = excluded.points_per_hole_tie,
                        match_hole_points_total = excluded.match_hole_points_total,
                        net_bonus_enabled = excluded.net_bonus_enabled,
                        net_bonus_below_max = excluded.net_bonus_below_max,
                        net_bonus_pts = excluded.net_bonus_pts,
                        net_even_min = excluded.net_even_min,
                        net_even_max = excluded.net_even_max,
                        net_even_pts = excluded.net_even_pts,
                        net_penalty_above_min = excluded.net_penalty_above_min,
                        net_penalty_pts = excluded.net_penalty_pts,
                        handicap_progression_mode = excluded.handicap_progression_mode,
                        plus_handicaps_enabled = excluded.plus_handicaps_enabled,
                        unplayed_round_score = excluded.unplayed_round_score
                """, (
                    lid,
                    req.get("rule_type", "ecgc_2person_match"),
                    int(req.get("holes_count", 9)),
                    float(req.get("points_per_hole_win", 1.0)),
                    float(req.get("points_per_hole_tie", 0.5)),
                    float(req.get("match_hole_points_total", 9.0)),
                    int(req.get("net_bonus_enabled", 1)),
                    int(req.get("net_bonus_below_max", 35)),
                    float(req.get("net_bonus_pts", 1.0)),
                    int(req.get("net_even_min", 36)),
                    int(req.get("net_even_max", 36)),
                    float(req.get("net_even_pts", 0.0)),
                    int(req.get("net_penalty_above_min", 37)),
                    float(req.get("net_penalty_pts", -1.0)),
                    req.get("handicap_progression_mode", "weekly_pt"),
                    int(req.get("plus_handicaps_enabled", 1)),
                    int(req.get("unplayed_round_score", -36)),
                ))
            return get_rules_config(lid)

    @app.post("/api/rules/simulate")
    def simulate_ecgc_match(req: dict[str, Any]) -> dict[str, Any]:
        for key in ("team_a", "team_b", "rules"):
            if not isinstance(req.get(key, {}), dict):
                raise HTTPException(422, detail=f"{key} must be an object")
        _validate_ecgc_rules(req.get("rules", {}))
        for key in ("hole_ranks", "pars"):
            if key in req:
                values = req[key]
                if not isinstance(values, list) or len(values) != 9 or any(type(v) is not int or v < 1 for v in values):
                    raise HTTPException(422, detail=f"{key} must contain nine positive integers")
                if key == "hole_ranks" and sorted(values) != list(range(1, 10)):
                    raise HTTPException(422, detail="hole_ranks must be a permutation of 1..9")
        for team_key in ("team_a", "team_b"):
            for player_key in ("player1", "player2"):
                player = req.get(team_key, {}).get(player_key, {})
                if not isinstance(player, dict):
                    raise HTTPException(422, detail="Players must be objects")
                hcp = player.get("handicap", 0)
                if isinstance(hcp, bool) or not isinstance(hcp, (float, int)) or not math.isfinite(hcp) or not -54 <= hcp <= 54:
                    raise HTTPException(422, detail="Invalid player handicap")
                for scores_key in ("gross_scores", "holes"):
                    if scores_key in player:
                        scores = player[scores_key]
                        if not isinstance(scores, list) or len(scores) != 9 or any(type(s) is not int or not -36 <= s <= golf_engine.MAX_HOLE_SCORE for s in scores):
                            raise HTTPException(422, detail="Scores must contain nine valid integers")
        team_a = req.get("team_a", {})
        team_b = req.get("team_b", {})
        rules = req.get("rules", {})
        ranks = req.get("hole_ranks") or [7, 1, 5, 4, 6, 3, 2, 8, 9]
        pars = req.get("pars") or [4, 4, 4, 3, 5, 5, 4, 3, 4]
        return match_engine.score_ecgc_2person_match(
            team_a=team_a,
            team_b=team_b,
            hole_ranks=ranks,
            pars=pars,
            rules=rules,
        )

    @app.get("/api/ecgc/course-analytics")
    def get_ecgc_course_analytics(league_id: int | None = None) -> dict[str, Any]:
        with get_conn() as conn:
            pars = [4, 4, 4, 3, 5, 5, 4, 3, 4]
            caps = [13, 1, 9, 7, 11, 5, 3, 15, 17]
            ranks9 = [7, 1, 5, 4, 6, 3, 2, 8, 9]
            yards_blue = [307, 384, 313, 199, 481, 519, 392, 166, 272]
            yards_white = [300, 374, 301, 192, 472, 513, 384, 156, 268]
            yards_red = [293, 298, 227, 183, 435, 405, 310, 146, 253]

            hole_rows: list[dict[str, Any]] = []
            if golf_engine.table_exists(conn, "ecgc_hole_scores") and golf_engine.table_exists(conn, "ecgc_rounds"):
                where_sql = "WHERE hs.gross_score > 0 AND r.gross_total >= 20"
                params: list[Any] = []
                if league_id and int(league_id) >= 20180:
                    yr = int(league_id) // 10
                    slug = "womens" if int(league_id) % 10 == 2 else "mens"
                    where_sql += " AND r.season_year = ? AND r.league_slug = ?"
                    params.extend([yr, slug])

                q = f"""
                    SELECT
                        hs.hole_number,
                        COUNT(*) AS samples,
                        ROUND(AVG(hs.gross_score), 2) AS avg_gross,
                        MIN(hs.gross_score) AS best_gross,
                        MAX(hs.gross_score) AS max_gross,
                        SUM(CASE WHEN hs.gross_score <= hs.par - 2 THEN 1 ELSE 0 END) AS eagles_plus,
                        SUM(CASE WHEN hs.gross_score = hs.par - 1 THEN 1 ELSE 0 END) AS birdies,
                        SUM(CASE WHEN hs.gross_score = hs.par THEN 1 ELSE 0 END) AS pars_cnt,
                        SUM(CASE WHEN hs.gross_score = hs.par + 1 THEN 1 ELSE 0 END) AS bogeys,
                        SUM(CASE WHEN hs.gross_score >= hs.par + 2 THEN 1 ELSE 0 END) AS double_plus
                    FROM ecgc_hole_scores hs
                    JOIN ecgc_rounds r ON r.id = hs.round_id
                    {where_sql}
                    GROUP BY hs.hole_number
                    ORDER BY hs.hole_number ASC
                """
                stats_by_h = {int(r["hole_number"]): r for r in golf_engine.rows_as_dicts(conn.execute(q, params))}
            else:
                stats_by_h = {}

            for i in range(9):
                h_num = i + 1
                st = stats_by_h.get(h_num, {})
                avg_g = float(st.get("avg_gross") or pars[i])
                over_par = round(avg_g - pars[i], 2)
                hole_rows.append({
                    "hole": h_num,
                    "par": pars[i],
                    "handicap_stroke_index": caps[i],
                    "nine_hole_rank": ranks9[i],
                    "yards_blue": yards_blue[i],
                    "yards_white": yards_white[i],
                    "yards_red": yards_red[i],
                    "samples": int(st.get("samples") or 0),
                    "avg_gross": avg_g,
                    "over_par_avg": over_par,
                    "eagles_plus": int(st.get("eagles_plus") or 0),
                    "birdies": int(st.get("birdies") or 0),
                    "pars": int(st.get("pars_cnt") or 0),
                    "bogeys": int(st.get("bogeys") or 0),
                    "double_plus": int(st.get("double_plus") or 0),
                })

            ranked = sorted(hole_rows, key=lambda x: (-x["over_par_avg"], x["nine_hole_rank"]))
            for rk, item in enumerate(ranked, start=1):
                item["toughness_rank"] = rk

            return {
                "course_id": 5,
                "course_name": "Edwards County Golf Course",
                "league_id": league_id,
                "holes": hole_rows,
            }

    @app.post("/api/leagues/{lid}/teams/{team_id}")
    def update_league_team(lid: LeagueId, team_id: int, req: dict[str, Any]) -> dict[str, Any]:
        with get_conn() as conn:
            require_league(conn, lid)
            t_tbl = f"{lid}Teams"
            p_tbl = f"{lid}Players"
            if not golf_engine.table_exists(conn, t_tbl):
                raise HTTPException(404, detail=f"League {lid} has no teams table")
            pa = golf_engine.safe_int(req.get("PlayerA")) or None
            pb = golf_engine.safe_int(req.get("PlayerB")) or None
            tname = _clean_text(str(req.get("TeamName") or f"Team {team_id}"), field="TeamName", max_len=80, required=True)
            with conn:
                exists = conn.execute(f'SELECT 1 FROM "{t_tbl}" WHERE "TeamID"=?', (team_id,)).fetchone()
                if exists:
                    conn.execute(
                        f'UPDATE "{t_tbl}" SET "TeamName"=?, "PlayerA"=?, "PlayerB"=? WHERE "TeamID"=?',
                        (tname, pa, pb, team_id),
                    )
                else:
                    conn.execute(
                        f'INSERT INTO "{t_tbl}" ("TeamID","TeamName","PlayerA","PlayerB","Division","Points","PrevPts") VALUES (?,?,?,?,1,0,0)',
                        (team_id, tname, pa, pb),
                    )
                if golf_engine.table_exists(conn, p_tbl):
                    for pid in (pa, pb):
                        if pid:
                            conn.execute(f'UPDATE "{p_tbl}" SET "TeamID"=? WHERE "PlayerID"=?', (team_id, pid))
                    conn.execute(
                        f"""
                        UPDATE "{t_tbl}"
                        SET "Handicap" = ROUND(
                            COALESCE((SELECT p."Handicap" FROM "{p_tbl}" p WHERE p."PlayerID" = "{t_tbl}"."PlayerA"), 0.0) +
                            COALESCE((SELECT p."Handicap" FROM "{p_tbl}" p WHERE p."PlayerID" = "{t_tbl}"."PlayerB"), 0.0),
                            1
                        )
                        WHERE "TeamID" = ?
                        """,
                        (team_id,),
                    )
            return golf_engine.get_league_standings(conn, lid)

    @app.post("/api/ecgc/leagues/{lid}/week/{week_num}/matchups")
    def save_week_matchups(lid: LeagueId, week_num: WeekNum, req: dict[str, Any]) -> dict[str, Any]:
        with get_conn() as conn:
            require_league(conn, lid)
            s_tbl = f"{lid}Schedule"
            if not golf_engine.table_exists(conn, s_tbl):
                raise HTTPException(404, detail=f"League {lid} has no schedule table")
            dt_str = _clean_text(str(req.get("date") or date.today().isoformat()), field="date", max_len=32, required=False) or date.today().isoformat()
            half = 1 if int(req.get("half") or (1 if week_num <= 8 else 2)) == 1 else 2
            weather = _clean_text(str(req.get("weather") or "Clear"), field="weather", max_len=32, required=False) or "Clear"
            matches = req.get("matches") or []
            if not isinstance(matches, list):
                raise HTTPException(422, detail="matches must be a list")

            cols_check = {d[1] for d in conn.execute(f'PRAGMA table_info("{s_tbl}")').fetchall()}
            with conn:
                for m_idx in range(3, 12):
                    for side in (1, 2):
                        cname = f"Match{m_idx}Team{side}"
                        if cname not in cols_check:
                            conn.execute(f'ALTER TABLE "{s_tbl}" ADD COLUMN "{cname}" INTEGER')

                m_vals: list[int | None] = []
                for m_idx in range(1, 12):
                    item = next((x for x in matches if isinstance(x, dict) and int(x.get("match_num") or 0) == m_idx), None)
                    if not item and m_idx - 1 < len(matches) and isinstance(matches[m_idx - 1], dict):
                        item = matches[m_idx - 1]
                    t1 = golf_engine.safe_int(item.get("team1_id")) if item else 0
                    t2 = golf_engine.safe_int(item.get("team2_id")) if item else 0
                    m_vals.extend([t1 if t1 > 0 else None, t2 if t2 > 0 else None])

                ex = conn.execute(f'SELECT 1 FROM "{s_tbl}" WHERE "WeekNum"=?', (week_num,)).fetchone()
                match_col_names = [f'"Match{i}Team{s}"' for i in range(1, 12) for s in (1, 2)]
                if ex:
                    set_sql = '"Date"=?, "Half"=?, "Weather"=?, ' + ", ".join(f"{c}=?" for c in match_col_names)
                    conn.execute(f'UPDATE "{s_tbl}" SET {set_sql} WHERE "WeekNum"=?', [dt_str, half, weather, *m_vals, week_num])
                else:
                    cols_sql = '"WeekNum", "Date", "CourseID", "Half", "Weather", ' + ", ".join(match_col_names)
                    qs = ", ".join("?" for _ in range(5 + len(m_vals)))
                    conn.execute(f'INSERT INTO "{s_tbl}" ({cols_sql}) VALUES ({qs})', [week_num, dt_str, 5, half, weather, *m_vals])

            return get_schedule(lid)

    @app.post("/api/ecgc/seasons/rollover")
    def rollover_ecgc_season(req: dict[str, Any]) -> dict[str, Any]:
        source_lid = int(req.get("source_league_id") or 20261)
        target_year = int(req.get("target_year") or 2027)
        if target_year < 2018 or target_year > 2100:
            raise HTTPException(422, detail="target_year must be between 2018 and 2100")
        division = str(req.get("division") or ("womens" if source_lid % 10 == 2 else "mens")).lower()
        if division not in ("mens", "womens"):
            raise HTTPException(422, detail="division must be mens or womens")
        target_lid = target_year * 10 + (2 if division == "womens" else 1)
        weeks = max(1, min(52, int(req.get("weeks") or (12 if division == "womens" else 16))))
        start_date = str(req.get("start_date") or f"{target_year}-05-05")
        div_title = "Women's League" if division == "womens" else "Men's League"
        league_name = _clean_text(
            str(req.get("league_name") or f"{target_year} ECGC {div_title}"),
            field="league_name",
            max_len=80,
            required=True,
        )

        with get_conn() as conn:
            require_league(conn, source_lid)
            src_st = golf_engine.get_league_standings(conn, source_lid)
            day_str = "Tuesday" if division == "womens" else "Wednesday"
            with conn:
                conn.execute('DELETE FROM "Leagues" WHERE "LeagueID"=?', (target_lid,))
                conn.execute(
                    """
                    INSERT INTO "Leagues" (
                        "LeagueID", "LeagueName", "CourseID", "LeagueDay", "FirstTeeTime",
                        "MinsBetweenGroups", "LeagueHoles", "NumManTeams", "PercentHandicap",
                        "MaximumHandicap", "AdjustScores", "SubPercent", "Div1"
                    ) VALUES (?, ?, 5, ?, '06:00 PM', 10, 9, 2, 100.0, 36.0, 0, 100.0, ?)
                    """,
                    (target_lid, league_name, day_str, "Women's Division" if division == "womens" else "Men's Division"),
                )
                conn.execute('DELETE FROM "LeagueRules" WHERE "LeagueID"=?', (target_lid,))
                conn.execute(
                    """
                    INSERT INTO "LeagueRules" (
                        "LeagueID", "IndPtsNet", "IndPtsAct", "IndPtsHolesMatch",
                        "TeamPtsNetMatch", "TeamPtsHolesMatch", "UseIndPts"
                    ) VALUES (?, 1.0, 0.0, 0.0, 2.0, 2.0, -1)
                    """,
                    (target_lid,),
                )
                if golf_engine.table_exists(conn, "league_rules_config"):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO league_rules_config (
                            league_id, rule_type, holes_count, points_per_hole_win, points_per_hole_tie,
                            match_hole_points_total, net_bonus_enabled, net_bonus_below_max, net_bonus_pts,
                            net_even_min, net_even_max, net_even_pts, net_penalty_above_min, net_penalty_pts,
                            handicap_progression_mode, plus_handicaps_enabled, unplayed_round_score
                        ) VALUES (?, 'ecgc_2person_match', 9, 1.0, 0.5, 9.0, 1, 35, 1.0, 36, 36, 0.0, 37, -1.0, 'weekly_pt', 1, -36)
                        """,
                        (target_lid,),
                    )

                t_tbl = f"{target_lid}Teams"
                p_tbl = f"{target_lid}Players"
                s_tbl = f"{target_lid}Schedule"
                pr_tbl = f"{target_lid}PlayerResults"
                tr_tbl = f"{target_lid}TeamResults"
                tt_tbl = f"{target_lid}TeeTimes"
                ms_tbl = f"{target_lid}MatchSetup"
                holes_cols_sql = ", ".join(f'"{i}" INTEGER DEFAULT 0' for i in range(1, 19))
                match_cols_sql = ", ".join(f'"Match{i}Team1" INTEGER, "Match{i}Team2" INTEGER' for i in range(1, 12))

                conn.executescript(f"""
                    CREATE TABLE IF NOT EXISTS "{t_tbl}" (
                        "TeamID" INTEGER PRIMARY KEY, "TeamName" TEXT, "TeamSponsor" TEXT,
                        "PlayerA" INTEGER, "PlayerB" INTEGER, "PlayerC" INTEGER, "PlayerD" INTEGER,
                        "Handicap" REAL DEFAULT 0.0, "Division" INTEGER DEFAULT 1,
                        "1stHalfPts" REAL DEFAULT 0.0, "2ndHalfPts" REAL DEFAULT 0.0,
                        "FinalPts" REAL DEFAULT 0.0, "Points" REAL DEFAULT 0.0,
                        "PrevPts" REAL DEFAULT 0.0, "Money" REAL DEFAULT 0.0, "InMoney" INTEGER DEFAULT 1
                    );
                    CREATE TABLE IF NOT EXISTS "{p_tbl}" (
                        "PlayerID" INTEGER PRIMARY KEY, "TeamID" INTEGER,
                        "PlayerFirst" TEXT, "PlayerLast" TEXT, "Street" TEXT, "City" TEXT,
                        "State" TEXT, "Zip" TEXT, "HomePhone" TEXT, "WorkPhone" TEXT,
                        "FaxPhone" TEXT, "EMail" TEXT, "Handicap" REAL DEFAULT 0.0,
                        "Division" INTEGER DEFAULT 1, "1stHalfPts" REAL DEFAULT 0.0,
                        "2ndHalfPts" REAL DEFAULT 0.0, "FinalPts" REAL DEFAULT 0.0,
                        "Points" REAL DEFAULT 0.0, "PrevPts" REAL DEFAULT 0.0,
                        "Money" REAL DEFAULT 0.0, "InMoney" INTEGER DEFAULT 1
                    );
                    CREATE TABLE IF NOT EXISTS "{s_tbl}" (
                        "WeekNum" INTEGER PRIMARY KEY, "Date" TEXT, "DateType" INTEGER DEFAULT 1,
                        "CourseID" INTEGER DEFAULT 5, "SchedUsed" INTEGER DEFAULT -1,
                        "Half" INTEGER DEFAULT 1, "Weather" TEXT DEFAULT 'Clear',
                        {match_cols_sql}
                    );
                    CREATE TABLE IF NOT EXISTS "{pr_tbl}" (
                        "WeekNum" INTEGER, "PlayerID" INTEGER, {holes_cols_sql},
                        "FrontNine" INTEGER DEFAULT 0, "BackNine" INTEGER DEFAULT 0,
                        "NumPutts" INTEGER DEFAULT 0, "GreensInRegulation" INTEGER DEFAULT 0,
                        "NumFairwaysHit" INTEGER DEFAULT 0, "IndividualPts" REAL DEFAULT 0.0,
                        "FieldPts" REAL DEFAULT 0.0, "Skins" REAL DEFAULT 0.0,
                        "SkinsNet" REAL DEFAULT 0.0, "Sub" INTEGER DEFAULT 0, "Forfeit" INTEGER DEFAULT 0,
                        PRIMARY KEY ("WeekNum", "PlayerID")
                    );
                    CREATE TABLE IF NOT EXISTS "{tr_tbl}" (
                        "WeekNum" INTEGER, "TeamID" INTEGER, "TeamPts" REAL DEFAULT 0.0,
                        "MatchPts" REAL DEFAULT 0.0, "FieldPts" REAL DEFAULT 0.0,
                        "TeamActual" INTEGER DEFAULT 0, "TeamNet" INTEGER DEFAULT 0,
                        "SubPts" REAL DEFAULT 0.0, "UserDefinedPts" REAL DEFAULT 0.0,
                        PRIMARY KEY ("WeekNum", "TeamID")
                    );
                    CREATE TABLE IF NOT EXISTS "{tt_tbl}" ("MatchNum" INTEGER PRIMARY KEY, "TeeTime" TEXT);
                    CREATE TABLE IF NOT EXISTS "{ms_tbl}" ("MatchNum" INTEGER PRIMARY KEY, "Team1" INTEGER, "Team2" INTEGER);
                """)
                conn.execute(f'DELETE FROM "{t_tbl}"')
                conn.execute(f'DELETE FROM "{p_tbl}"')
                for pl in src_st["players"]:
                    conn.execute(
                        f'INSERT INTO "{p_tbl}" ("PlayerID","TeamID","PlayerFirst","PlayerLast","Handicap","Division","Points","PrevPts","EMail","HomePhone") VALUES (?,?,?,?,?,1,0,0,?,?)',
                        (pl["PlayerID"], pl.get("TeamID") or 1, pl.get("PlayerFirst") or "", pl.get("PlayerLast") or "", float(pl.get("Handicap") or 0.0), pl.get("EMail") or "", pl.get("HomePhone") or ""),
                    )
                for tm in src_st["teams"]:
                    conn.execute(
                        f'INSERT INTO "{t_tbl}" ("TeamID","TeamName","PlayerA","PlayerB","Handicap","Division","1stHalfPts","2ndHalfPts","FinalPts","Points","PrevPts") VALUES (?,?,?,?,?,1,0,0,0,0,0)',
                        (tm["TeamID"], tm.get("TeamName") or f"Team {tm['TeamID']}", tm.get("PlayerA"), tm.get("PlayerB"), float(tm.get("CombinedHcp") or tm.get("Handicap") or 0.0)),
                    )
                golf_engine.generate_schedule(conn, target_lid, weeks=weeks, start_date=start_date)

            return {
                "status": "ok",
                "new_league_id": target_lid,
                "league_name": league_name,
                "teams_carried_over": len(src_st["teams"]),
                "players_carried_over": len(src_st["players"]),
                "weeks_generated": weeks,
            }


    @app.get("/api/ecgc/blind-40")
    def get_blind_40_preview(handicap: float = 9.0, target_net: int = 40) -> dict[str, Any]:
        holes = golf_engine.compute_blind_40_scores(handicap, target_net=target_net)
        hcp_int = int(round(float(handicap)))
        return {
            "handicap": hcp_int,
            "target_net": target_net,
            "gross": sum(holes),
            "net": sum(holes) - hcp_int,
            "holes": holes,
        }

    @app.get("/api/export/sqlite")
    def export_sqlite() -> FileResponse:
        return FileResponse(
            app.state.db_file,
            media_type="application/x-sqlite3",
            filename="gls9_modern.db",
        )

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
