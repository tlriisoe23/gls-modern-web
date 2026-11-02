"use strict";

const state = {
  leagues: [],
  activeLeagueId: 10,
  standings: null,
  activeWeek: 1,
  scorecard: null,
  courses: [],
  tables: [],
  handlersBound: false,
};

// ---------------------------------------------------------------------------
// XSS-safe HTML templating
//
// Every value interpolated into an `html` template is HTML-escaped unless it is
// itself the output of `html` (a SafeHtml fragment). Arrays are joined after each
// element is escaped. All data coming from the API (player names, team names,
// imported .mdb cells, ...) is untrusted and must only reach innerHTML via `html`.
// ---------------------------------------------------------------------------
class SafeHtml {
  constructor(str) {
    this.str = str;
  }
  toString() {
    return this.str;
  }
}

const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" };

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/[&<>"'`]/g, (ch) => HTML_ESCAPES[ch]);
}

function toSafe(value) {
  if (value instanceof SafeHtml) return value.str;
  if (Array.isArray(value)) return value.map(toSafe).join("");
  return escapeHtml(value);
}

function html(strings, ...values) {
  let out = strings[0];
  for (let i = 0; i < values.length; i++) {
    out += toSafe(values[i]) + strings[i + 1];
  }
  return new SafeHtml(out);
}

function setHtml(el, fragment) {
  if (!el) return;
  if (!(fragment instanceof SafeHtml)) {
    throw new TypeError("setHtml() only accepts html`` fragments");
  }
  el.innerHTML = fragment.str;
}

// ---------------------------------------------------------------------------
// Notifications & API
// ---------------------------------------------------------------------------
let toastTimer = null;
function showToast(msg, { error = false } = {}) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.toggle("error", error);
  el.classList.add("show");
  if (error) {
    // Errors are announced assertively (role="alert") for screen-reader users.
    const alertEl = document.getElementById("toastAlert");
    if (alertEl) alertEl.textContent = msg;
  }
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), error ? 8000 : 3200);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        detail = body.detail
          .map((d) => `${(d.loc || []).filter((x) => x !== "body").join(".")}: ${d.msg}`)
          .join("; ");
      }
    } catch (_) {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json();
}

/** Wrap an async event handler so failures surface to the user instead of failing silently. */
function guarded(fn) {
  return async (...args) => {
    try {
      await fn(...args);
    } catch (err) {
      showToast(`Error: ${err.message || err}`, { error: true });
    }
  };
}

function fmtMoney(v) {
  const n = Number(v || 0);
  return "$" + (Number.isFinite(n) ? n : 0).toFixed(2);
}

function fmtNum(v, d = 1) {
  const n = Number(v || 0);
  if (!Number.isFinite(n)) return "0";
  return Number.isInteger(n) ? String(n) : n.toFixed(d);
}

/**
 * WCAG 2.1.1: horizontally scrollable table wrappers must be reachable by keyboard so
 * their overflow can be scrolled with arrow keys. Each becomes a named, focusable region.
 */
function makeScrollRegionsFocusable(root = document) {
  root.querySelectorAll(".table-wrap").forEach((wrap) => {
    if (wrap.hasAttribute("tabindex")) return;
    const caption = wrap.querySelector("caption")?.textContent?.trim();
    wrap.setAttribute("tabindex", "0");
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", caption ? `${caption} (scrollable)` : "Scrollable table");
  });
}

// ---------------------------------------------------------------------------
// Tabs (WAI-ARIA Authoring Practices: automatic activation, roving tabindex)
// ---------------------------------------------------------------------------
function activateTab(btn, { focus = false } = {}) {
  const tabs = Array.from(document.querySelectorAll(".tab-btn"));
  tabs.forEach((b) => {
    const selected = b === btn;
    b.classList.toggle("active", selected);
    b.setAttribute("aria-selected", selected ? "true" : "false");
    b.setAttribute("tabindex", selected ? "0" : "-1");
    const pane = document.getElementById(`tab-${b.dataset.tab}`);
    if (pane) pane.classList.toggle("hidden", !selected);
  });
  if (focus) btn.focus();
}

function setupTabs() {
  const tabs = Array.from(document.querySelectorAll(".tab-btn"));
  tabs.forEach((btn, idx) => {
    btn.addEventListener("click", () => activateTab(btn));
    btn.addEventListener("keydown", (e) => {
      let next = null;
      if (e.key === "ArrowRight") next = tabs[(idx + 1) % tabs.length];
      else if (e.key === "ArrowLeft") next = tabs[(idx - 1 + tabs.length) % tabs.length];
      else if (e.key === "Home") next = tabs[0];
      else if (e.key === "End") next = tabs[tabs.length - 1];
      if (next) {
        e.preventDefault();
        activateTab(next, { focus: true });
      }
    });
  });
}

// ---------------------------------------------------------------------------
// App bootstrap
// ---------------------------------------------------------------------------
async function loadLeagues() {
  const lgData = await api("/api/leagues");
  state.leagues = lgData.leagues || [];
  const lgSel = document.getElementById("leagueSelect");
  setHtml(
    lgSel,
    html`${state.leagues.map(
      (l) =>
        html`<option value="${l.LeagueID}">League #${l.LeagueID}: ${l.LeagueName} (${l.LeagueHoles}H · ${l.player_count} Players)</option>`
    )}`
  );
  if (state.leagues.length > 0) {
    const stillThere = state.leagues.some((l) => Number(l.LeagueID) === state.activeLeagueId);
    const has10 = state.leagues.some((l) => Number(l.LeagueID) === 10);
    if (!stillThere) state.activeLeagueId = has10 ? 10 : Number(state.leagues[0].LeagueID);
    lgSel.value = String(state.activeLeagueId);
  }
}

function bindStaticHandlers() {
  // Static controls are bound exactly once; re-running initApp() (e.g. after an
  // .mdb import) must not stack duplicate listeners.
  if (state.handlersBound) return;
  state.handlersBound = true;

  const themeSel = document.getElementById("themeSelect");
  themeSel.addEventListener("change", () => {
    document.documentElement.setAttribute("data-theme", themeSel.value);
  });

  setupTabs();

  const lgSel = document.getElementById("leagueSelect");
  lgSel.addEventListener(
    "change",
    guarded(async () => {
      state.activeLeagueId = Number(lgSel.value);
      state.activeWeek = 1;
      await refreshLeagueData();
    })
  );

  document.getElementById("weekSelect").addEventListener(
    "change",
    guarded(async (e) => {
      state.activeWeek = Number(e.target.value);
      await loadWeekScorecard();
    })
  );

  document.getElementById("recalcHcpBtn").addEventListener(
    "click",
    guarded(async () => {
      const res = await api(`/api/leagues/${state.activeLeagueId}/recalculate-handicaps`, { method: "POST" });
      showToast(`Recalculated ESC handicaps for ${res.updated_players} players!`);
      await refreshLeagueData();
    })
  );

  document.getElementById("printSheetBtn").addEventListener("click", () => window.print());

  const caddyBtn = document.getElementById("toggleCaddyBtn");
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const box = document.getElementById("caddyModeBox");
      if (box && !box.classList.contains("hidden")) {
        box.classList.add("hidden");
        caddyBtn.setAttribute("aria-expanded", "false");
        caddyBtn.focus();
      }
    }
  });
  caddyBtn.addEventListener("click", () => {
    const box = document.getElementById("caddyModeBox");
    const nowHidden = box.classList.toggle("hidden");
    caddyBtn.setAttribute("aria-expanded", nowHidden ? "false" : "true");
  });

  document.getElementById("autoScoreMatchesBtn").addEventListener(
    "click",
    guarded(async () => {
      await api(`/api/leagues/${state.activeLeagueId}/week/${state.activeWeek}/auto-score-matches`, { method: "POST" });
      showToast(`Auto-scored Week ${state.activeWeek} Head-to-Head Match Play & Standings!`);
      await refreshLeagueData();
    })
  );

  document.getElementById("mdbUploadInput").addEventListener(
    "change",
    guarded(async (e) => {
      const input = e.target;
      const file = input.files[0];
      if (!file) return;
      try {
        const fd = new FormData();
        fd.append("file", file);
        showToast(`Importing ${file.name}...`);
        const res = await api("/api/import/mdb", { method: "POST", body: fd });
        showToast(`Migrated ${res.migrated_tables} tables from ${file.name}!`);
        await initApp();
      } finally {
        input.value = "";
      }
    })
  );

  const form = document.getElementById("playerForm");
  form.addEventListener(
    "submit",
    guarded(async (e) => {
      e.preventDefault();
      if (!form.checkValidity()) {
        form.reportValidity();
        return;
      }
      const val = (id) => document.getElementById(id).value;
      const payload = {
        PlayerID: val("pfPlayerID") ? Number(val("pfPlayerID")) : null,
        PlayerFirst: val("pfFirst").trim(),
        PlayerLast: val("pfLast").trim(),
        TeamID: Number(val("pfTeam") || 1),
        Handicap: Number(val("pfHcp") || 0),
        Points: Number(val("pfPts") || 0),
        Money: Number(val("pfMoney") || 0),
        EMail: val("pfEmail").trim(),
        HomePhone: val("pfPhone").trim(),
      };
      await api(`/api/leagues/${state.activeLeagueId}/players`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      showToast(`Saved player ${payload.PlayerFirst} ${payload.PlayerLast}`);
      form.reset();
      document.getElementById("pfPlayerID").value = "";
      await refreshLeagueData();
    })
  );

  document.getElementById("genSchedBtn").addEventListener(
    "click",
    guarded(async () => {
      const weeks = Number(document.getElementById("schedWeeksInput").value || 16);
      const start_date = document.getElementById("schedStartInput").value || "2026-05-05";
      const res = await api(`/api/leagues/${state.activeLeagueId}/schedule/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ weeks, start_date }),
      });
      showToast(`Generated ${res.generated_weeks}-week round-robin schedule!`);
      await loadScheduleTab();
    })
  );

  const rawSel = document.getElementById("rawTableSelect");
  rawSel.addEventListener("change", guarded(() => inspectRawTable(rawSel.value)));

  setupCaddyModeHandlers();
  setupScorecardDelegation();
}

async function initApp() {
  bindStaticHandlers();
  makeScrollRegionsFocusable();
  await loadLeagues();
  await refreshLeagueData();
  await loadCoursesTab();
  await loadExplorerTab();
}

function setupCaddyModeHandlers() {
  const holeSel = document.getElementById("caddyHoleSelect");
  holeSel.addEventListener("change", updateCaddyHoleMeta);

  document.querySelectorAll(".caddy-btn[data-rel]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pid = Number(document.getElementById("caddyPlayerSelect").value);
      const hIdx = Number(document.getElementById("caddyHoleSelect").value);
      const rel = Number(btn.dataset.rel);
      const hm = (state.scorecard?.holes_meta || [])[hIdx];
      const par = hm ? hm.par : 4;
      const score = Math.max(1, par + rel);
      const inp = document.querySelector(`tr[data-row-pid="${pid}"] .score-input[data-hidx="${hIdx}"]`);
      if (inp) {
        inp.value = String(score);
        showToast(`Set Hole #${hIdx + 1} to ${score} (Par ${par}) for Golfer #${pid}`);
        const nextIdx = (hIdx + 1) % (state.scorecard?.num_holes || 18);
        document.getElementById("caddyHoleSelect").value = String(nextIdx);
        updateCaddyHoleMeta();
      }
    });
  });

  document.getElementById("caddySaveBtn").addEventListener("click", () => {
    const pid = Number(document.getElementById("caddyPlayerSelect").value);
    const saveBtn = document.querySelector(`.save-score-btn[data-pid="${pid}"]`);
    if (saveBtn) saveBtn.click();
  });
}

function setupScorecardDelegation() {
  // One delegated listener for every row's Save button (rows are re-rendered often).
  const tbody = document.querySelector("#scorecardTable tbody");
  tbody.addEventListener(
    "click",
    guarded(async (e) => {
      const btn = e.target.closest(".save-score-btn");
      if (!btn) return;
      const pid = Number(btn.dataset.pid);
      const tr = btn.closest("tr");
      const inputs = Array.from(tr.querySelectorAll(".score-input"));
      let invalid = false;
      const holes = inputs.map((inp) => {
        const raw = inp.value.trim();
        const n = raw === "" ? 0 : Number(raw);
        const bad = !Number.isInteger(n) || n < 0 || n > 20;
        inp.setAttribute("aria-invalid", bad ? "true" : "false");
        if (bad) invalid = true;
        return bad ? 0 : n;
      });
      if (invalid) {
        showToast("Hole scores must be whole numbers between 0 and 20.", { error: true });
        tr.querySelector('.score-input[aria-invalid="true"]')?.focus();
        return;
      }
      const NumPutts = Number(tr.querySelector(".putts-inp").value || 0);
      const GreensInRegulation = Number(tr.querySelector(".gir-inp").value || 0);
      const IndividualPts = Number(tr.querySelector(".pts-inp").value || 0);
      await api(`/api/leagues/${state.activeLeagueId}/week/${state.activeWeek}/scores`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ PlayerID: pid, holes, NumPutts, GreensInRegulation, IndividualPts }),
      });
      showToast(`Saved Week ${state.activeWeek} scorecard, ESC & Match Play for Player #${pid}!`);
      await refreshLeagueData();
    })
  );
}

function updateCaddyHoleMeta() {
  const hIdx = Number(document.getElementById("caddyHoleSelect").value || 0);
  const hm = (state.scorecard?.holes_meta || [])[hIdx];
  const badge = document.getElementById("caddyHoleMeta");
  if (hm && badge) {
    badge.textContent = `Hole #${hm.hole} · Par ${hm.par} · ${hm.yards} yds · Hcp #${hm.handicap_rank}`;
  }
}

async function refreshLeagueData() {
  const st = await api(`/api/leagues/${state.activeLeagueId}/standings`);
  state.standings = st;
  renderKpiStrip(st);
  renderStandingsTab(st);
  renderRosterTab(st);
  await loadScheduleTab();
  await loadWeekScorecard();
}

function renderKpiStrip(st) {
  const lg = st.league || {};
  const rs = st.rules_summary || {};
  const c = st.course || {};
  const players = st.players || [];
  const totalPrizeMoney = players.reduce((acc, p) => acc + Number(p.Money || 0), 0);
  const avgHcp =
    players.length > 0 ? (players.reduce((a, p) => a + Number(p.Handicap || 0), 0) / players.length).toFixed(1) : "0.0";

  setHtml(
    document.getElementById("kpiStrip"),
    html`
    <div class="kpi-card">
      <div class="kpi-label">Active League</div>
      <div class="kpi-value">#${lg.LeagueID} · ${lg.LeagueHoles || 18} Holes</div>
      <div class="kpi-sub">${lg.LeagueName || ""} (${rs.LeagueDay || ""} @ ${rs.FirstTeeTime || ""})</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Home Course</div>
      <div class="kpi-value">${c.CourseName || "Course"}</div>
      <div class="kpi-sub">Par ${c.total_par || 72} · Rating ${c.CourseRating || 72.0} / Slope ${c.SlopeRating || 113}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Teams &amp; Players</div>
      <div class="kpi-value">${(st.teams || []).length} Teams · ${players.length} Players</div>
      <div class="kpi-sub">${rs.NumManTeams || 2}-Person Teams · ${(st.subs || []).length} Subs</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">League Avg Handicap &amp; ESC</div>
      <div class="kpi-value">${avgHcp} Hcp</div>
      <div class="kpi-sub">${rs.PercentHandicap || 90}% Factor · Max ${rs.MaximumHandicap || 18} · ${rs.AdjustScoresLabel || "ESC"}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Total Prize Purse Awarded</div>
      <div class="kpi-value">${fmtMoney(totalPrizeMoney)}</div>
      <div class="kpi-sub">Divisions: ${(rs.Divisions || []).join(" / ")}</div>
    </div>
  `
  );
}

function renderStandingsTab(st) {
  const teams = st.teams || [];
  const players = st.players || [];
  const rs = st.rules_summary || {};

  document.getElementById("teamMetaBadge").textContent = `${teams.length} Teams`;
  document.getElementById("playerMetaBadge").textContent = `${players.length} Players`;

  setHtml(
    document.querySelector("#teamsTable tbody"),
    html`${teams.map(
      (t, i) => html`
    <tr>
      <td><strong>#${i + 1}</strong></td>
      <td>Team ${t.TeamID}</td>
      <th scope="row"><strong>${t.TeamName || "Team " + t.TeamID}</strong></th>
      <td>${t.Division ?? 1}</td>
      <td class="num">${fmtNum(t.Handicap)}</td>
      <td class="num">${fmtNum(t.PrevPts)}</td>
      <td class="num"><span class="badge">${fmtNum(t.Points)} pts</span></td>
      <td class="num">${fmtMoney(t.Money)}</td>
    </tr>`
    )}`
  );

  setHtml(
    document.querySelector("#playersLeaderTable tbody"),
    html`${players.map(
      (p, i) => html`
    <tr>
      <td><strong>#${i + 1}</strong></td>
      <th scope="row"><strong>${p.PlayerFirst || ""} ${p.PlayerLast || ""}</strong></th>
      <td>Team ${p.TeamID || "-"}</td>
      <td class="num">${fmtNum(p.Handicap)}</td>
      <td class="num">${fmtNum(p.PrevPts)}</td>
      <td class="num"><span class="badge">${fmtNum(p.Points)} pts</span></td>
      <td class="num">${fmtMoney(p.Money)}</td>
    </tr>`
    )}`
  );

  setHtml(
    document.getElementById("leagueRulesSummary"),
    html`
    <div class="kpi-card">
      <div class="kpi-label">Handicap &amp; ESC Policy</div>
      <div class="kpi-value">${rs.PercentHandicap || 90}% Over-Par (Max ${rs.MaximumHandicap || 18})</div>
      <div class="kpi-sub">ESC Cap: ${rs.AdjustScoresLabel || "Double Bogey Max"} · Sub Factor: ${rs.SubPercent || 100}%</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Match Play Points (<code>LeagueRules</code>)</div>
      <div class="kpi-value">${rs.HolePts || 1} Hole / ${rs.IndMatchPts || 2} Match</div>
      <div class="kpi-sub">Team Match Bonus: ${rs.TeamMatchPts || 4} pts · Field Top: ${rs.FieldTopPts || 0} pts</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Season Dues &amp; Fees (<code>*LeagueFees</code>)</div>
      <div class="kpi-value">${fmtMoney(rs.GreenFees)} Green / ${fmtMoney(rs.LeagueFee)} League</div>
      <div class="kpi-sub">Skins: ${fmtMoney(rs.SkinsFee)} · Banquet: ${fmtMoney(rs.BanquetFee)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Tee Times &amp; Divisions</div>
      <div class="kpi-value">${rs.FirstTeeTime || "05:00 PM"} (${rs.MinsBetweenGroups || 9}m)</div>
      <div class="kpi-sub">${(rs.Divisions || []).join(" / ")}</div>
    </div>
  `
  );
}

async function loadWeekScorecard() {
  const sc = await api(`/api/leagues/${state.activeLeagueId}/week/${state.activeWeek}`);
  state.scorecard = sc;
  const holesMeta = sc.holes_meta || [];
  document.getElementById("weekCourseBadge").textContent = `${sc.course?.CourseName || "Course"} · ${sc.num_holes} Holes`;

  // Populate Mobile Caddy selects
  setHtml(
    document.getElementById("caddyPlayerSelect"),
    html`${(sc.scorecards || []).map(
      (c) => html`<option value="${c.PlayerID}">${c.PlayerName} (T${c.TeamID} · Hcp ${fmtNum(c.Handicap)})</option>`
    )}`
  );
  setHtml(
    document.getElementById("caddyHoleSelect"),
    html`${holesMeta.map((h, i) => html`<option value="${i}">Hole #${h.hole} (Par ${h.par})</option>`)}`
  );
  updateCaddyHoleMeta();

  const thead = document.querySelector("#scorecardTable thead");
  const tbody = document.querySelector("#scorecardTable tbody");
  const showBack = sc.num_holes > 9;

  setHtml(
    thead,
    html`
    <tr>
      <th scope="col">Player</th>
      <th scope="col">Team</th>
      <th scope="col" class="num">Hcp</th>
      ${holesMeta.map(
        (h) =>
          html`<th scope="col" class="hole-cell"><abbr title="Hole ${h.hole}">H${h.hole}</abbr><div class="brand-sub">P${h.par}·#${h.handicap_rank}</div></th>`
      )}
      <th scope="col" class="num">Front</th>
      ${showBack ? html`<th scope="col" class="num">Back</th>` : ""}
      <th scope="col" class="num">Gross</th>
      <th scope="col" class="num"><abbr title="Equitable Stroke Control adjusted score">ESC Adj</abbr></th>
      <th scope="col" class="num">Net</th>
      <th scope="col" class="num"><abbr title="Over or under par">+/-</abbr></th>
      <th scope="col" class="num"><abbr title="Modified Stableford net points">Stbl</abbr></th>
      <th scope="col" class="num">Putts</th>
      <th scope="col" class="num"><abbr title="Greens in regulation">GIR</abbr></th>
      <th scope="col" class="num">Pts</th>
      <th scope="col">Save</th>
    </tr>
  `
  );

  setHtml(
    tbody,
    html`${(sc.scorecards || []).map((row) => {
      const name = row.PlayerName || `Player ${row.PlayerID}`;
      const holeInputs = row.holes.map((val, idx) => {
        const strokes = row.strokes_received[idx] || 0;
        const holeNo = holesMeta[idx]?.hole ?? idx + 1;
        const label = `${name}, hole ${holeNo} score${strokes ? `, receives ${strokes} handicap stroke${strokes > 1 ? "s" : ""}` : ""}`;
        return html`<td class="hole-cell">
            <span class="stroke-dots" aria-hidden="true" title="${strokes} handicap stroke(s)">${"•".repeat(strokes)}</span>
            <input type="number" inputmode="numeric" min="0" max="20" step="1" class="score-input" data-pid="${row.PlayerID}" data-hidx="${idx}" value="${val || ""}" placeholder="-" aria-label="${label}" />
          </td>`;
      });

      const overStr = row.Gross > 0 ? (row.OverPar > 0 ? `+${row.OverPar}` : String(row.OverPar)) : "-";
      const adjStr =
        row.AdjGross > 0 ? `${row.AdjGross}${row.ESC_CappedStrokes > 0 ? " (-" + row.ESC_CappedStrokes + ")" : ""}` : "-";
      return html`
        <tr data-row-pid="${row.PlayerID}">
          <th scope="row"><strong>${name}</strong></th>
          <td>T${row.TeamID || "-"}</td>
          <td class="num">${fmtNum(row.Handicap)}</td>
          ${holeInputs}
          <td class="num"><strong>${row.FrontNine || "-"}</strong></td>
          ${showBack ? html`<td class="num"><strong>${row.BackNine || "-"}</strong></td>` : ""}
          <td class="num"><span class="badge">${row.Gross || "-"}</span></td>
          <td class="num">${adjStr}</td>
          <td class="num"><span class="badge gold">${row.Net || "-"}</span></td>
          <td class="num">${overStr}</td>
          <td class="num">${row.Gross > 0 ? row.StablefordNet : "-"}</td>
          <td class="num"><input type="number" min="0" max="100" class="stat-input putts-inp" value="${row.NumPutts || 0}" aria-label="${name}, putts" /></td>
          <td class="num"><input type="number" min="0" max="18" class="stat-input gir-inp" value="${row.GreensInRegulation || 0}" aria-label="${name}, greens in regulation" /></td>
          <td class="num"><input type="number" step="0.5" class="stat-input pts-inp" value="${row.IndividualPts || 0}" aria-label="${name}, individual points" /></td>
          <td><button type="button" class="primary save-score-btn" data-pid="${row.PlayerID}" aria-label="Save scores for ${name}">Save</button></td>
        </tr>
      `;
    })}`
  );

  // Render Head-to-Head Matchup Pairings
  const matchups = sc.matchups || [];
  document.getElementById("matchupsCountBadge").textContent = `${matchups.length} Pairings`;
  setHtml(
    document.getElementById("matchupsBox"),
    matchups.length > 0
      ? html`${matchups.map(
          (m) => html`
        <div class="matchup-card">
          <div class="matchup-row">
            <strong>${m.PlayerA_Name} (T${m.PlayerA_Team} · Hcp ${fmtNum(m.PlayerA_Hcp)})</strong>
            <span class="badge">${m.computed_pts_a} pts (${m.holes_won_a}W)</span>
          </div>
          <div class="matchup-row">
            <strong>${m.PlayerB_Name} (T${m.PlayerB_Team} · Hcp ${fmtNum(m.PlayerB_Hcp)})</strong>
            <span class="badge">${m.computed_pts_b} pts (${m.holes_won_b}W)</span>
          </div>
          <div class="kpi-sub matchup-status">
            <strong>${m.status}</strong> · Halved Holes: ${m.holes_halved} · Net: ${m.PlayerA_Net || "-"} vs ${m.PlayerB_Net || "-"}
          </div>
        </div>`
        )}`
      : html`<div class="brand-sub">Individual Flight mode (Field Points awarded across all golfers).</div>`
  );

  // Render Gross & Net Skins
  const grossSkins = sc.gross_skins || [];
  setHtml(
    document.getElementById("grossSkinsBox"),
    grossSkins.length > 0
      ? html`${grossSkins.map(
          (s) => html`
        <div class="skin-card">
          <div class="kpi-label">Hole #${s.hole} (Par ${s.par})</div>
          <div class="kpi-value">${s.player}</div>
          <div class="kpi-sub">Gross Score: <strong>${s.score}</strong></div>
        </div>`
        )}`
      : html`<div class="brand-sub">No outright Gross Skins on Week ${state.activeWeek} (all low scores tied or no scores entered).</div>`
  );

  const netSkins = sc.net_skins || [];
  setHtml(
    document.getElementById("netSkinsBox"),
    netSkins.length > 0
      ? html`${netSkins.map(
          (s) => html`
        <div class="skin-card">
          <div class="kpi-label">Hole #${s.hole} (Par ${s.par})</div>
          <div class="kpi-value">${s.player}</div>
          <div class="kpi-sub">Net Score: <strong>${s.net_score}</strong></div>
        </div>`
        )}`
      : html`<div class="brand-sub">No outright Net Skins on Week ${state.activeWeek}.</div>`
  );
}

function renderRosterTab(st) {
  const subs = st.subs || [];
  const fees = st.fees || [];
  const pMap = {};
  (st.players || []).forEach((p) => {
    pMap[p.PlayerID] = `${p.PlayerFirst || ""} ${p.PlayerLast || ""}`.trim();
  });

  setHtml(
    document.querySelector("#subsTable tbody"),
    html`${subs.map(
      (s) => html`
    <tr>
      <td>#${s.SubID}</td>
      <th scope="row"><strong>${s.SubFirst || ""} ${s.SubLast || ""}</strong></th>
      <td class="num">${fmtNum(s.Handicap)}</td>
      <td class="num">${fmtNum(s.Points)}</td>
      <td class="num">${fmtMoney(s.Money)}</td>
      <td>${s.HomePhone || s.WorkPhone || "-"}</td>
    </tr>`
    )}`
  );

  setHtml(
    document.querySelector("#feesTable tbody"),
    html`${fees.map(
      (f) => html`
    <tr>
      <td>#${f.PlayerID}</td>
      <th scope="row"><strong>${pMap[f.PlayerID] || "Player #" + f.PlayerID}</strong></th>
      <td class="num">${fmtMoney(f.GreenFees)}</td>
      <td class="num">${fmtMoney(f.LeagueFee)}</td>
      <td class="num">${fmtMoney(f.SkinsFee)}</td>
      <td class="num">${fmtMoney(f.BanquetFee)}</td>
      <td class="num">${fmtMoney(f.ExtraFee)}</td>
    </tr>`
    )}`
  );
}

async function loadScheduleTab() {
  const data = await api(`/api/leagues/${state.activeLeagueId}/schedule`);
  const sched = data.schedule || [];
  const wkSel = document.getElementById("weekSelect");
  const maxWk = Math.min(52, Math.max(17, sched.length));
  const opts = [];
  for (let w = 1; w <= maxWk; w++) {
    const row = sched.find((r) => Number(r.WeekNum) === w);
    const dtLabel = row?.Date ? String(row.Date).split(" ")[0] : "";
    opts.push(html`<option value="${w}">Week ${w}${dtLabel ? " (" + dtLabel + ")" : ""}</option>`);
  }
  setHtml(wkSel, html`${opts}`);
  wkSel.value = String(state.activeWeek);

  const tbody = document.querySelector("#scheduleTable tbody");
  setHtml(
    tbody,
    html`${sched.map(
      (w) => html`
    <tr>
      <th scope="row"><strong>Week ${w.WeekNum}</strong></th>
      <td>${String(w.Date || "").split(" ")[0]}</td>
      <td>Half ${w.Half || 1}</td>
      <td>${w.Weather || "Clear"}</td>
      <td>${w.Match1Label || ""}</td>
      <td>${w.Match2Label || ""}</td>
      <td><button type="button" class="open-wk-btn" data-wk="${w.WeekNum}" aria-label="Open week ${w.WeekNum} scorecard">Open Scorecard <span aria-hidden="true">→</span></button></td>
    </tr>`
    )}`
  );

  tbody.querySelectorAll(".open-wk-btn").forEach((b) => {
    b.addEventListener(
      "click",
      guarded(async () => {
        state.activeWeek = Number(b.dataset.wk);
        document.getElementById("weekSelect").value = String(state.activeWeek);
        activateTab(document.querySelector('.tab-btn[data-tab="scorecard"]'), { focus: true });
        await loadWeekScorecard();
      })
    );
  });
}

async function loadCoursesTab() {
  const data = await api("/api/courses");
  state.courses = data.courses || [];
  setHtml(
    document.getElementById("coursesContainer"),
    html`${state.courses.map((c) => {
      const sumYards = (arr) => arr.reduce((a, x) => a + Number(x.yards || 0), 0);
      return html`
      <div class="panel">
        <div class="panel-header">
          <div>
            <h2><span aria-hidden="true">⛳</span> ${c.CourseName} (${c.City || ""}, ${c.State || ""})</h2>
            <div class="brand-sub">Course Rating: ${c.CourseRating} · Slope Rating: ${c.SlopeRating} · Front Par ${c.front_par} / Back Par ${c.back_par} (Total Par ${c.total_par})</div>
          </div>
          <span class="badge">Course ID #${c.CourseID}</span>
        </div>
        <div class="table-wrap">
          <table>
            <caption class="sr-only">${c.CourseName} hole-by-hole card</caption>
            <thead>
              <tr><th scope="col">Metric</th>${c.holes.map((h) => html`<th scope="col" class="num">H${h.hole}</th>`)}<th scope="col" class="num">Front 9</th><th scope="col" class="num">Back 9</th><th scope="col" class="num">Total</th></tr>
            </thead>
            <tbody>
              <tr><th scope="row">Par</th>${c.holes.map((h) => html`<td class="num"><strong>${h.par}</strong></td>`)}<td class="num">${c.front_par}</td><td class="num">${c.back_par}</td><td class="num"><strong>${c.total_par}</strong></td></tr>
              <tr><th scope="row">Yards</th>${c.holes.map((h) => html`<td class="num">${h.yards}</td>`)}<td class="num">${sumYards(c.holes.slice(0, 9))}</td><td class="num">${sumYards(c.holes.slice(9, 18))}</td><td class="num">${sumYards(c.holes)}</td></tr>
              <tr><th scope="row">Handicap Stroke Index</th>${c.holes.map((h) => html`<td class="num"><span class="badge gold">#${h.handicap_rank}</span></td>`)}<td class="num">-</td><td class="num">-</td><td class="num">1..18</td></tr>
            </tbody>
          </table>
        </div>
      </div>`;
    })}`
  );
  makeScrollRegionsFocusable(document.getElementById("coursesContainer"));
}

async function loadExplorerTab() {
  const data = await api("/api/tables");
  state.tables = data.tables || [];
  const sel = document.getElementById("rawTableSelect");
  setHtml(sel, html`${state.tables.map((t) => html`<option value="${t.name}">${t.name} (${t.row_count} rows)</option>`)}`);
  document.getElementById("rawTableCountBadge").textContent = `${data.table_count} SQLite Tables`;
  if (state.tables.length > 0) {
    await inspectRawTable(state.tables[0].name);
  }
}

async function inspectRawTable(tableName) {
  const data = await api(`/api/tables/${encodeURIComponent(tableName)}`);
  const rows = data.rows || [];
  const thead = document.querySelector("#rawTableGrid thead");
  const tbody = document.querySelector("#rawTableGrid tbody");
  if (rows.length === 0) {
    setHtml(thead, html`<tr><th scope="col">Empty Table</th></tr>`);
    setHtml(tbody, html`<tr><td class="brand-sub">Table "${tableName}" has 0 rows.</td></tr>`);
    return;
  }
  const cols = Object.keys(rows[0]);
  setHtml(thead, html`<tr>${cols.map((c) => html`<th scope="col">${c}</th>`)}</tr>`);
  setHtml(
    tbody,
    html`${rows.map((r) => html`<tr>${cols.map((c) => html`<td>${r[c] === null || r[c] === undefined ? "" : String(r[c])}</td>`)}</tr>`)}`
  );
}

window.addEventListener(
  "DOMContentLoaded",
  guarded(() => initApp())
);

// Exposed for automated XSS regression tests.
window.__gls = { escapeHtml, html, SafeHtml };
