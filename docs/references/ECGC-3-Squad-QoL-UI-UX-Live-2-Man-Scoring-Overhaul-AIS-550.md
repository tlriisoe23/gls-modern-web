# ECGC 3-Squad QoL, UI/UX & Live 2-Man Scoring Overhaul (AIS-550)

# ECGC 9-Hole League Manager — 3-Squad QoL, UI/UX & Live 2-Man Scoring Overhaul (AIS-550)

## Summary of Implemented Batches (A–D)
- **Batch A (`CLD-01`, `AGY-01`, `CLD-02`, `CLD-03`)**:
  - Restored clean UTF-8 encoding across `app/static/app.js` and `app/static/index.html` (zero `??` mojibake).
  - Rebranded topbar and workspaces around **Edwards County Golf Course — Golf League Secretary (`ECGC 9-Hole Edition`)** in default `slate-light` theme; tucked admin buttons (`Recalculate Handicaps`, `Import .mdb`, `Download SQLite`) into `#adminToolsDrawer`.
  - Consolidated Tab 1 duplicate Team Standings into a single authoritative `#teamsTable` driven by the Split-Season filter bar (`Final`, `1st Half`, `2nd Half`, `Playoff Brackets`).
  - Kept all 18 ECGC seasons (`20181`..`20262`) accessible in `#leagueSelect` and hid legacy GLS9 demo leagues behind `Legacy Samples`.
- **Batch B (`AGY-02`, `CDX-01`, `CDX-02`)**:
  - Streamlined Tab 2 9-hole scorecard (`H1`–`H9`, `Gross`, `ESC Adj`, `Net`, `+/-`, `Extra PT`, `Next Hcp`) and added `#scorecardMatchFilter` (`Grouped by 2-Man Matchup`, `Full Roster`, `Match #1..#11`).
  - Wired `match_engine.score_ecgc_2person_match()` and `compute_ecgc_pt()` into live score saving (`save_player_week_score` and `auto_score_week_matches`) for ECGC leagues (`lid >= 20180`).
  - Backfilled `<lid>Teams` combined partner handicaps (`PlayerA + PlayerB`) and split-season points (`1stHalfPts`, `2ndHalfPts`, `FinalPts`) in `ecgc_importer.py`, and enriched `get_league_standings()` with player `rounds_played`, `gross_avg`, `net_avg`, `best_gross`, and `season_pt` (`+/-`).
- **Batch C (`AGY-03`, `AGY-04`, `AGY-05`)**:
  - Replaced empty `*Subs` and `*LeagueFees` panels on Tab 3 for ECGC leagues with the **2-Man Team Roster & Partner Manager** (`POST /api/leagues/{lid}/teams/{team_id}`) and searchable **128-Golfer ECGC Career Directory (2018–2026)**.
  - Upgraded Tab 4 (`#scheduleTable`) to display all weekly 2-man matchups (`Matches 1–11`) as interactive `.sched-match-pill` buttons.
  - Renamed Tab 5 to `⛳ 5. ECGC Course & Hole Analytics`, added `GET /api/ecgc/course-analytics` (Hole 1–9 scoring averages, toughness rank `#1 Hardest` to `#9 Easiest`, Birdie/Par/Bogey distribution), and hid legacy 18H demo courses behind `#toggleLegacyCoursesBtn`.
- **Batch D (`CLD-04`, `CDX-03`)**:
  - Added `POST /api/ecgc/leagues/{lid}/week/{week_num}/matchups` (`#weekPairingsEditorBox`) and `POST /api/ecgc/seasons/rollover` (`#rolloverWizardBox`).
  - Added 1-Page Printable ECGC Weekly Clubhouse Sheet (`#clubhouseSheetModal` + `#clubhousePrintSheet` `@media print`).
