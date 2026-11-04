# Golf League Secretary (:8104) — ECGC Historical Data Import, Gap Analysis & Overhaul Plan

**Organization**: AI Stack Autonomous Multi-Agent Engineering  
**Target Application**: Golf League Secretary Modern Web (`gls-modern-web`, port `:8104`)  
**Subject**: Edwards County Golf Course (Kinsley, KS) Historical League Import (2018–2026) & Rules Engine Overhaul  
**Author**: Forge-AGY (Lead Full-Stack & Backend Engineer)  
**Issue**: `AIS-546` (Stage 1 AGY Squad Build, Trinity Pipeline)

---

## 1. Executive Summary & Domain Context

Edwards County Golf Course (`ECGC`, Kinsley, KS) is a scenic, community-owned 9-hole Par-36 prairie golf course founded in 1963. For over two decades, ECGC has operated two flagship competitive league programs:
1. **Men's Twilight League**: 9-hole 2-person team flighted match play held on Wednesday evenings (April through August).
2. **Women's Tuesday Evening League**: 9-hole 2-player scramble and match play held on Tuesday evenings.

Historically, golf league scoring software—represented by legacy solutions like GolfSoft's Golf League Secretary (`GLS90.exe` / Jet 3.5 `Gls90db.mdb`) and online publishing portals like Tournascore—operated under disconnected assumptions. Legacy GLS90 was architected around individual USGA handicap formulas, rigid 18-hole or 4-person formats, and single-season isolated `.mdb` files. In contrast, ECGC league play operates under a distinctive, highly dynamic set of traditional local league rules:
- **9-Hole 2-Person Team Match Play** with differential team handicap stroke allocation.
- **Per-Player Net vs. Par Bonus/Penalty (`PT`: `+1`, `0`, `-1`)** added directly to weekly team match points.
- **Automatic Weekly Handicap Progression** (`HCP_next = HCP_prev - PT`).
- **Plus-Handicap Golfer Stroke Allocation** where scratch/plus golfers give strokes back on the easiest hole handicap ranks.
- **Split-Season First Half / Second Half Points Races** culminating in 4-round single-elimination **Playoff Brackets**.

This document outlines the systematic software and domain gap analysis between legacy GLS90 and ECGC league operations, details the verified data reconciliation preview of all 2018–2026 historical records, and establishes the complete technical blueprint for the importer, rules engine, and 6-workspace UI overhaul.

---

## 2. Software & Domain Gap Analysis

| Feature / Domain Area | Legacy GLS90 (`.mdb` / Clean-Room V1) | ECGC Historical & Modern Operations | Severity / Impact | Modernization Strategy in V2 |
| :--- | :--- | :--- | :--- | :--- |
| **Match Play Format** | Individual 1v1 match play or 4-person stroke play (`TeamPtsNetMatch=8`, `IndPtsNet=1`). | 2-Person Team combined match play: Team A combined gross vs. Team B combined gross per hole with differential handicap strokes (`diff = (HCP_A1 + HCP_A2) - (HCP_B1 + HCP_B2)`). | **Critical** (Rules Mismatch) | Implement `score_ecgc_2person_match` in `app/match_engine.py` calculating 9 hole points (`1.0` win, `0.5` tie, `9.0` total). |
| **Weekly Net Bonus/Penalty (`PT`)** | No concept of per-player net-versus-par bonus or penalty points contributing to team total. | Each player whose net score is `< 36` earns `+1`, `= 36` earns `0`, and `> 36` earns `-1`. Both teammates can earn up to `+2` or `-2` extra points for their team. | **Critical** (Scoring Inaccuracy) | Add per-player `PT` calculation, configurable thresholds in `league_rules_config`, and weekly team total formula `PTS = Hole_Pts + PT_1 + PT_2`. |
| **Handicap Progression** | Complex USGA / custom average of best X of last Y scores multiplied by `PercentHandicap` (90%–100%). | Fast-moving, weekly responsive rule: `HCP_next = HCP_prev - PT`. Players who shoot under net par drop 1 stroke; over net par gain 1 stroke. | **High** (Handicap Drift) | Implement automatic ECGC weekly handicap progression alongside legacy USGA recalculation. |
| **Plus-Handicap Support** | `strokes_on_hole` clamped `max(0, hcp)`, treating plus-handicap golfers (`-1.0` to `-10.0`) as scratch (`0`). | Plus-handicap golfers give strokes back to the course on the easiest holes (`Hole 9 [17], Hole 8 [15], Hole 1 [13]...`). | **Critical** (Competitive Distortion) | Overhaul `strokes_on_hole` and `strokes_per_hole` to assign negative strokes (`-1`, `-2`) based on reverse hole handicap ranking. |
| **Substitute Player Management** | Substitutes stored in isolated `*Subs` / `*SubResults` tables, often requiring manual roster overrides. | Substitutes seamlessly partner in weekly matchups. Sub gross and PT count for team points, but canonical team roster remains pristine. | **Medium** (Roster Integrity) | Tag substitute rounds with `is_sub=True` and `sub_name`, crediting canonical `team_id` without corrupting season roster. |
| **Split-Season & Playoffs** | Fixed columns in `*Teams` (`1stHalfPts`, `2ndHalfPts`, `FinalPts`) with no bracket structures or tournament trees. | Split-season halves (Weeks 1–8, Weeks 9–16), combined standings, and 11 multi-round Playoff Brackets (2019–2026) with Championship crowns. | **High** (User Experience) | Create `ecgc_standings` and `ecgc_brackets` tables, interactive bracket viewer, and PDF archive viewer. |
| **Multi-Year Career Analytics** | Single-season isolated MDB database files; player identity disconnected between years. | 128 canonical players across 9 seasons (2018–2026) with unified career averages, multi-year scoring history, and handicap progression. | **Medium** (Historical Depth) | Implement `ecgc_players` canonical registry with alias mapping and Career Player Profile Drawer. |
| **Course & Tee Configuration** | Courses stored in flat 36-column tables (`CoursePar`, `CourseHandicap`, `CourseYards`), missing 9-hole tee definitions. | Official 9-hole Par-36 layout with Blue (`3,033 yds 34.4/113`), White (`2,960 yds 34.0/111`), and Red (`2,550 yds 34.5/112`) tees. | **High** (Course Fidelity) | Seed Course ID 5 into `Courses`, `CoursePar`, `CourseHandicap`, `CourseYards`, and create `CourseTees` table. |

---

## 3. Data Reconciliation Preview & Verification

The historical data foundation is sourced from `/workspace/ecgc-modern/data/ecgc.sqlite` (derived from 255 verified Tournascore HTML pages) and `/workspace/ecgc-modern/public/assets/brackets/brackets.json` (11 official bracket artifacts).

### 3.1 Reconciliation Metrics

| Entity | Authoritative Source (`ecgc.sqlite` / `ecgc_leagues.*`) | Target (`gls9.db` on `:8104`) | Exact Count | Verification & Integrity Notes |
| :--- | :--- | :--- | ---: | :--- |
| **Course** | Edwards County Golf Course (Kinsley, KS) | `Courses` (`CourseID=5`) + `CourseTees` | **1 Course / 3 Tees** | Blue `3,033 yds 34.4/113`, White `2,960 yds 34.0/111`, Red `2,550 yds 34.5/112`. |
| **Canonical Players** | `league_players` deduplicated across 9 years | `ecgc_players` + `<lid>Players` | **128** | Canonicalized via `CANONICAL_PLAYER_ALIASES` to resolve name variations (nicknames, middle initials). |
| **Season Teams** | `league_teams` (2-person teams) | `ecgc_teams` + `<lid>Teams` | **244** | Preserves all two-person team pairings across all historical seasons and divisions. |
| **Team Memberships** | `league_team_members` + played rounds | `ecgc_team_members` + `<lid>Players` | **633** | 472 permanent roster assignments + 161 substitute appearances (632 unique ID pairs + 1 sub alias). |
| **Weekly / Playoff Events** | `league_events` (regular + playoff) | `ecgc_events` + `<lid>Schedule` | **206** | 160 regular season weeks + 46 playoff/tournament rounds across 2019–2026. |
| **Season-Divisions** | 9 seasons (2018–2026) × 2 divisions | `Leagues` (`LeagueID 20181..20262`) + `ecgc_seasons` | **18** | Men's Twilight League and Women's League (2018 tournament-only baseline + 2019–2026 active leagues). |
| **Head-to-Head Matches** | `league_matches` (team-vs-team) | `ecgc_matches` + `<lid>MatchSetup` | **1,611** | Complete record of all weekly team-vs-team matches with recorded points and outcomes. |
| **Player Rounds Played** | `league_rounds` (9-hole rounds) | `ecgc_rounds` + `<lid>PlayerResults` | **5,521** | Strictly genuine played rounds (zero synthetic unplayed `-36` rows). |
| **Hole-by-Hole Scores** | `league_hole_scores` (#1..#9) | `ecgc_hole_scores` + `<lid>PlayerResults` | **49,689** | Exactly 5,521 rounds × 9 holes = 49,689 hole scores (#1 through #9). |
| **Split Standings Rows** | `league_standings` (First, Second, Final) | `ecgc_standings` + `<lid>Teams` | **698** | First Half, Second Half, and Final Combined standings records across all seasons. |
| **Official Playoff Brackets** | `brackets.json` + PDF artifacts | `ecgc_brackets` | **11** | 11 tournament brackets (2019–2026) with championship and runner-up crowns. |

### 3.2 Canonical Course Specification: Edwards County Golf Course

- **Location**: 1044 O Rd, Kinsley, KS 67547 (Est. 1963)
- **Holes**: 9 Holes, Par 36
- **Par Layout**: `[4, 4, 4, 3, 5, 5, 4, 3, 4]` (Total Par: 36)
- **Hole Handicaps (Stroke Allocation Indices)**: `[13, 1, 9, 7, 11, 5, 3, 15, 17]`
- **Hole Handicap Rank Order (Hardest to Easiest)**:
  1. Hole 2 (Stroke Index 1)
  2. Hole 7 (Stroke Index 3)
  3. Hole 6 (Stroke Index 5)
  4. Hole 4 (Stroke Index 7)
  5. Hole 3 (Stroke Index 9)
  6. Hole 5 (Stroke Index 11)
  7. Hole 1 (Stroke Index 13)
  8. Hole 8 (Stroke Index 15)
  9. Hole 9 (Stroke Index 17)
- **Course Tees**:
  - **Blue (Championship)**: 3,033 yards, USGA Rating 34.4, Slope 113
  - **White (Regular / Men's)**: 2,960 yards, USGA Rating 34.0, Slope 111
  - **Red (Forward / Women's)**: 2,550 yards, USGA Rating 34.5, Slope 112

---

## 4. Rules & Scoring Engine Architecture

### 4.1 Plus-Handicap Stroke Allocation Algorithm

For a golfer with a plus handicap (represented numerically as a negative number, e.g., $H = -2.0$ for $+2$):
1. Compute integer handicap: $h = \text{round\_half\_up}(H)$. If $h < 0$, the golfer gives strokes back to the course.
2. Magnitude: $|h|$, base strokes given back per hole: $b = -(|h| // N)$, remainder: $r = |h| \pmod N$.
3. Allocate the remainder strokes on the **easiest holes**. In a 9-hole ranking where $1$ is hardest and $9$ is easiest, holes with $\text{rank} \ge (N - r + 1)$ receive an additional $-1$ stroke.
4. For ECGC, remainder strokes are deducted in order:
   - 1st easiest: Hole 9 (cap 17, rank 9)
   - 2nd easiest: Hole 8 (cap 15, rank 8)
   - 3rd easiest: Hole 1 (cap 13, rank 7)
   - 4th easiest: Hole 5 (cap 11, rank 6)
   - ...

### 4.2 2-Person Team Match Play & Differential Strokes

1. Calculate combined team handicaps:
   $$\text{Team\_Hcp}_A = \text{Hcp}_{A1} + \text{Hcp}_{A2}, \quad \text{Team\_Hcp}_B = \text{Hcp}_{B1} + \text{Hcp}_{B2}$$
2. Calculate differential:
   $$\Delta = \text{Team\_Hcp}_A - \text{Team\_Hcp}_B$$
   - If $\Delta > 0$, Team A receives $\text{round}(\Delta)$ strokes against Team B.
   - If $\Delta < 0$, Team B receives $\text{round}(|\Delta|)$ strokes against Team A.
   - If $\Delta = 0$, scratch matchup (no differential strokes).
3. Distribute differential strokes by hole handicap rank ($[7, 1, 5, 4, 6, 3, 2, 8, 9]$).
4. On each hole $h \in \{1 \dots 9\}$:
   $$\text{Gross}_A = \text{Gross}_{A1} + \text{Gross}_{A2}, \quad \text{Gross}_B = \text{Gross}_{B1} + \text{Gross}_{B2}$$
   $$\text{Net}_A = \text{Gross}_A - \text{DiffStrokes}_A(h), \quad \text{Net}_B = \text{Gross}_B - \text{DiffStrokes}_B(h)$$
   - $\text{Net}_A < \text{Net}_B \implies$ Team A wins hole (1.0 pt), Team B (0.0 pt).
   - $\text{Net}_B < \text{Net}_A \implies$ Team B wins hole (1.0 pt), Team A (0.0 pt).
   - $\text{Net}_A = \text{Net}_B \implies$ Halved hole (0.5 pt each).
   - Total hole points across 9 holes: $9.0$ points.

### 4.3 Per-Player Net Bonus / Penalty (`PT`)

For each player $p$:
$$\text{Net}_p = \text{Gross}_p - \text{round\_half\_up}(\text{Hcp}_p)$$
Using configurable thresholds in `league_rules_config` (defaults: `bonus <= 35`, `even == 36`, `penalty >= 37`):
$$\text{PT}_p = \begin{cases} +1 & \text{if } \text{Net}_p \le 35 \\ 0 & \text{if } \text{Net}_p = 36 \\ -1 & \text{if } \text{Net}_p \ge 37 \end{cases}$$

Weekly Team Points:
$$\text{Total\_Points}_{\text{Team}} = \text{Hole\_Points}_{\text{Team}} + \text{PT}_{\text{Player1}} + \text{PT}_{\text{Player2}}$$

### 4.4 Automatic Weekly Handicap Progression

$$\text{Hcp}_{p, \text{next}} = \text{Hcp}_{p, \text{current}} - \text{PT}_p$$
- Shooting below net par drops handicap by 1 (harder).
- Shooting above net par increases handicap by 1 (easier).
- Shooting even par leaves handicap unchanged.

---

## 5. Implementation Roadmap & Milestones

1. **Step 1: Gap Analysis & Overhaul Plan Documentation** (Completed in this document).
2. **Step 2: ECGC Historical Importer (`app/ecgc_importer.py` & API)**:
   - Seed Course 5 and `CourseTees`.
   - Seed normalized ECGC tables (`ecgc_seasons`, `ecgc_players`, `ecgc_teams`, `ecgc_events`, `ecgc_matches`, `ecgc_rounds`, `ecgc_hole_scores`, `ecgc_standings`, `ecgc_brackets`, `league_rules_config`).
   - Populate native GLS9 tables for leagues `20181` through `20262`.
   - Auto-seed on startup and set default active league to `20261` (2026 ECGC Men's Twilight League).
3. **Step 3: Scoring & Rules Engine Overhaul (`app/golf_engine.py`, `app/match_engine.py`, `app/main.py`)**:
   - Plus-handicap stroke allocation on easiest holes.
   - 2-person team match play evaluator and `PT` net bonus/penalty calculator.
   - Rules configuration API and interactive simulation endpoint.
4. **Step 4: 6-Workspace UI Upgrade (`index.html`, `app.js`, `styles.css`)**:
   - Multi-season & division filter bar.
   - Split standings & interactive bracket drawer.
   - Matchup breakdown modal with 9.0 hole pts + PT columns.
   - Interactive rules simulator & career player profile drawer.
5. **Step 5: Verification & Quality Assurance**:
   - Comprehensive test suite validating exact reconciliation counts, plus-handicaps, 2-person match points, and API endpoints.
   - Live regression testing on `:8104`.

---

## 6. Stage-2 Independent Audit Results (Sentinel, AIS-547, 2026-11-03)

- Row-level set diff (all shared columns) source vs target: 0 missing rows in every entity; only extras are 160 `sub_or_alt` memberships, each backed by a played round. **Correction to §3.1: memberships = 632 (472 + 160), not 633.**
- Integrity: 0 orphans; 0 rounds with gross != SUM(holes); 0 with net != gross - hcp; re-import idempotent.
- Engine math verified (diff strokes, PT +1/0/-1, +2 for two 34-net partners, plus-hcp give-back on holes #9/#8/#1, SUB name preservation, HCP_next = HCP - PT). pytest 190 passed / 1 skipped.
- **Open rules question:** recorded PT disagrees with the spec on 887 rounds (16.1%) — net 34/35 recorded 0 in 797/1,059 cases. Engine follows the spec; history is preserved, not recomputed. Owner to confirm whether the historical bonus threshold was <=33.
- UI: 0 axe WCAG 2.2 AA violations and 0px overflow at 1440/768/375; one console error (favicon 404); mojibake `???` / `??` in toast and league card.
- Hardening backlog: `POST /api/rules/config/{lid}` accepts non-existent leagues and 500s on bad types; `/api/rules/simulate` 500s on malformed input.
