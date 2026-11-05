# Golf League Secretary — Modern Web Edition (`gls-modern-web`, `:8104`)

Clean-room modern web replacement of **GolfSoft Golf League Secretary v9.954 (`GLS9`)**, reconstructed from the `:8103` **REA Reverse-Engineering Studio** dossier (`/workspace/knowledge-base/gls9-golfsoft-bundle/dossier.md`).

Replaces the 1990s 32-bit Visual Basic 6.0 executable (`Gls90.exe` + `SPR32X60.ocx` FarPoint Spread ActiveX grids + `Gls90db.mdb` Microsoft Jet 3.5 database) with a zero-dependency **FastAPI + SQLite WAL + 6-Workspace, 5-Theme Web Studio**.

---

## Edwards County Golf Course (ECGC) 9-Hole League Secretary (`AIS-550`–`AIS-553`)

- **Default Course, League & Crisp Light Theme**:
  - Defaults to **Edwards County Golf Course (`CourseID=5`, Kinsley, KS — 9 Holes, Par 36, `[4,3,4,4,4,4,5,3,5]`)**, **`2026 ECGC Men's League` (`LeagueID=20261`)**, and the **Crisp Light (`#f8faf8`)** theme across all **18 historical Men's & Women's seasons (`2018–2026`: `128` golfers, `244` 2-man teams, `1,611` matches, `5,521` rounds, `49,689` hole scores)**.
  - **Naming Invariant**: All ECGC leagues use canonical `ECGC Men's League` and `ECGC Women's League` names (`0` occurrences of `"Twilight"`).
- **ECGC 2-Person Match Play + Net `PT` (`+1/0/-1`) & Handicap Progression (`app/golf_engine.py`)**:
  - Computes 9-hole 2-person match points (`1.0` win / `0.5` tie, `9.0` max) plus per-player Net vs. Par 36 `PT` bonus/penalty (`+1` / `0` / `-1`) and automatic weekly handicap progression (`HCP_next = clamp(HCP_prev - PT, 0, 36)`).
- **Analytics, Pairing Builder, Season Rollover & Printable Clubhouse Sheet**:
  - Includes `GET /api/ecgc/course-analytics` (Hole 1–9 toughness & player career matrix), `POST /api/ecgc/leagues/{id}/generate-week` (round-robin pairing builder), `POST /api/ecgc/leagues/rollover` (new season rollover wizard), and a 1-page `@media print` Clubhouse Sheet.
- **Verification**: `PYTHONPATH=. pytest -q tests/` passes **`234 / 234` tests** (`tests/test_ecgc_rules.py`, `tests/test_ecgc_rules_and_import.py`, and full regression suite).

---

## ✨ V2 Capabilities (3-Squad Audited: AGY → Codex → Claude)

1. **Automatic `.mdb` + Round-Robin Schedule Migration (`app/mdb_migrator.py`)**:
   - Migrates all **60 Microsoft Jet 3.5 tables** from `Database/Gls90db.mdb` (`Leagues`, `LeagueRules`, `Courses`, `CoursePar`, `CourseHandicap`, `CourseYards`, `StablefordPts`, `HandicapLookup`, `ZipCodes`, plus all `51` per-league operational tables across Leagues `#9`, `#10`, and `#11`) and all **25 round-robin schedule templates** (`Schedules/4team.csv`..`52team.csv`) into SQLite WAL (`data/gls9.db`).
   - One-click **📂 Import `.mdb`** and **⬇ Download SQLite (`.db`)** in the top bar.

2. **Clean-Room Golf & Match-Play Calculation Engine (`app/golf_engine.py`)**:
   - **Handicap Stroke Allocation (`strokes_on_hole`)**: Allocates handicap strokes per hole using `CourseHandicap` (`Hole01Cap..Hole18Cap`) for both 9-hole and 18-hole leagues.
   - **Equitable Stroke Control (`apply_esc_cap` + `*AdjScores` Sync)**: Supports both Double Bogey Max (`AdjustScores=1`) and USGA Handicap ESC (`AdjustScores=2`), automatically writing adjusted hole scores into `*AdjScores`.
   - **Modified Stableford (`hole_stableford_pts`)**: Computes per-round Gross & Net Stableford points.
   - **Automated Head-to-Head Match Play (`auto_score_week_matches`)**: Reads weekly player pairings from `*MatchSetup` (`ID1..ID16`) or auto-pairs opposing teams from `*Schedule`, awards `IndPtsNet` per hole with `0.5x` tie-splitting on halved holes and halved matches, computes Individual Flight `FieldPts` (`IndPtsNetField` / `IndNetFieldDiff`), updates `*TeamResults`, and rolls up season totals into `*Players.Points` and `*Teams.Points`.

3. **6 Workspaces + On-Course Mobile Caddy + Printable Clubhouse Sheet**:
   - **🏆 1. Standings & Leaderboards**: Team Standings, Individual Player Leaderboard, and ground-truth `LeagueRules` summary.
   - **📝 2. Weekly Scorecard, Matchups & Skins**: Hole-by-Hole scorecard with stroke dots (`•`), `ESC Adj`, `Stableford`, **📱 Mobile Caddy Mode** (`Birdie`/`Par`/`Bogey`/`Double` quick-tap), **⚔️ Head-to-Head Matchup Pairings**, and **Gross & Net Skins Winners**.
   - **👥 3. Roster, Subs & Dues**: Player CRUD (`*Players`), Substitute Roster (`*Subs`), and League Fees ledger (`*LeagueFees`).
   - **📅 4. Schedule & Round-Robin Generator**: Season schedule viewer and 1-click generator from the `25` `GLS9` templates.
   - **⛳ 5. Golf Courses (18/36-Hole Matrix)**: Full Par, Yardage, Rating/Slope, and Stroke Index cards for all 4 courses.
   - **🗄️ 6. Raw `.mdb` Explorer (`61` Tables)**: Live SQLite table inspector replacing `frmDbViewer`.
   - **🖨️ Print Clubhouse Sheet**: Dedicated `@media print` layout for posting weekly standings, matchups, and skins in the clubhouse.

---

## 🚀 Quickstart & Verification

```bash
pip install mypy fastapi uvicorn httpx python-multipart pytest pytest-cov ruff
PYTHONPATH=. pytest -q tests/          # hermetic: runs on a temp copy of data/gls9.db
uvicorn app.main:app --host 0.0.0.0 --port 8104
node tests/spa_smoke.mjs               # optional CHROMIUM_PATH=/usr/bin/chromium
```

Test layout:

| File | Covers |
| --- | --- |
| `tests/test_gls9.py` | End-to-end API flow (plus the original `.mdb` migration flow when `/tmp/GLS9` exists) |
| `tests/test_engine_unit.py` | Stroke allocation, ESC, Stableford, field points, schedule generation |
| `tests/test_match_engine.py` | Head-to-head match play calculations and point distribution |
| `tests/test_ecgc_rules.py` | ECGC custom league rules, PT calculation, and seasonal handicaps |
| `tests/test_ecgc_rules_and_import.py` | ECGC import processing, integration, and historical season boundaries |
| `tests/test_api_hardening.py` | Input validation, 404/422 handling, upload limits, security headers, connection hygiene |
| `tests/test_regressions.py` | One test per edge-case bug fixed in the FSA-15 audit |
| `tests/test_spa_browser.py` + `spa_a11y_xss.mjs` | Headless-browser XSS and WCAG 2.2 AA checks (skipped without Node + Playwright). Set `AXE_CORE_PATH=.../axe-core/axe.min.js` to add a full axe-core scan of every tab in all 5 themes. |

## 🔒 Security & Accessibility Notes (FSA-15 audit)

- All API inputs are bounded and validated (hole scores 0–20, ≤18 holes, weeks 1–52, ISO dates, name/email/phone rules). Unknown leagues or players return 404 and never write partial rows.
- The SPA renders every server value through an auto-escaping `html` template tag. A strict CSP (`script-src 'self'`), `nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer` are sent on the SPA and API.
- `.mdb` uploads are size-capped (`GLS9_MAX_MDB_BYTES`, 64 MB default) and signature-checked. They are migrated into a scratch DB and swapped in atomically, so a failed import never half-overwrites live data.
- The UI targets WCAG 2.2 AA: skip link, keyboard-operable ARIA tabs, labelled controls, AA contrast in all 5 themes, 320 px reflow, focus not obscured by the sticky header, and reduced-motion support.
- **There is no authentication.** Run the app only on a trusted network: anyone who can reach it can edit data, import a database or download `/api/export/sqlite`, which includes player emails and phone numbers.

---

<!-- AUTO-REPO-INVENTORY:START -->
## Automated Repository Inventory (Auto-Synced)

- **Verification Suite (`pytest`):** `pytest -q` (`>= 5` test modules discovered)
- **Discovered API Endpoints (33):**
  - `GET /favicon.ico` (`app/main.py`)
  - `GET /api/health` (`app/main.py`)
  - `GET /api/leagues` (`app/main.py`)
  - `GET /api/leagues/{lid}/standings` (`app/main.py`)
  - `GET /api/leagues/{lid}/week/{week_num}` (`app/main.py`)
  - `POST /api/leagues/{lid}/week/{week_num}/scores` (`app/main.py`)
  - `POST /api/leagues/{lid}/week/{week_num}/auto-score-matches` (`app/main.py`)
  - `GET /api/leagues/{lid}/week/{week_num}/report` (`app/main.py`)
  - `POST /api/leagues/{lid}/recalculate-handicaps` (`app/main.py`)
  - `GET /api/leagues/{lid}/schedule` (`app/main.py`)
  - `POST /api/leagues/{lid}/schedule/generate` (`app/main.py`)
  - `POST /api/leagues/{lid}/players` (`app/main.py`)
  - `GET /api/courses` (`app/main.py`)
  - `GET /api/tables` (`app/main.py`)
  - `GET /api/tables/{table_name}` (`app/main.py`)
  - `POST /api/import/mdb` (`app/main.py`)
  - `POST /api/import/ecgc` (`app/main.py`)
  - `GET /api/ecgc/seasons` (`app/main.py`)
  - `GET /api/ecgc/standings` (`app/main.py`)
  - `GET /api/ecgc/brackets` (`app/main.py`)
  - `GET /api/ecgc/players` (`app/main.py`)
  - `GET /api/ecgc/players/{player_id}` (`app/main.py`)
  - `GET /api/ecgc/matches` (`app/main.py`)
  - `GET /api/ecgc/matches/{match_id}/breakdown` (`app/main.py`)
  - `GET /api/rules/config/{lid}` (`app/main.py`)
  - `POST /api/rules/config/{lid}` (`app/main.py`)
  - `POST /api/rules/simulate` (`app/main.py`)
  - `GET /api/ecgc/course-analytics` (`app/main.py`)
  - `POST /api/leagues/{lid}/teams/{team_id}` (`app/main.py`)
  - `POST /api/ecgc/leagues/{lid}/week/{week_num}/matchups` (`app/main.py`)
  - `POST /api/ecgc/seasons/rollover` (`app/main.py`)
  - `GET /api/ecgc/blind-40` (`app/main.py`)
  - `GET /api/export/sqlite` (`app/main.py`)
  - `GET /` (`app/main.py`)
<!-- AUTO-REPO-INVENTORY:END -->

## ECGC Rules Engine & Historical Data (Stage-2 QA, AIS-547)

- Source: `/workspace/ecgc-modern/data/ecgc.sqlite` -> `ecgc_*` tables via `POST /api/import/ecgc` (idempotent). Verified lossless: 128 players, 244 teams, 206 events, 1,611 matches, 5,521 rounds, 49,689 hole scores, 698 standings, 11 brackets; 632 memberships = 472 roster + 160 substitute rows.
- Course: Edwards County GC, par `[4,4,4,3,5,5,4,3,4]` (36), hole hcp `[13,1,9,7,11,5,3,15,17]` -> 9-hole ranks `[7,1,5,4,6,3,2,8,9]`.
- Match: 9 holes x 1 pt (tie 0.5); team diff `(A1+A2)-(B1+B2)` strokes on lowest-rank holes; plus-handicaps give strokes back on hardest-to-easiest reverse order (hcp 17, 15, 13...).
- PT per player: net <=35 -> +1, 36 -> 0, >=37 -> -1 (configurable via `/api/rules/config/{lid}`); team total = hole pts + PT1 + PT2; next HCP = HCP - PT.
- Known gap: historical `points_adjustment` is preserved verbatim and disagrees with the engine PT rule on 887/5,521 rounds (mostly net 34/35 recorded as 0). See `docs/ECGC_GAP_ANALYSIS_AND_OVERHAUL_PLAN.md` §6.
