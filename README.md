# Golf League Secretary — Modern Web Edition (`gls-modern-web`, `:8104`)

Clean-room modern web replacement of **GolfSoft Golf League Secretary v9.954 (`GLS9`)**, reconstructed from the `:8103` **REA Reverse-Engineering Studio** dossier (`/workspace/knowledge-base/gls9-golfsoft-bundle/dossier.md`).

Replaces the 1990s 32-bit Visual Basic 6.0 executable (`Gls90.exe` + `SPR32X60.ocx` FarPoint Spread ActiveX grids + `Gls90db.mdb` Microsoft Jet 3.5 database) with a zero-dependency **FastAPI + SQLite WAL + 6-Workspace, 5-Theme Web Studio**.

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
PYTHONPATH=. pytest -q tests/
uvicorn app.main:app --host 0.0.0.0 --port 8104
CHROMIUM_PATH=/usr/bin/chromium node tests/spa_smoke.mjs
```
