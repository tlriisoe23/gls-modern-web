"use strict";

const state = {
  modalFocusReturn: null,
  leagues: [],
  ecgcSeasons: [],
  ecgcPlayers: [],
  activeLeagueId: 20261,
  activeSplit: "final",
  standings: null,
  ecgcStandings: null,
  ecgcBrackets: [],
  activeWeek: 1,
  scorecard: null,
  courses: [],
  tables: [],
  rulesConfig: null,
  courseAnalytics: null,
  courseAnalyticsScope: "season",
  showLegacyCourses: false,
  scorecardViewMode: "grouped",
  careerSearchQuery: "",
  scheduleData: null,
  handlersBound: false,
};

// ---------------------------------------------------------------------------
// XSS-safe HTML templating
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
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle("error", error);
  el.classList.add("show");
  if (error) {
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

function guarded(fn) {
  return async (...args) => {
    const event = args[0] instanceof Event ? args[0] : null;
    let btn = null;
    if (event) {
      if (event.type === "submit" && event.submitter && typeof event.submitter.disabled !== "undefined") {
        btn = event.submitter;
      } else if (event.currentTarget && typeof event.currentTarget.disabled !== "undefined" && event.currentTarget.tagName === "BUTTON") {
        btn = event.currentTarget;
      }
    }
    const wasDisabled = btn ? btn.disabled : false;
    if (btn && !wasDisabled) {
      btn.disabled = true;
      btn.setAttribute("aria-busy", "true");
    }
    try {
      await fn(...args);
    } catch (err) {
      showToast(`Error: ${err.message || err}`, { error: true });
    } finally {
      if (btn && !wasDisabled) {
        btn.disabled = false;
        btn.removeAttribute("aria-busy");
      }
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

function fmtHcp(v) {
  const n = Number(v || 0);
  if (!Number.isFinite(n)) return "0";
  if (n < 0) return `+${fmtNum(Math.abs(n), 1)}`;
  return fmtNum(n, 1);
}

function fmtPtBadge(pt) {
  const n = Number(pt || 0);
  if (n > 0) return html`<span class="badge pt-plus">+${fmtNum(n, 1)} PT</span>`;
  if (n < 0) return html`<span class="badge pt-minus">${fmtNum(n, 1)} PT</span>`;
  return html`<span class="badge pt-even">0 PT</span>`;
}

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
// Tabs
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
// App bootstrap & Season/Division filtering
// ---------------------------------------------------------------------------
function isEcgcLeague(lid) {
  return Number(lid) >= 20180;
}

function syncFilterSelectsFromLeague(lid) {
  const seasonSel = document.getElementById("seasonSelect");
  const divSel = document.getElementById("divisionSelect");
  if (!seasonSel || !divSel) return;
  const n = Number(lid);
  if (n >= 20180) {
    const yr = String(Math.floor(n / 10));
    const dv = n % 10 === 2 ? "womens" : "mens";
    seasonSel.value = yr;
    divSel.value = dv;
  } else {
    seasonSel.value = "legacy";
    divSel.value = "legacy";
  }
}

function renderLeagueSelectOptions() {
  const lgSel = document.getElementById("leagueSelect");
  if (!lgSel) return;
  const seasonVal = document.getElementById("seasonSelect")?.value || "all";
  const divVal = document.getElementById("divisionSelect")?.value || "all";
  const showLegacy = seasonVal === "legacy" || divVal === "legacy" || state.activeLeagueId < 20180;

  let pool = state.leagues.filter((l) => {
    const lid = Number(l.LeagueID);
    if (!showLegacy && lid < 20180) return false;
    if ((seasonVal === "legacy" || divVal === "legacy") && lid >= 20180) return false;
    return true;
  });
  if (pool.length === 0) pool = state.leagues;

  const sorted = [...pool].sort((a, b) => {
    const la = Number(a.LeagueID);
    const lb = Number(b.LeagueID);
    const matchA =
      (seasonVal === "all" || String(Math.floor(la / 10)) === seasonVal) &&
      (divVal === "all" || (divVal === "mens" && la % 10 === 1) || (divVal === "womens" && la % 10 === 2));
    const matchB =
      (seasonVal === "all" || String(Math.floor(lb / 10)) === seasonVal) &&
      (divVal === "all" || (divVal === "mens" && lb % 10 === 1) || (divVal === "womens" && lb % 10 === 2));
    if (matchA !== matchB) return matchA ? -1 : 1;
    return lb - la;
  });

  setHtml(
    lgSel,
    html`${sorted.map(
      (l) =>
        html`<option value="${l.LeagueID}">${l.LeagueName} (${l.LeagueHoles}H · ${l.team_count || 0} Teams · ${l.player_count} Golfers)</option>`
    )}`
  );
  if (sorted.some((l) => Number(l.LeagueID) === state.activeLeagueId)) {
    lgSel.value = String(state.activeLeagueId);
  } else if (sorted.length > 0) {
    state.activeLeagueId = Number(sorted[0].LeagueID);
    lgSel.value = String(state.activeLeagueId);
  }
}

async function loadLeagues() {
  const lgData = await api("/api/leagues");
  state.leagues = lgData.leagues || [];
  try {
    const [secData, plData] = await Promise.all([api("/api/ecgc/seasons"), api("/api/ecgc/players")]);
    state.ecgcSeasons = secData.seasons || [];
    state.ecgcPlayers = plData.players || [];
  } catch (_) {
    state.ecgcSeasons = [];
    state.ecgcPlayers = [];
  }

  if (state.leagues.length > 0) {
    const urlLeague = Number(new URLSearchParams(window.location.search).get("league") || 0);
    if (urlLeague && state.leagues.some((l) => Number(l.LeagueID) === urlLeague)) {
      state.activeLeagueId = urlLeague;
    }
    const stillThere = state.leagues.some((l) => Number(l.LeagueID) === state.activeLeagueId);
    if (!stillThere) {
      const has2026Mens = state.leagues.some((l) => Number(l.LeagueID) === 20261);
      const has10 = state.leagues.some((l) => Number(l.LeagueID) === 10);
      state.activeLeagueId = has2026Mens ? 20261 : has10 ? 10 : Number(state.leagues[0].LeagueID);
    }
    syncFilterSelectsFromLeague(state.activeLeagueId);
    renderLeagueSelectOptions();
  }
}

function bindStaticHandlers() {
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
      syncFilterSelectsFromLeague(state.activeLeagueId);
      await refreshLeagueData();
    })
  );

  const seasonSel = document.getElementById("seasonSelect");
  const divSel = document.getElementById("divisionSelect");
  const handleFilterChange = guarded(async () => {
    const s = seasonSel?.value || "all";
    const d = divSel?.value || "all";
    if (d === "career") {
      if (state.ecgcPlayers.length > 0) {
        await openCareerDrawer(state.ecgcPlayers[0].id);
      }
      return;
    }
    if (s !== "all" && s !== "legacy" && (d === "mens" || d === "womens")) {
      const targetLid = Number(s) * 10 + (d === "womens" ? 2 : 1);
      if (state.leagues.some((l) => Number(l.LeagueID) === targetLid)) {
        state.activeLeagueId = targetLid;
      }
    } else if (s === "legacy" || d === "legacy") {
      if (state.leagues.some((l) => Number(l.LeagueID) === 10)) {
        state.activeLeagueId = 10;
      }
    }
    renderLeagueSelectOptions();
    state.activeWeek = 1;
    await refreshLeagueData();
  });
  if (seasonSel) seasonSel.addEventListener("change", handleFilterChange);
  if (divSel) divSel.addEventListener("change", handleFilterChange);

  const quick2026Btn = document.getElementById("quick2026Btn");
  if (quick2026Btn) {
    quick2026Btn.addEventListener(
      "click",
      guarded(async () => {
        if (state.leagues.some((l) => Number(l.LeagueID) === 20261)) {
          state.activeLeagueId = 20261;
          syncFilterSelectsFromLeague(20261);
          renderLeagueSelectOptions();
          state.activeWeek = 1;
          await refreshLeagueData();
          showToast("Switched to 2026 ECGC Men's League!");
        }
      })
    );
  }

  const runEcgcSync = guarded(async () => {
    showToast("Synchronizing 2018–2026 ECGC historical league data...");
    const res = await api("/api/import/ecgc", { method: "POST" });
    showToast(`Imported ${res.seasons_count} ECGC seasons, ${res.players_count} players & ${res.rounds_count} rounds!`);
    await initApp();
  });
  document.getElementById("quickEcgcSyncBtn")?.addEventListener("click", runEcgcSync);
  document.getElementById("runEcgcImportBtn")?.addEventListener("click", runEcgcSync);

  // Split-season subtabs
  document.querySelectorAll(".subtab-btn").forEach((btn) => {
    btn.addEventListener(
      "click",
      guarded(async () => {
        document.querySelectorAll(".subtab-btn").forEach((b) => b.classList.toggle("active", b === btn));
        state.activeSplit = btn.dataset.split || "final";
        renderSplitStandingsView();
      })
    );
  });

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
      showToast(`Recalculated handicaps for ${res.updated_players} players!`);
      await refreshLeagueData();
    })
  );

  document.getElementById("printSheetBtn").addEventListener(
    "click",
    guarded(async () => {
      await openClubhouseSheetModal();
    })
  );
  document.getElementById("confirmPrintSheetBtn")?.addEventListener("click", () => window.print());
  document.getElementById("closeClubhouseModalBtn")?.addEventListener("click", closeClubhouseSheetModal);
  document.getElementById("clubhouseSheetModal")?.addEventListener("click", (e) => {
    if (e.target.id === "clubhouseSheetModal") closeClubhouseSheetModal();
  });

  const caddyBtn = document.getElementById("toggleCaddyBtn");
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      let handled = false;
      const box = document.getElementById("caddyModeBox");
      if (box && !box.classList.contains("hidden")) {
        box.classList.add("hidden");
        caddyBtn.setAttribute("aria-expanded", "false");
        caddyBtn.focus();
        handled = true;
      }
      const adminDrawer = document.getElementById("adminToolsDrawer");
      if (!handled && adminDrawer && adminDrawer.open) {
        adminDrawer.open = false;
        const summary = adminDrawer.querySelector("summary");
        if (summary) summary.focus();
        handled = true;
      }
      const breakdownModal = document.getElementById("matchupBreakdownModal");
      if (!handled && breakdownModal && !breakdownModal.classList.contains("hidden")) {
          closeBreakdownModal();
          handled = true;
      }
      const careerDrawer = document.getElementById("playerCareerDrawer");
      if (!handled && careerDrawer && !careerDrawer.classList.contains("hidden")) {
          closeCareerDrawer();
          handled = true;
      }
      const clubhouseSheetModal = document.getElementById("clubhouseSheetModal");
      if (!handled && clubhouseSheetModal && !clubhouseSheetModal.classList.contains("hidden")) {
          closeClubhouseSheetModal();
          handled = true;
      }
    }
  });
  caddyBtn.addEventListener("click", () => {
    const box = document.getElementById("caddyModeBox");
    const nowHidden = box.classList.toggle("hidden");
    caddyBtn.setAttribute("aria-expanded", nowHidden ? "false" : "true");
  });

  document.getElementById("closeBreakdownModalBtn")?.addEventListener("click", closeBreakdownModal);
  document.getElementById("matchupBreakdownModal")?.addEventListener("click", (e) => {
    if (e.target.id === "matchupBreakdownModal") closeBreakdownModal();
  });
  document.getElementById("closeCareerDrawerBtn")?.addEventListener("click", closeCareerDrawer);
  document.getElementById("playerCareerDrawer")?.addEventListener("click", (e) => {
    if (e.target.id === "playerCareerDrawer") closeCareerDrawer();
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
      const start = document.getElementById("schedStartInput").value || "2026-05-05";
      const res = await api(`/api/leagues/${state.activeLeagueId}/schedule/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ weeks, start_date: start }),
      });
      showToast(`Generated ${res.generated_weeks}-week Round-Robin schedule!`);
      await loadScheduleTab();
      await loadWeekScorecard();
    })
  );

  document.getElementById("rawTableSelect").addEventListener(
    "change",
    guarded(async (e) => {
      await inspectRawTable(e.target.value);
    })
  );

  // Mobile Caddy controls
  document.getElementById("caddyPlayerSelect").addEventListener("change", updateCaddyHoleMeta);
  document.getElementById("caddyHoleSelect").addEventListener("change", updateCaddyHoleMeta);
  document.querySelectorAll(".caddy-btn[data-rel]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pid = Number(document.getElementById("caddyPlayerSelect").value);
      const hIdx = Number(document.getElementById("caddyHoleSelect").value);
      const hm = state.scorecard?.holes_meta?.[hIdx];
      if (!hm) return;
      const score = Math.max(1, hm.par + Number(btn.dataset.rel));
      const inp = document.querySelector(`.score-input[data-pid="${pid}"][data-hidx="${hIdx}"]`);
      if (inp) inp.value = String(score);
      const hSel = document.getElementById("caddyHoleSelect");
      if (hIdx + 1 < hSel.options.length) hSel.value = String(hIdx + 1);
      updateCaddyHoleMeta();
    });
  });

  document.getElementById("caddySaveBtn").addEventListener(
    "click",
    guarded(async () => {
      const pid = Number(document.getElementById("caddyPlayerSelect").value);
      await savePlayerScoreRow(pid);
    })
  );

  // Rules Configurator & Simulator handlers
  document.getElementById("saveRulesConfigBtn")?.addEventListener(
    "click",
    guarded(async () => {
      const payload = readRulesFormPayload();
      state.rulesConfig = await api(`/api/rules/config/${state.activeLeagueId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      showToast(`Saved ECGC rules configuration for League #${state.activeLeagueId}!`);
      await refreshLeagueData();
    })
  );

  document.getElementById("simPresetCompetitiveBtn")?.addEventListener("click", () => {
    document.getElementById("simTeamAName").value = "Team Alpha (Both Shoot 34 Net -> +2 Bonus)";
    document.getElementById("simA1Name").value = "Spencer Bowman";
    document.getElementById("simA1Hcp").value = "6.0";
    setSimScores("simA1Scores", [4, 4, 5, 3, 5, 5, 5, 4, 5]);
    document.getElementById("simA2Name").value = "Wyatt Heinz";
    document.getElementById("simA2Hcp").value = "9.0";
    setSimScores("simA2Scores", [5, 5, 5, 4, 6, 5, 5, 4, 4]);

    document.getElementById("simTeamBName").value = "Team Beta (Tanner & Dale)";
    document.getElementById("simB1Name").value = "Tanner Riisoe";
    document.getElementById("simB1Hcp").value = "7.0";
    setSimScores("simB1Scores", [5, 5, 4, 4, 5, 6, 5, 4, 5]);
    document.getElementById("simB2Name").value = "Dale Stein";
    document.getElementById("simB2Hcp").value = "11.0";
    setSimScores("simB2Scores", [5, 6, 5, 5, 6, 6, 7, 4, 5]);
    runMatchSimulation();
  });

  document.getElementById("simPresetPlusHcpBtn")?.addEventListener("click", () => {
    document.getElementById("simTeamAName").value = "Team Plus-Handicap (+2 & 8 Hcp)";
    document.getElementById("simA1Name").value = "Scratch Plus Golfer";
    document.getElementById("simA1Hcp").value = "-2.0";
    setSimScores("simA1Scores", [4, 4, 4, 3, 4, 4, 4, 3, 3]);
    document.getElementById("simA2Name").value = "Partner Golfer";
    document.getElementById("simA2Hcp").value = "8.0";
    setSimScores("simA2Scores", [5, 5, 4, 4, 5, 6, 5, 4, 4]);
    runMatchSimulation();
  });

  document.getElementById("runSimulateBtn")?.addEventListener("click", guarded(runMatchSimulation));

  document.getElementById("scorecardMatchFilter")?.addEventListener("change", (e) => {
    state.scorecardViewMode = e.target.value || "grouped";
    if (state.scorecard) renderScorecardTableBody(state.scorecard);
  });

  document.getElementById("careerSearchInput")?.addEventListener("input", (e) => {
    state.careerSearchQuery = (e.target.value || "").trim().toLowerCase();
    if (state.standings) renderRosterTab(state.standings);
  });

  document.getElementById("teTeamId")?.addEventListener("change", (e) => {
    populateTeamEditInputs(Number(e.target.value));
  });

  document.getElementById("teamEditForm")?.addEventListener(
    "submit",
    guarded(async (e) => {
      e.preventDefault();
      const tid = Number(document.getElementById("teTeamId")?.value || 1);
      const tname = (document.getElementById("teTeamName")?.value || "").trim();
      const pa = Number(document.getElementById("tePlayerA")?.value || 0) || null;
      const pb = Number(document.getElementById("tePlayerB")?.value || 0) || null;
      await api(`/api/leagues/${state.activeLeagueId}/teams/${tid}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ TeamName: tname || `Team ${tid}`, PlayerA: pa, PlayerB: pb }),
      });
      showToast(`Updated Team #${tid} (${tname}) partners & combined handicap!`);
      await refreshLeagueData();
    })
  );

  document.getElementById("togglePairingsBuilderBtn")?.addEventListener("click", (e) => {
    const box = document.getElementById("weekPairingsEditorBox");
    if (!box) return;
    box.classList.toggle("hidden");
    e.currentTarget.setAttribute("aria-expanded", String(!box.classList.contains("hidden")));
    if (!box.classList.contains("hidden")) {
      populatePairingsBuilderWeek(Number(document.getElementById("peWeekNum")?.value || state.activeWeek || 1));
    }
  });

  document.getElementById("peWeekNum")?.addEventListener("change", (e) => {
    populatePairingsBuilderWeek(Number(e.target.value || 1));
  });

  document.getElementById("saveWeekPairingsBtn")?.addEventListener(
    "click",
    guarded(async () => {
      const wk = Number(document.getElementById("peWeekNum")?.value || 1);
      const dt = document.getElementById("peDate")?.value || "2026-05-06";
      const half = Number(document.getElementById("peHalf")?.value || (wk <= 8 ? 1 : 2));
      const rows = Array.from(document.querySelectorAll("#peMatchesGrid .pe-match-row"));
      const matches = rows
        .map((r, i) => ({
          match_num: i + 1,
          team1_id: Number(r.querySelector(".pe-t1")?.value || 0),
          team2_id: Number(r.querySelector(".pe-t2")?.value || 0),
        }))
        .filter((m) => m.team1_id > 0 && m.team2_id > 0);
      await api(`/api/ecgc/leagues/${state.activeLeagueId}/week/${wk}/matchups`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: dt, half, weather: "Clear", matches }),
      });
      showToast(`Saved ${matches.length} matchups for Week ${wk}!`);
      await loadScheduleTab();
      await loadWeekScorecard();
    })
  );

  document.getElementById("toggleRolloverWizardBtn")?.addEventListener("click", (e) => {
    const box = document.getElementById("rolloverWizardBox");
    if (box) {
      box.classList.toggle("hidden");
      e.currentTarget.setAttribute("aria-expanded", String(!box.classList.contains("hidden")));
    }
  });

  document.getElementById("runRolloverBtn")?.addEventListener(
    "click",
    guarded(async () => {
      const targetYear = Number(document.getElementById("roTargetYear")?.value || 2027);
      const division = document.getElementById("roDivision")?.value || "mens";
      const weeks = Number(document.getElementById("roWeeks")?.value || 16);
      const startDate = document.getElementById("roStartDate")?.value || `${targetYear}-05-05`;
      const res = await api("/api/ecgc/seasons/rollover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_league_id: state.activeLeagueId,
          target_year: targetYear,
          division,
          weeks,
          start_date: startDate,
        }),
      });
      showToast(`Created ${res.league_name} (#${res.new_league_id}) with ${res.teams_carried_over} teams & ${res.players_carried_over} players!`);
      state.activeLeagueId = Number(res.new_league_id);
      await initApp();
    })
  );
}

function setSimScores(containerId, scores) {
  const inputs = document.querySelectorAll(`#${containerId} input`);
  scores.forEach((s, i) => {
    if (inputs[i]) inputs[i].value = String(s);
  });
}

function readSimScores(containerId) {
  return Array.from(document.querySelectorAll(`#${containerId} input`)).map((el) => Number(el.value || 4));
}

function readRulesFormPayload() {
  return {
    rule_type: document.getElementById("cfgRuleType")?.value || "ecgc_2person_match",
    holes_count: Number(document.getElementById("cfgHolesCount")?.value || 9),
    points_per_hole_win: Number(document.getElementById("cfgWinPts")?.value || 1.0),
    points_per_hole_tie: Number(document.getElementById("cfgTiePts")?.value || 0.5),
    match_hole_points_total: 9.0,
    net_bonus_enabled: 1,
    net_bonus_below_max: Number(document.getElementById("cfgBonusBelow")?.value || 35),
    net_bonus_pts: Number(document.getElementById("cfgBonusPts")?.value || 1.0),
    net_even_min: Number(document.getElementById("cfgEvenMin")?.value || 36),
    net_even_max: Number(document.getElementById("cfgEvenMax")?.value || 36),
    net_even_pts: 0.0,
    net_penalty_above_min: Number(document.getElementById("cfgPenAbove")?.value || 37),
    net_penalty_pts: Number(document.getElementById("cfgPenPts")?.value || -1.0),
    handicap_progression_mode: document.getElementById("cfgHcpMode")?.value || "weekly_pt",
    plus_handicaps_enabled: Number(document.getElementById("cfgPlusHcps")?.value ?? 1),
    unplayed_round_score: -36,
  };
}

async function loadRulesConfigurator() {
  try {
    const cfg = await api(`/api/rules/config/${state.activeLeagueId}`);
    state.rulesConfig = cfg;
    const setVal = (id, v) => {
      const el = document.getElementById(id);
      if (el && v !== undefined && v !== null) el.value = String(v);
    };
    setVal("cfgRuleType", cfg.rule_type || "ecgc_2person_match");
    setVal("cfgHolesCount", cfg.holes_count ?? 9);
    setVal("cfgWinPts", cfg.points_per_hole_win ?? 1.0);
    setVal("cfgTiePts", cfg.points_per_hole_tie ?? 0.5);
    setVal("cfgBonusBelow", cfg.net_bonus_below_max ?? 35);
    setVal("cfgBonusPts", cfg.net_bonus_pts ?? 1.0);
    setVal("cfgEvenMin", cfg.net_even_min ?? 36);
    setVal("cfgEvenMax", cfg.net_even_max ?? 36);
    setVal("cfgPenAbove", cfg.net_penalty_above_min ?? 37);
    setVal("cfgPenPts", cfg.net_penalty_pts ?? -1.0);
    setVal("cfgHcpMode", cfg.handicap_progression_mode || "weekly_pt");
    setVal("cfgPlusHcps", cfg.plus_handicaps_enabled ?? 1);
    const badge = document.getElementById("rulesConfigBadge");
    if (badge) badge.textContent = `League #${state.activeLeagueId} • ${cfg.rule_type || "ecgc_2person_match"}`;
  } catch (_) {
    /* non-fatal */
  }
}

async function runMatchSimulation() {
  const payload = {
    team_a: {
      team_name: document.getElementById("simTeamAName")?.value || "Team A",
      players: [
        {
          name: document.getElementById("simA1Name")?.value || "Player A1",
          handicap: Number(document.getElementById("simA1Hcp")?.value || 0),
          holes: readSimScores("simA1Scores"),
        },
        {
          name: document.getElementById("simA2Name")?.value || "Player A2",
          handicap: Number(document.getElementById("simA2Hcp")?.value || 0),
          holes: readSimScores("simA2Scores"),
        },
      ],
    },
    team_b: {
      team_name: document.getElementById("simTeamBName")?.value || "Team B",
      players: [
        {
          name: document.getElementById("simB1Name")?.value || "Player B1",
          handicap: Number(document.getElementById("simB1Hcp")?.value || 0),
          holes: readSimScores("simB1Scores"),
        },
        {
          name: document.getElementById("simB2Name")?.value || "Player B2",
          handicap: Number(document.getElementById("simB2Hcp")?.value || 0),
          holes: readSimScores("simB2Scores"),
        },
      ],
    },
    rules: readRulesFormPayload(),
  };

  const res = await api("/api/rules/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const box = document.getElementById("simResultsContainer");
  if (!box) return;
  box.classList.remove("hidden");

  const holes = res.holes_breakdown || [];
  const pA = res.team_a?.players || [];
  const pB = res.team_b?.players || [];

  setHtml(
    box,
    html`
      <div class="kpi-strip" style="margin-top:14px;">
        <div class="kpi-card">
          <div class="kpi-label">${res.team_a?.team_name || "Team A"}</div>
          <div class="kpi-value">${fmtNum(res.team_a?.total_points, 1)} Total Pts</div>
          <div class="kpi-sub">${fmtNum(res.team_a?.hole_points, 1)} Hole Pts + ${fmtNum(res.team_a?.bonus_points, 1)} Player Net Bonus (PT)</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">${res.team_b?.team_name || "Team B"}</div>
          <div class="kpi-value">${fmtNum(res.team_b?.total_points, 1)} Total Pts</div>
          <div class="kpi-sub">${fmtNum(res.team_b?.hole_points, 1)} Hole Pts + ${fmtNum(res.team_b?.bonus_points, 1)} Player Net Bonus (PT)</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Matchup Outcome &amp; Handicap Diff</div>
          <div class="kpi-value">${res.winner_label || res.winner || "Completed"}</div>
          <div class="kpi-sub">Team Hcp: ${fmtNum(res.team_a?.team_handicap, 1)} vs ${fmtNum(res.team_b?.team_handicap, 1)} (Diff ${fmtNum(res.handicap_diff, 1)})</div>
        </div>
      </div>

      <div class="grid-2" style="margin-top:12px;">
        <div class="table-wrap">
          <table>
            <caption class="sr-only">Per-player net bonus points and handicap progression</caption>
            <thead>
              <tr>
                <th scope="col">Golfer</th>
                <th scope="col" class="num">Gross</th>
                <th scope="col" class="num">Hcp</th>
                <th scope="col" class="num">Net (vs 36)</th>
                <th scope="col" class="num">Extra Team PT</th>
                <th scope="col" class="num">Next Wk Hcp</th>
              </tr>
            </thead>
            <tbody>
              ${[...pA, ...pB].map(
                (p) => html`
                  <tr>
                    <th scope="row"><strong>${p.name}</strong></th>
                    <td class="num">${p.gross}</td>
                    <td class="num">${fmtHcp(p.handicap)}</td>
                    <td class="num"><strong>${p.net}</strong> (${p.net - 36 >= 0 ? "+" + (p.net - 36) : p.net - 36})</td>
                    <td class="num">${fmtPtBadge(p.pt)}</td>
                    <td class="num">${fmtHcp(p.next_handicap)}</td>
                  </tr>
                `
              )}
            </tbody>
          </table>
        </div>

        <div class="table-wrap">
          <table>
            <caption class="sr-only">Hole-by-hole 2-person team match points</caption>
            <thead>
              <tr>
                <th scope="col">Hole</th>
                <th scope="col" class="num">Par</th>
                <th scope="col" class="num">Rank</th>
                <th scope="col" class="num">Team A Net</th>
                <th scope="col" class="num">Team B Net</th>
                <th scope="col" class="num">Pts (A / B)</th>
              </tr>
            </thead>
            <tbody>
              ${holes.map(
                (h) => html`
                  <tr>
                    <th scope="row">H${h.hole}</th>
                    <td class="num">${h.par}</td>
                    <td class="num">#${h.rank}</td>
                    <td class="num">${h.team_a_gross}${h.team_a_strokes ? " (-" + h.team_a_strokes + ")" : ""} = <strong>${h.team_a_net}</strong></td>
                    <td class="num">${h.team_b_gross}${h.team_b_strokes ? " (-" + h.team_b_strokes + ")" : ""} = <strong>${h.team_b_net}</strong></td>
                    <td class="num"><strong>${h.team_a_pts}</strong> / <strong>${h.team_b_pts}</strong></td>
                  </tr>
                `
              )}
            </tbody>
          </table>
        </div>
      </div>
    `
  );
  makeScrollRegionsFocusable(box);
}

async function initApp() {
  bindStaticHandlers();
  await loadLeagues();
  await refreshLeagueData();
  await loadCoursesTab();
  await loadExplorerTab();
  makeScrollRegionsFocusable();
}

async function refreshLeagueData() {
  const st = await api(`/api/leagues/${state.activeLeagueId}/standings`);
  state.standings = st;

  if (isEcgcLeague(state.activeLeagueId)) {
    const yr = Math.floor(Number(state.activeLeagueId) / 10);
    const slug = Number(state.activeLeagueId) % 10 === 2 ? "womens" : "mens";
    const [ecgcSt, brData] = await Promise.all([
      api(`/api/ecgc/standings?league_id=${state.activeLeagueId}`),
      api(`/api/ecgc/brackets?season_year=${yr}&league_slug=${slug}`),
    ]);
    state.ecgcStandings = ecgcSt;
    state.ecgcBrackets = brData.brackets || [];
  } else {
    state.ecgcStandings = null;
    state.ecgcBrackets = [];
  }

  renderKpiStrip(st);
  renderStandingsTab(st);
  renderSplitStandingsView();
  renderRosterTab(st);
  await loadScheduleTab();
  await loadWeekScorecard();
  await loadRulesConfigurator();
  makeScrollRegionsFocusable();
}

function renderKpiStrip(st) {
  const lg = st.league || {};
  const rs = st.rules_summary || {};
  const c = st.course || {};
  const players = st.players || [];
  const totalPrizeMoney = players.reduce((acc, p) => acc + Number(p.Money || 0), 0);
  const avgHcp =
    players.length > 0 ? (players.reduce((a, p) => a + Number(p.Handicap || 0), 0) / players.length).toFixed(1) : "0.0";

  const ecgcSeason = state.ecgcSeasons.find((s) => Number(s.gls_league_id) === Number(lg.LeagueID));
  const extraCard = ecgcSeason
    ? html`
      <div class="kpi-card">
        <div class="kpi-label">ECGC Scoring &amp; Champion</div>
        <div class="kpi-value">${ecgcSeason.champion_team || "9-Hole 2-Man Match + PT"}</div>
        <div class="kpi-sub">9 Hole Pts + Per-Player Net Bonus (+1 &lt;36 • 0 =36 • -1 &gt;36)</div>
      </div>`
    : html`
      <div class="kpi-card">
        <div class="kpi-label">Total Prize Purse Awarded</div>
        <div class="kpi-value">${fmtMoney(totalPrizeMoney)}</div>
        <div class="kpi-sub">Divisions: ${(rs.Divisions || []).join(" / ")}</div>
      </div>`;

  setHtml(
    document.getElementById("kpiStrip"),
    html`
    <div class="kpi-card">
      <div class="kpi-label">Active League</div>
      <div class="kpi-value">#${lg.LeagueID} • ${lg.LeagueHoles || 9} Holes</div>
      <div class="kpi-sub">${lg.LeagueName || ""} (${rs.LeagueDay || ""} @ ${rs.FirstTeeTime || ""})</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Home Course</div>
      <div class="kpi-value">${c.CourseName || "Edwards County Golf Course"}</div>
      <div class="kpi-sub">${Number(c.NumHoles || lg.LeagueHoles || 9) === 9 ? "9-Hole Course • Par " + (c.front_par || c.total_par || 36) : "18-Hole • Par " + (c.total_par || 72)} • Rating ${c.CourseRating || 34.4} / Slope ${c.SlopeRating || 113}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Teams &amp; Players</div>
      <div class="kpi-value">${(st.teams || []).length} Teams • ${players.length} Players</div>
      <div class="kpi-sub">${rs.NumManTeams || 2}-Person Teams • ${(st.subs || []).length} Subs</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">League Avg Handicap &amp; ESC</div>
      <div class="kpi-value">${avgHcp} Hcp</div>
      <div class="kpi-sub">${rs.PercentHandicap || 90}% Factor • Max ${rs.MaximumHandicap || 18} • ${rs.AdjustScoresLabel || "ESC"}</div>
    </div>
    ${extraCard}
  `
  );
}

function renderSplitStandingsView() {
  const splitBox = document.getElementById("splitStandingsContainer");
  const playBox = document.getElementById("playoffsContainer");
  if (!splitBox || !playBox) return;

  // Consolidated Team Standings (CLD-02): never stack a duplicate 22-team table above #teamsTable
  splitBox.classList.add("hidden");

  if (!isEcgcLeague(state.activeLeagueId)) {
    playBox.classList.add("hidden");
    if (state.standings) renderStandingsTab(state.standings);
    return;
  }

  if (state.activeSplit === "playoffs") {
    playBox.classList.remove("hidden");
    const brs = state.ecgcBrackets || [];
    setHtml(
      playBox,
      brs.length > 0
        ? html`
            <div class="panel">
              <div class="panel-header">
                <h2>🏅 ECGC Official Playoff Brackets (Rounds 1–4)</h2>
                <span class="badge gold">${brs.length} Bracket(s)</span>
              </div>
              <div class="matchups-grid">
                ${brs.map(
                  (b) => html`
                    <div class="matchup-card">
                      <div class="matchup-row">
                        <strong>${b.title} (${b.season_year})</strong>
                        <span class="badge gold">${b.rounds_count || 4} Rounds</span>
                      </div>
                      <div class="brand-sub" style="margin-top:6px;">
                        🏆 <strong>Champion:</strong> ${b.playoff_champion || "TBD"}<br />
                        🥈 <strong>Runner-Up:</strong> ${b.playoff_runner_up || "TBD"}<br />
                        🎖️ <strong>Finalists:</strong> ${b.playoff_finalists || "-"}
                      </div>
                    </div>
                  `
                )}
              </div>
            </div>
          `
        : html`<div class="panel"><div class="brand-sub"><span role="status">No playoff bracket recorded for this season-division.</span></div></div>`
    );
  } else {
    playBox.classList.add("hidden");
  }

  if (state.standings) {
    renderStandingsTab(state.standings);
  }
}

function renderStandingsTab(st) {
  const teams = st.teams || [];
  const players = st.players || [];
  const rs = st.rules_summary || {};
  const isEcgc = isEcgcLeague(state.activeLeagueId);

  const splitLabel =
    state.activeSplit === "first_half"
      ? "🥇 1st Half Team Standings (Weeks 1–8)"
      : state.activeSplit === "second_half"
      ? "🥈 2nd Half Team Standings (Weeks 9–16)"
      : "🏆 ECGC 2-Man Team Standings (Full Season)";

  const teamsTitleEl = document.getElementById("teamsPanelTitle");
  if (teamsTitleEl) {
    teamsTitleEl.textContent = isEcgc ? splitLabel : "Team Standings";
  }
  const playersTitleEl = document.getElementById("playersPanelTitle");
  if (playersTitleEl) {
    playersTitleEl.textContent = isEcgc ? "Individual Golfer & Net PT Leaderboard" : "Individual Player Leaderboard";
  }

  document.getElementById("teamMetaBadge").textContent = `${teams.length} Teams`;
  document.getElementById("playerMetaBadge").textContent = `${players.length} Golfers`;

  const teamsThead = document.querySelector("#teamsTable thead");
  const teamsTbody = document.querySelector("#teamsTable tbody");

  if (isEcgc) {
    setHtml(
      teamsThead,
      html`
        <tr>
          <th scope="col">Rank</th>
          <th scope="col">Team #</th>
          <th scope="col">2-Man Team / Partners</th>
          <th scope="col" class="num">Comb Hcp</th>
          <th scope="col" class="num">1st Half</th>
          <th scope="col" class="num">2nd Half</th>
          <th scope="col" class="num">Total Pts</th>
          <th scope="col" class="num">Gross Avg</th>
          <th scope="col" class="num">Net Avg</th>
          <th scope="col" class="num">GB</th>
        </tr>
      `
    );

    const sortKey =
      state.activeSplit === "first_half"
        ? "1stHalfPts"
        : state.activeSplit === "second_half"
        ? "2ndHalfPts"
        : "Points";

    const sortedTeams = [...teams].sort((a, b) => Number(b[sortKey] || 0) - Number(a[sortKey] || 0));
    const leaderPts = sortedTeams.length > 0 ? Number(sortedTeams[0][sortKey] || 0) : 0;

    setHtml(
      teamsTbody,
      html`${sortedTeams.map((t, i) => {
        const activePts = Number(t[sortKey] || 0);
        const gb = Math.max(0, leaderPts - activePts);
        const partnersSub =
          t.PlayerA_Name || t.PlayerB_Name
            ? `${t.PlayerA_Name || "P1"} (${fmtHcp(t.PlayerA_Hcp)}) · ${t.PlayerB_Name || "P2"} (${fmtHcp(t.PlayerB_Hcp)})`
            : "";
        return html`
          <tr>
            <td><strong>#${i + 1}</strong></td>
            <td>Team ${t.TeamID}</td>
            <th scope="row">
              <strong>${t.TeamName || "Team " + t.TeamID}</strong>
              ${partnersSub ? html`<div class="brand-sub">${partnersSub}</div>` : ""}
            </th>
            <td class="num"><span class="badge">${fmtHcp(t.CombinedHcp ?? t.Handicap)}</span></td>
            <td class="num">${fmtNum(t["1stHalfPts"], 1)}</td>
            <td class="num">${fmtNum(t["2ndHalfPts"], 1)}</td>
            <td class="num"><span class="badge gold">${fmtNum(t.Points, 1)} pts</span></td>
            <td class="num">${t.gross_avg ? fmtNum(t.gross_avg, 1) : "-"}</td>
            <td class="num">${t.net_avg ? fmtNum(t.net_avg, 1) : "-"}</td>
            <td class="num">${gb === 0 ? "-" : fmtNum(gb, 1)}</td>
          </tr>
        `;
      })}`
    );
  } else {
    setHtml(
      teamsThead,
      html`
        <tr>
          <th scope="col">Rank</th>
          <th scope="col">Team ID</th>
          <th scope="col">Team Name</th>
          <th scope="col">Div</th>
          <th scope="col" class="num">Team Hcp</th>
          <th scope="col" class="num">Prev Pts</th>
          <th scope="col" class="num">Total Pts</th>
          <th scope="col" class="num">Money Won</th>
        </tr>
      `
    );
    setHtml(
      teamsTbody,
      html`${teams.map(
        (t, i) => html`
          <tr>
            <td><strong>#${i + 1}</strong></td>
            <td>Team ${t.TeamID}</td>
            <th scope="row"><strong>${t.TeamName || "Team " + t.TeamID}</strong></th>
            <td>${t.Division ?? 1}</td>
            <td class="num">${fmtHcp(t.Handicap)}</td>
            <td class="num">${fmtNum(t.PrevPts)}</td>
            <td class="num"><span class="badge">${fmtNum(t.Points)} pts</span></td>
            <td class="num">${fmtMoney(t.Money)}</td>
          </tr>
        `
      )}`
    );
  }

  const playersThead = document.querySelector("#playersLeaderTable thead");
  const playersTbody = document.querySelector("#playersLeaderTable tbody");

  if (isEcgc) {
    setHtml(
      playersThead,
      html`
        <tr>
          <th scope="col">Rank</th>
          <th scope="col">Golfer</th>
          <th scope="col">Team</th>
          <th scope="col" class="num">Rds</th>
          <th scope="col" class="num">Hcp</th>
          <th scope="col" class="num">Gross Avg</th>
          <th scope="col" class="num">Net Avg</th>
          <th scope="col" class="num">Season PT (+/-)</th>
        </tr>
      `
    );
    const sortedPlayers = [...players].sort((a, b) => {
      const pa = Number(a.season_pt ?? a.Points ?? 0);
      const pb = Number(b.season_pt ?? b.Points ?? 0);
      if (pb !== pa) return pb - pa;
      return Number(a.Handicap || 0) - Number(b.Handicap || 0);
    });

    setHtml(
      playersTbody,
      html`${sortedPlayers.map((p, i) => {
        const fullName = `${p.PlayerFirst || ""} ${p.PlayerLast || ""}`.trim();
        const ptVal = p.season_pt ?? p.Points ?? 0;
        return html`
          <tr>
            <td><strong>#${i + 1}</strong></td>
            <th scope="row">
              <button type="button" class="link-btn career-player-btn" data-pid="${p.PlayerID}">
                <strong>${fullName}</strong> 📊
              </button>
            </th>
            <td>Team ${p.TeamID || "-"}</td>
            <td class="num">${p.rounds_played ?? "-"}</td>
            <td class="num">${fmtHcp(p.Handicap)}</td>
            <td class="num">${p.gross_avg ? fmtNum(p.gross_avg, 1) : "-"}</td>
            <td class="num">${p.net_avg ? fmtNum(p.net_avg, 1) : "-"}</td>
            <td class="num">${fmtPtBadge(ptVal)}</td>
          </tr>
        `;
      })}`
    );
  } else {
    setHtml(
      playersThead,
      html`
        <tr>
          <th scope="col">Rank</th>
          <th scope="col">Player</th>
          <th scope="col">Team</th>
          <th scope="col" class="num">Handicap</th>
          <th scope="col" class="num">Prev Pts</th>
          <th scope="col" class="num">Total Pts</th>
          <th scope="col" class="num">Prize Money</th>
        </tr>
      `
    );
    setHtml(
      playersTbody,
      html`${players.map((p, i) => {
        const fullName = `${p.PlayerFirst || ""} ${p.PlayerLast || ""}`.trim();
        return html`
          <tr>
            <td><strong>#${i + 1}</strong></td>
            <th scope="row"><strong>${fullName}</strong></th>
            <td>Team ${p.TeamID || "-"}</td>
            <td class="num">${fmtHcp(p.Handicap)}</td>
            <td class="num">${fmtNum(p.PrevPts)}</td>
            <td class="num"><span class="badge">${fmtNum(p.Points)} pts</span></td>
            <td class="num">${fmtMoney(p.Money)}</td>
          </tr>
        `;
      })}`
    );
  }

  document.querySelectorAll("#playersLeaderTable .career-player-btn").forEach((btn) => {
    btn.addEventListener(
      "click",
      guarded(async () => {
        await openCareerDrawer(Number(btn.dataset.pid));
      })
    );
  });

  setHtml(
    document.getElementById("leagueRulesSummary"),
    html`
      <div class="kpi-card">
        <div class="kpi-label">Handicap &amp; Progression Policy</div>
        <div class="kpi-value">Weekly PT (HCP = Prev - PT)</div>
        <div class="kpi-sub">Plus-Handicaps Enabled (+1..+10) · 9 Holes (Par 36)</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">9-Hole 2-Man Team Match Play</div>
        <div class="kpi-value">1.0 Hole Win / 0.5 Tie (9.0 Max)</div>
        <div class="kpi-sub">2-Person Combined Gross vs Team Handicap Differential on Holes 1–9</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Per-Player Net Bonus / Penalty (PT)</div>
        <div class="kpi-value">+1 (&lt;36 Net) · 0 (=36) · -1 (&gt;36)</div>
        <div class="kpi-sub">Awarded per player: if both teammates shoot 34 net, team earns +2 bonus pts!</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Tee Times &amp; Divisions</div>
        <div class="kpi-value">${rs.FirstTeeTime || "06:00 PM"} (${rs.MinsBetweenGroups || 10}m)</div>
        <div class="kpi-sub">${(rs.Divisions || []).join(" / ")}</div>
      </div>
    `
  );
}

async function openCareerDrawer(playerId) {
  state.modalFocusReturn = document.activeElement;
  const data = await api(`/api/ecgc/players/${playerId}`);
  const drawer = document.getElementById("playerCareerDrawer");
  const titleEl = document.getElementById("careerDrawerTitle");
  const metaEl = document.getElementById("careerPlayerMeta");
  const bodyEl = document.getElementById("careerDrawerContent");
  if (!drawer || !bodyEl) return;

  const p = data.player || {};
  const seasons = data.season_summary || [];
  const rounds = data.rounds || [];
  if (titleEl) titleEl.textContent = `${p.display_name || "Golfer"} — Career Profile (2018–2026)`;
  if (metaEl)
    metaEl.textContent = `Division: ${(p.primary_division || "mens").toUpperCase()} · ${data.career_seasons || 0} Seasons · ${rounds.length} Recent Rounds Shown`;

  setHtml(
    bodyEl,
    html`
      <div class="panel">
        <div class="panel-header">
          <h3>Season-by-Season Summary</h3>
          <span class="badge gold">${seasons.length} Seasons</span>
        </div>
        <div class="table-wrap">
          <table>
            <caption class="sr-only">Career season summary</caption>
            <thead>
              <tr>
                <th scope="col">Year</th>
                <th scope="col">Division</th>
                <th scope="col">Team</th>
                <th scope="col" class="num">Rounds</th>
                <th scope="col" class="num">Avg Gross</th>
                <th scope="col" class="num">Avg Net</th>
                <th scope="col" class="num">Best Gross</th>
                <th scope="col" class="num">Avg Hcp</th>
                <th scope="col" class="num">Net PT Bonus Sum</th>
              </tr>
            </thead>
            <tbody>
              ${seasons.map(
                (s) => html`
                  <tr>
                    <th scope="row"><strong>${s.season_year}</strong></th>
                    <td>${s.league_slug === "womens" ? "Women's" : "Men's"}</td>
                    <td>${s.team_name || "-"}</td>
                    <td class="num">${s.rounds_played}</td>
                    <td class="num">${fmtNum(s.avg_gross, 1)}</td>
                    <td class="num">${fmtNum(s.avg_net, 1)}</td>
                    <td class="num">${s.best_gross ?? "-"}</td>
                    <td class="num">${fmtHcp(s.avg_handicap)}</td>
                    <td class="num">${fmtPtBadge(s.season_pt_total)}</td>
                  </tr>
                `
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div class="panel" style="margin-top:12px;">
        <div class="panel-header">
          <h3>Recent 9-Hole Rounds &amp; Net Bonus (PT) History</h3>
        </div>
        <div class="table-wrap">
          <table>
            <caption class="sr-only">Recent rounds and net bonus history</caption>
            <thead>
              <tr>
                <th scope="col">Season / Wk</th>
                <th scope="col">Team</th>
                <th scope="col" class="num">Gross</th>
                <th scope="col" class="num">Hcp</th>
                <th scope="col" class="num">Net</th>
                <th scope="col" class="num">O/U</th>
                <th scope="col" class="num">Extra PT</th>
              </tr>
            </thead>
            <tbody>
              ${rounds.map(
                (r) => html`
                  <tr>
                    <th scope="row">${r.season_year} Wk${r.week_number || "-"}</th>
                    <td>${r.team_name || "-"}</td>
                    <td class="num"><strong>${r.gross_total > 0 ? r.gross_total : "DNP"}</strong></td>
                    <td class="num">${fmtHcp(r.handicap)}</td>
                    <td class="num">${r.gross_total > 0 ? r.net_total : "-"}</td>
                    <td class="num">${r.over_under || "-"}</td>
                    <td class="num">${fmtPtBadge(r.points_adjustment)}</td>
                  </tr>
                `
              )}
            </tbody>
          </table>
        </div>
      </div>
    `
  );
  drawer.classList.remove("hidden");
  makeScrollRegionsFocusable(bodyEl);
}

function closeCareerDrawer() {
  document.getElementById("playerCareerDrawer")?.classList.add("hidden");
  if (state.modalFocusReturn) {
    state.modalFocusReturn.focus();
    state.modalFocusReturn = null;
  }
}

async function openBreakdownModal(matchId) {
  state.modalFocusReturn = document.activeElement;
  const data = await api(`/api/ecgc/matches/${matchId}/breakdown`);
  const modal = document.getElementById("matchupBreakdownModal");
  const titleEl = document.getElementById("breakdownModalTitle");
  const contentEl = document.getElementById("matchupBreakdownContent");
  if (!modal || !contentEl) return;

  const m = data.match || {};
  const ta = data.team_a || {};
  const tb = data.team_b || {};
  const holes = data.holes || [];

  if (titleEl) {
    titleEl.textContent = `Match #${m.match_number || ""}: ${ta.name || "Team A"} (${m.team_a_points} pts) vs ${tb.name || "Team B"} (${m.team_b_points} pts)`;
  }

  setHtml(
    contentEl,
    html`
      <div class="kpi-strip">
        <div class="kpi-card">
          <div class="kpi-label">Team A: ${ta.name}</div>
          <div class="kpi-value">Official: ${fmtNum(m.team_a_points, 1)} PTS</div>
          <div class="kpi-sub">9-Hole Match: ${fmtNum(ta.hole_points, 1)} pts + Player PT Bonus: ${fmtNum(ta.pt_bonus_total, 1)} pts</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Team B: ${tb.name}</div>
          <div class="kpi-value">Official: ${fmtNum(m.team_b_points, 1)} PTS</div>
          <div class="kpi-sub">9-Hole Match: ${fmtNum(tb.hole_points, 1)} pts + Player PT Bonus: ${fmtNum(tb.pt_bonus_total, 1)} pts</div>
        </div>
      </div>

      <div class="table-wrap" style="margin-top:12px;">
        <table>
          <caption class="sr-only">Player rounds and net handicap bonus points</caption>
          <thead>
            <tr>
              <th scope="col">Team</th>
              <th scope="col">Golfer</th>
              <th scope="col" class="num">Gross</th>
              <th scope="col" class="num">Hcp</th>
              <th scope="col" class="num">Net</th>
              <th scope="col" class="num">Extra PT (+1/0/-1)</th>
            </tr>
          </thead>
          <tbody>
            ${[...(ta.rounds || []), ...(tb.rounds || [])].map(
              (r) => html`
                <tr>
                  <td>${r.team_name || "-"}</td>
                  <th scope="row"><strong>${r.player_name}</strong></th>
                  <td class="num">${r.gross_total > 0 ? r.gross_total : "DNP (-36)"}</td>
                  <td class="num">${fmtHcp(r.handicap)}</td>
                  <td class="num"><strong>${r.gross_total > 0 ? r.net_total : "-"}</strong></td>
                  <td class="num">${fmtPtBadge(r.points_adjustment)}</td>
                </tr>
              `
            )}
          </tbody>
        </table>
      </div>

      <div class="table-wrap" style="margin-top:12px;">
        <table>
          <caption class="sr-only">Hole-by-hole 2-person team match comparison</caption>
          <thead>
            <tr>
              <th scope="col">Hole</th>
              <th scope="col" class="num">Par</th>
              <th scope="col" class="num">Rank</th>
              <th scope="col" class="num">${ta.name} Net</th>
              <th scope="col" class="num">${tb.name} Net</th>
              <th scope="col" class="num">Hole Pts (A / B)</th>
            </tr>
          </thead>
          <tbody>
            ${holes.map(
              (h) => html`
                <tr>
                  <th scope="row">Hole ${h.hole_number}</th>
                  <td class="num">${h.par}</td>
                  <td class="num">#${h.hole_rank}</td>
                  <td class="num">${h.team_a_gross}${h.team_a_strokes ? " (-" + h.team_a_strokes + ")" : ""} = <strong>${h.team_a_net}</strong></td>
                  <td class="num">${h.team_b_gross}${h.team_b_strokes ? " (-" + h.team_b_strokes + ")" : ""} = <strong>${h.team_b_net}</strong></td>
                  <td class="num"><strong>${h.team_a_pts}</strong> / <strong>${h.team_b_pts}</strong></td>
                </tr>
              `
            )}
          </tbody>
        </table>
      </div>
    `
  );
  modal.classList.remove("hidden");
  makeScrollRegionsFocusable(contentEl);
}

function closeBreakdownModal() {
  document.getElementById("matchupBreakdownModal")?.classList.add("hidden");
  if (state.modalFocusReturn) {
    state.modalFocusReturn.focus();
    state.modalFocusReturn = null;
  }
}

function extractScheduledWeekMatches(sc) {
  const sched = sc.schedule || {};
  const teamsMap = {};
  (state.standings?.teams || []).forEach((t) => {
    teamsMap[Number(t.TeamID)] = t.TeamName || `Team ${t.TeamID}`;
  });
  const out = [];
  for (let m = 1; m <= 11; m++) {
    const t1 = Number(sched[`Match${m}Team1`] || 0);
    const t2 = Number(sched[`Match${m}Team2`] || 0);
    if (t1 > 0 && t2 > 0) {
      out.push({
        match_num: m,
        team1_id: t1,
        team1_name: teamsMap[t1] || `Team ${t1}`,
        team2_id: t2,
        team2_name: teamsMap[t2] || `Team ${t2}`,
      });
    }
  }
  return out;
}

async function loadWeekScorecard() {
  const sc = await api(`/api/leagues/${state.activeLeagueId}/week/${state.activeWeek}`);
  state.scorecard = sc;
  const holesMeta = sc.holes_meta || [];
  document.getElementById("weekCourseBadge").textContent = `${sc.course?.CourseName || "Edwards County Golf Course"} · ${sc.num_holes} Holes`;

  setHtml(
    document.getElementById("caddyPlayerSelect"),
    html`${(sc.scorecards || []).map(
      (c) => html`<option value="${c.PlayerID}">${c.PlayerName} (T${c.TeamID} · Hcp ${fmtHcp(c.Handicap)})</option>`
    )}`
  );
  setHtml(
    document.getElementById("caddyHoleSelect"),
    html`${holesMeta.map((h, i) => html`<option value="${i}">Hole #${h.hole} (Par ${h.par})</option>`)}`
  );
  updateCaddyHoleMeta();

  // Populate #scorecardMatchFilter options
  const matchFilterEl = document.getElementById("scorecardMatchFilter");
  if (matchFilterEl) {
    const wkPairs = extractScheduledWeekMatches(sc);
    const prevVal = state.scorecardViewMode || "grouped";
    setHtml(
      matchFilterEl,
      html`
        <option value="grouped">Grouped by 2-Man Matchup (${wkPairs.length} Matches)</option>
        <option value="all">Full Roster (All ${(sc.scorecards || []).length} Golfers)</option>
        ${wkPairs.map(
          (mp) => html`<option value="match:${mp.match_num}">Match #${mp.match_num}: T${mp.team1_id} (${mp.team1_name}) vs T${mp.team2_id} (${mp.team2_name})</option>`
        )}
      `
    );
    if (Array.from(matchFilterEl.options).some((o) => o.value === prevVal)) {
      matchFilterEl.value = prevVal;
    } else {
      state.scorecardViewMode = "grouped";
      matchFilterEl.value = "grouped";
    }
  }

  renderScorecardTableBody(sc);

  // Render ECGC 2-Person Team Matchups (if present) + Head-to-Head Matchup Pairings
  const ecgcMatches = sc.ecgc_matches || [];
  const matchups = sc.matchups || [];
  const totalCount = ecgcMatches.length > 0 ? ecgcMatches.length : matchups.length;
  document.getElementById("matchupsCountBadge").textContent = `${totalCount} Matchups`;

  if (ecgcMatches.length > 0) {
    setHtml(
      document.getElementById("matchupsBox"),
      html`${ecgcMatches.map(
        (em) => html`
          <div class="matchup-card">
            <div class="matchup-row">
              <strong>Match #${em.match_number}: ${em.team_a_name}</strong>
              <span class="badge gold">${fmtNum(em.team_a_points, 1)} PTS</span>
            </div>
            <div class="matchup-row">
              <strong>vs ${em.team_b_name}</strong>
              <span class="badge gold">${fmtNum(em.team_b_points, 1)} PTS</span>
            </div>
            <div class="matchup-status" style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">
              <span>${em.result_summary || em.winner_label || "Completed"}</span>
              <button type="button" class="btn small open-breakdown-btn" data-mid="${em.match_id}">📊 9-Hole &amp; PT Breakdown</button>
            </div>
          </div>
        `
      )}`
    );
    document.querySelectorAll(".open-breakdown-btn").forEach((b) => {
      b.addEventListener(
        "click",
        guarded(async () => {
          await openBreakdownModal(Number(b.dataset.mid));
        })
      );
    });
  } else {
    setHtml(
      document.getElementById("matchupsBox"),
      matchups.length > 0
        ? html`${matchups.map(
            (m) => html`
              <div class="matchup-card">
                <div class="matchup-row">
                  <strong>${m.PlayerA_Name} (T${m.PlayerA_Team} · Hcp ${fmtHcp(m.PlayerA_Hcp)})</strong>
                  <span class="badge">${m.computed_pts_a} pts (${m.holes_won_a}W)</span>
                </div>
                <div class="matchup-row">
                  <strong>${m.PlayerB_Name} (T${m.PlayerB_Team} · Hcp ${fmtHcp(m.PlayerB_Hcp)})</strong>
                  <span class="badge">${m.computed_pts_b} pts (${m.holes_won_b}W)</span>
                </div>
                <div class="matchup-status">${m.status} · ${m.holes_halved} Halved</div>
              </div>
            `
          )}`
        : html`<div class="brand-sub"><span role="status">No pairings found for this week.</span></div>`
    );
  }

  // Skins
  const gSkins = sc.gross_skins || [];
  setHtml(
    document.getElementById("grossSkinsBox"),
    gSkins.length > 0
      ? html`${gSkins.map(
          (s) => html`<div class="skin-pill"><strong>Hole #${s.hole}</strong> (Par ${s.par}): ${s.player} — <span class="badge gold">${s.score} Gross</span></div>`
        )}`
      : html`<div class="brand-sub"><span role="status">No outright gross skins on this week's card.</span></div>`
  );

  const nSkins = sc.net_skins || [];
  setHtml(
    document.getElementById("netSkinsBox"),
    nSkins.length > 0
      ? html`${nSkins.map(
          (s) => html`<div class="skin-pill"><strong>Hole #${s.hole}</strong> (Par ${s.par}): ${s.player} — <span class="badge gold">${s.net_score} Net</span></div>`
        )}`
      : html`<div class="brand-sub"><span role="status">No outright net skins on this week's card.</span></div>`
  );
}

function renderScorecardTableBody(sc) {
  const holesMeta = sc.holes_meta || [];
  const thead = document.querySelector("#scorecardTable thead");
  const tbody = document.querySelector("#scorecardTable tbody");
  const isEcgcNine = isEcgcLeague(state.activeLeagueId) && Number(sc.num_holes || 9) === 9;
  const showBack = sc.num_holes > 9;

  if (isEcgcNine) {
    setHtml(
      thead,
      html`
        <tr>
          <th scope="col">Golfer</th>
          <th scope="col">Team</th>
          <th scope="col" class="num">Hcp</th>
          ${holesMeta.map(
            (h) =>
              html`<th scope="col" class="hole-cell"><abbr title="Hole ${h.hole}">H${h.hole}</abbr><div class="brand-sub">P${h.par}·#${h.handicap_rank}</div></th>`
          )}
          <th scope="col" class="num">Gross</th>
          <th scope="col" class="num"><abbr title="Equitable Stroke Control adjusted score">ESC Adj</abbr></th>
          <th scope="col" class="num">Net</th>
          <th scope="col" class="num"><abbr title="Over or under par 36">+/-</abbr></th>
          <th scope="col" class="num"><abbr title="Per-Player Net vs Par 36 Bonus/Penalty (+1 / 0 / -1)">Extra PT</abbr></th>
          <th scope="col" class="num"><abbr title="Next Week Handicap (HCP - PT)">Next Hcp</abbr></th>
          <th scope="col">Save</th>
        </tr>
      `
    );
  } else {
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
          <th scope="col" class="num">Pts / PT</th>
          <th scope="col">Save</th>
        </tr>
      `
    );
  }


const TEAM_TINT_THEMES = [
  { tint: "rgba(16, 185, 129, 0.11)", border: "#10b981", pillBg: "rgba(16, 185, 129, 0.22)", pillText: "#6ee7b7" },
  { tint: "rgba(59, 130, 246, 0.11)", border: "#3b82f6", pillBg: "rgba(59, 130, 246, 0.22)", pillText: "#93c5fd" },
  { tint: "rgba(245, 158, 11, 0.11)", border: "#f59e0b", pillBg: "rgba(245, 158, 11, 0.22)", pillText: "#fcd34d" },
  { tint: "rgba(139, 92, 246, 0.11)", border: "#8b5cf6", pillBg: "rgba(139, 92, 246, 0.22)", pillText: "#c4b5fd" },
  { tint: "rgba(236, 72, 153, 0.10)", border: "#ec4899", pillBg: "rgba(236, 72, 153, 0.22)", pillText: "#f9a8d4" },
  { tint: "rgba(6, 182, 212, 0.11)", border: "#06b6d4", pillBg: "rgba(6, 182, 212, 0.22)", pillText: "#67e8f9" }
];
function getTeamTintTheme(teamId) {
  const n = Number(teamId || 0);
  if (!n || n <= 0) return null;
  return TEAM_TINT_THEMES[(n - 1) % TEAM_TINT_THEMES.length];
}
function computeBlind40Client(handicap, holesMeta) {
  const pars = (holesMeta && holesMeta.length === 9) ? holesMeta.map(h => Number(h.par || 4)) : [4, 4, 4, 3, 5, 5, 4, 3, 4];
  const ranks = (holesMeta && holesMeta.length === 9) ? holesMeta.map(h => Number(h.handicap_rank || 9)) : [13, 1, 9, 7, 11, 5, 3, 15, 17];
  const hcp = Math.round(Number(handicap || 0));
  const coursePar = pars.reduce((a, b) => a + b, 0);
  const bogeysOverPar = (40 + hcp) - coursePar;
  const order = pars.map((_, i) => i).sort((a, b) => ranks[a] - ranks[b]);
  const baseAdd = Math.trunc(bogeysOverPar / pars.length) || 0;
  const rem = Math.abs(bogeysOverPar % pars.length);
  const strokes = pars.map(() => baseAdd);
  const extra = bogeysOverPar >= 0 ? order.slice(0, rem) : order.slice(-rem);
  for (const idx of extra) strokes[idx] += Math.sign(bogeysOverPar);
  return pars.map((p, i) => Math.max(1, p + strokes[i]));
}

  const renderPlayerRow = (row) => {
    const name = row.PlayerName || `Player ${row.PlayerID}`;
    const isSub = Number(row.Sub || 0) === 1 || Number(row.PlayerID || 0) >= 900 || !row.TeamID;
    const theme = !isSub ? getTeamTintTheme(row.TeamID) : null;
    const teamMembers = (!isSub && row.TeamID && Array.isArray(sc.scorecards))
      ? sc.scorecards.filter(c => Number(c.TeamID) === Number(row.TeamID)).map(c => c.PlayerName).filter(Boolean)
      : [];
    const teamBoxLabel = !isSub && row.TeamID
      ? (teamMembers.length > 0 ? `Team ${row.TeamID}: ${teamMembers.join(" and ")}` : `Team ${row.TeamID}`)
      : "SUB";
    const rowStyle = theme ? `--team-tint-bg:${theme.tint};--team-border-color:${theme.border};--team-pill-bg:${theme.pillBg};--team-pill-text:${theme.pillText};` : "";
    const holeInputs = row.holes.map((val, idx) => {
      const strokes = row.strokes_received[idx] || 0;
      const holeNo = holesMeta[idx]?.hole ?? idx + 1;
      const dotStr = strokes > 0 ? "•".repeat(strokes) : strokes < 0 ? "+" + Math.abs(strokes) : "";
      const label = `${name}, hole ${holeNo} score${strokes ? `, handicap strokes ${strokes}` : ""}`;
      return html`<td class="hole-cell">
        <span class="stroke-dots" aria-hidden="true" title="${strokes} handicap stroke(s)">${dotStr}</span>
        <input type="number" inputmode="numeric" min="0" max="20" step="1" class="score-input" data-pid="${row.PlayerID}" data-hidx="${idx}" value="${val || ""}" placeholder="-" aria-label="${label}" />
      </td>`;
    });

    const overStr = row.Gross > 0 ? (row.OverPar > 0 ? `+${row.OverPar}` : String(row.OverPar)) : "-";
    const adjStr =
      row.AdjGross > 0 ? `${row.AdjGross}${row.ESC_CappedStrokes > 0 ? " (-" + row.ESC_CappedStrokes + ")" : ""}` : "-";

    if (isEcgcNine) {
      const ptVal = row.Gross > 0 ? Number(row.ecgc_pt ?? row.IndividualPts ?? 0) : 0;
      const nextHcp = row.Gross > 0 ? Number(row.next_handicap ?? (Number(row.Handicap || 0) - ptVal)) : Number(row.Handicap || 0);
      return html`
        <tr data-row-pid="${row.PlayerID}" data-hcp="${row.Handicap || 0}" class="${theme ? "team-tinted-row" : ""} ${isSub ? "sub-player-row" : ""}" style="${rowStyle}">
          <th scope="row">
            <div class="player-name-line">
              <strong>${name}</strong>
              ${isSub ? html`<span class="badge sub-pill" title="Substitute Golfer">SUB</span>` : ""}
            </div>
          </th>
          <td><span class="team-pill-tag">${teamBoxLabel}</span></td>
          <td class="num">${fmtHcp(row.Handicap)}</td>
          ${holeInputs}
          <td class="num"><span class="badge cell-gross">${row.Gross || "-"}</span></td>
          <td class="num cell-esc">${adjStr}</td>
          <td class="num"><span class="badge gold cell-net">${row.Net || "-"}</span></td>
          <td class="num cell-over">${overStr}</td>
          <td class="num cell-pt">
            ${row.Gross > 0 ? fmtPtBadge(ptVal) : html`<span class="badge pt-even">-</span>`}
            <input type="hidden" class="pts-inp" value="${ptVal}" />
          </td>
          <td class="num cell-nexthcp">${row.Gross > 0 ? fmtHcp(nextHcp) : fmtHcp(row.Handicap)}</td>
          <td class="row-actions-cell">
            <button type="button" class="secondary blind40-btn" data-pid="${row.PlayerID}" title="Blind 40: Auto-fill Net 40 / Gross ${40 + Math.round(Number(row.Handicap || 0))} on hardest holes">Blind 40</button>
            <button type="button" class="primary save-score-btn" data-pid="${row.PlayerID}" aria-label="Save scores for ${name}">Save</button>
          </td>
        </tr>
      `;
    }

    return html`
      <tr data-row-pid="${row.PlayerID}" data-hcp="${row.Handicap || 0}">
        <th scope="row"><strong>${name}</strong></th>
        <td>T${row.TeamID || "-"}</td>
        <td class="num">${fmtHcp(row.Handicap)}</td>
        ${holeInputs}
        <td class="num"><strong>${row.FrontNine || "-"}</strong></td>
        ${showBack ? html`<td class="num"><strong>${row.BackNine || "-"}</strong></td>` : ""}
        <td class="num"><span class="badge">${row.Gross || "-"}</span></td>
        <td class="num">${adjStr}</td>
        <td class="num"><span class="badge gold">${row.Net || "-"}</span></td>
        <td class="num">${overStr}</td>
        <td class="num">${row.Gross > 0 ? row.StablefordNet : "-"}</td>
        <td class="num"><input type="number" min="0" max="100" class="stat-input putts-inp" value="${row.NumPutts || 0}" aria-label="${name}, putts" /></td>
        <td class="num"><input type="number" min="0" max="${sc.num_holes || 9}" class="stat-input gir-inp" value="${row.GreensInRegulation || 0}" aria-label="${name}, greens in regulation" /></td>
        <td class="num"><input type="number" step="0.5" class="stat-input pts-inp" value="${row.IndividualPts || 0}" aria-label="${name}, individual points" /></td>
        <td><button type="button" class="primary save-score-btn" data-pid="${row.PlayerID}" aria-label="Save scores for ${name}">Save</button></td>
      </tr>
    `;
  };

  const allCards = sc.scorecards || [];
  const wkPairs = extractScheduledWeekMatches(sc);
  const mode = state.scorecardViewMode || "grouped";
  const colSpan = isEcgcNine ? 10 + holesMeta.length : 12 + holesMeta.length + (showBack ? 1 : 0);

  let bodyFragments = [];
  if (isEcgcNine && mode.startsWith("match:")) {
    const mNum = Number(mode.split(":")[1] || 1);
    const pair = wkPairs.find((p) => p.match_num === mNum);
    if (pair) {
      const mCards = allCards.filter((c) => Number(c.TeamID) === pair.team1_id || Number(c.TeamID) === pair.team2_id);
      bodyFragments.push(html`
        <tr class="matchup-group-row">
          <td colspan="${colSpan}">
            ⚔️ Match #${pair.match_num}: Team ${pair.team1_id} (${pair.team1_name}) vs Team ${pair.team2_id} (${pair.team2_name})
          </td>
        </tr>
      `);
      bodyFragments.push(...mCards.map(renderPlayerRow));
    } else {
      bodyFragments = allCards.map(renderPlayerRow);
    }
  } else if (isEcgcNine && mode === "grouped" && wkPairs.length > 0) {
    const seenPids = new Set();
    for (const pair of wkPairs) {
      const mCards = allCards.filter((c) => Number(c.TeamID) === pair.team1_id || Number(c.TeamID) === pair.team2_id);
      if (mCards.length === 0) continue;
      bodyFragments.push(html`
        <tr class="matchup-group-row">
          <td colspan="${colSpan}">
            ⚔️ Match #${pair.match_num}: Team ${pair.team1_id} (${pair.team1_name}) vs Team ${pair.team2_id} (${pair.team2_name})
          </td>
        </tr>
      `);
      for (const c of mCards) {
        seenPids.add(Number(c.PlayerID));
        bodyFragments.push(renderPlayerRow(c));
      }
    }
    const remaining = allCards.filter((c) => !seenPids.has(Number(c.PlayerID)));
    if (remaining.length > 0) {
      bodyFragments.push(html`
        <tr class="matchup-group-row">
          <td colspan="${colSpan}">Other Roster &amp; Substitute Golfers</td>
        </tr>
      `);
      bodyFragments.push(...remaining.map(renderPlayerRow));
    }
  } else {
    bodyFragments = allCards.map(renderPlayerRow);
  }

  setHtml(tbody, html`${bodyFragments}`);

  // Live client-side Gross / Net / PT / Next Hcp calculation as scores are typed
  if (isEcgcNine) {
    tbody.querySelectorAll("tr[data-row-pid]").forEach((tr) => {
      const inps = Array.from(tr.querySelectorAll(".score-input"));
      inps.forEach((inp) => {
        inp.addEventListener("input", () => {
          const vals = inps.map((el) => Number(el.value || 0));
          const gross = vals.reduce((a, b) => a + (b > 0 ? b : 0), 0);
          const hcp = Number(tr.dataset.hcp || 0);
          const grossEl = tr.querySelector(".cell-gross");
          const netEl = tr.querySelector(".cell-net");
          const overEl = tr.querySelector(".cell-over");
          const ptEl = tr.querySelector(".cell-pt");
          const nextEl = tr.querySelector(".cell-nexthcp");
          if (gross > 0) {
            const net = gross - Math.round(hcp);
            const over = gross - 36;
            const pt = net <= 35 ? 1.0 : net === 36 ? 0.0 : -1.0;
            const nextHcp = Number((hcp - pt).toFixed(1));
            if (grossEl) grossEl.textContent = String(gross);
            if (netEl) netEl.textContent = String(net);
            if (overEl) overEl.textContent = over > 0 ? `+${over}` : String(over);
            if (ptEl) {
              setHtml(
                ptEl,
                html`${fmtPtBadge(pt)}<input type="hidden" class="pts-inp" value="${pt}" />`
              );
            }
            if (nextEl) nextEl.textContent = fmtHcp(nextHcp);
          }
        });
      });
    });
  }

  tbody.querySelectorAll(".blind40-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pid = Number(btn.dataset.pid);
      const tr = tbody.querySelector(`tr[data-row-pid="${pid}"]`);
      if (!tr) return;
      const hcp = Number(tr.dataset.hcp || 0);
      const holes = computeBlind40Client(hcp, holesMeta);
      tr.dataset.blind40 = "1";
      const inps = Array.from(tr.querySelectorAll(".score-input"));
      inps.forEach((inp, i) => {
        if (holes[i] !== undefined) inp.value = String(holes[i]);
      });
      if (inps[0]) inps[0].dispatchEvent(new Event("input", { bubbles: false }));
      const nextEl = tr.querySelector(".cell-nexthcp");
      if (nextEl) nextEl.textContent = fmtHcp(hcp);
    });
  });

  tbody.querySelectorAll(".save-score-btn").forEach((btn) => {
    btn.addEventListener(
      "click",
      guarded(async () => {
        const pid = Number(btn.dataset.pid);
        await savePlayerScoreRow(pid);
      })
    );
  });
}

function updateCaddyHoleMeta() {
  const pid = Number(document.getElementById("caddyPlayerSelect")?.value);
  const hIdx = Number(document.getElementById("caddyHoleSelect")?.value);
  const hm = state.scorecard?.holes_meta?.[hIdx];
  const card = state.scorecard?.scorecards?.find((c) => Number(c.PlayerID) === pid);
  const metaEl = document.getElementById("caddyHoleMeta");
  if (!hm || !metaEl) return;
  const strokes = card?.strokes_received?.[hIdx] || 0;
  metaEl.textContent = `Hole #${hm.hole} · Par ${hm.par} · ${hm.yards} yds · Stroke Index #${hm.handicap_rank} (${strokes} Pop${strokes === 1 ? "" : "s"})`;
}

async function savePlayerScoreRow(pid) {
  const rowEl = document.querySelector(`tr[data-row-pid="${pid}"]`);
  if (!rowEl) return;
  const holeInps = Array.from(rowEl.querySelectorAll(".score-input"));
  let invalid = false;
  const holes = holeInps.map((inp) => {
    const raw = inp.value.trim();
    const n = raw === "" ? 0 : Number(raw);
    const bad = !Number.isInteger(n) || n < 0 || n > 20;
    inp.setAttribute("aria-invalid", bad ? "true" : "false");
    if (bad) invalid = true;
    return bad ? 0 : n;
  });
  if (invalid) {
    showToast("Hole scores must be whole numbers between 0 and 20.", { error: true });
    rowEl.querySelector('.score-input[aria-invalid="true"]')?.focus();
    return;
  }
  const putts = Number(rowEl.querySelector(".putts-inp")?.value || 0);
  const gir = Number(rowEl.querySelector(".gir-inp")?.value || 0);
  const pts = Number(rowEl.querySelector(".pts-inp")?.value || 0);

  await api(`/api/leagues/${state.activeLeagueId}/week/${state.activeWeek}/scores`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      PlayerID: pid,
      holes,
      NumPutts: putts,
      GreensInRegulation: gir,
      IndividualPts: pts,
      Blind40: Number(rowEl.dataset.blind40 || 0) === 1,
    }),
  });
  showToast(`Saved Week ${state.activeWeek} scorecard & recalculated 2-man match + PT points!`);
  await refreshLeagueData();
}

function populateTeamEditInputs(teamId) {
  const teams = state.standings?.teams || [];
  const t = teams.find((x) => Number(x.TeamID) === Number(teamId)) || teams[0];
  if (!t) return;
  const nameEl = document.getElementById("teTeamName");
  const paEl = document.getElementById("tePlayerA");
  const pbEl = document.getElementById("tePlayerB");
  if (nameEl) nameEl.value = t.TeamName || `Team ${t.TeamID}`;
  if (paEl) paEl.value = String(t.PlayerA || "");
  if (pbEl) pbEl.value = String(t.PlayerB || "");
}

function renderRosterTab(st) {
  const teams = st.teams || [];
  const players = st.players || [];
  const subs = st.subs || [];
  const fees = st.fees || [];
  const isEcgc = isEcgcLeague(state.activeLeagueId);

  const teamForm = document.getElementById("teamEditForm");
  const subsTitle = document.getElementById("subsPanelTitle");
  const subsBadge = document.getElementById("subsPanelBadge");
  const feesTitle = document.getElementById("feesPanelTitle");
  const feesBadge = document.getElementById("feesPanelBadge");
  const searchInp = document.getElementById("careerSearchInput");

  const subsThead = document.querySelector("#subsTable thead");
  const subsTbody = document.querySelector("#subsTable tbody");
  const feesThead = document.querySelector("#feesTable thead");
  const feesTbody = document.querySelector("#feesTable tbody");

  if (isEcgc) {
    teamForm?.classList.remove("hidden");
    searchInp?.classList.remove("hidden");
    if (subsTitle) subsTitle.textContent = "2-Man Team Roster & Partner Manager";
    if (subsBadge) subsBadge.textContent = `${teams.length} Teams`;
    if (feesTitle) feesTitle.textContent = "ECGC Career Golfer Directory (2018–2026)";

    const teSel = document.getElementById("teTeamId");
    const paSel = document.getElementById("tePlayerA");
    const pbSel = document.getElementById("tePlayerB");
    if (teSel && paSel && pbSel) {
      const sortedTeamsById = [...teams].sort((a, b) => Number(a.TeamID) - Number(b.TeamID));
      setHtml(
        teSel,
        html`${sortedTeamsById.map((t) => html`<option value="${t.TeamID}">Team #${t.TeamID}: ${t.TeamName}</option>`)}`
      );
      const pOpts = html`<option value="">-- Select Golfer --</option>${players.map(
        (p) => html`<option value="${p.PlayerID}">${p.PlayerFirst} ${p.PlayerLast} (Hcp ${fmtHcp(p.Handicap)})</option>`
      )}`;
      setHtml(paSel, pOpts);
      setHtml(pbSel, pOpts);
      if (sortedTeamsById.length > 0) {
        populateTeamEditInputs(sortedTeamsById[0].TeamID);
      }
    }

    setHtml(
      subsThead,
      html`
        <tr>
          <th scope="col">Team #</th>
          <th scope="col">Team Name</th>
          <th scope="col">Partner 1</th>
          <th scope="col">Partner 2</th>
          <th scope="col" class="num">Comb Hcp</th>
          <th scope="col" class="num">Total Pts</th>
          <th scope="col">Edit</th>
        </tr>
      `
    );
    const sortedTeamsById = [...teams].sort((a, b) => Number(a.TeamID) - Number(b.TeamID));
    setHtml(
      subsTbody,
      html`${sortedTeamsById.map(
        (t) => html`
          <tr>
            <td><strong>#${t.TeamID}</strong></td>
            <th scope="row"><strong>${t.TeamName || "Team " + t.TeamID}</strong></th>
            <td>${t.PlayerA_Name || "-"} (${fmtHcp(t.PlayerA_Hcp)})</td>
            <td>${t.PlayerB_Name || "-"} (${fmtHcp(t.PlayerB_Hcp)})</td>
            <td class="num"><span class="badge">${fmtHcp(t.CombinedHcp ?? t.Handicap)}</span></td>
            <td class="num"><span class="badge gold">${fmtNum(t.Points, 1)} pts</span></td>
            <td><button type="button" class="btn small select-team-edit-btn" data-tid="${t.TeamID}" aria-label="Edit Team ${t.TeamID}">Edit</button></td>
          </tr>
        `
      )}`
    );
    subsTbody.querySelectorAll(".select-team-edit-btn").forEach((b) => {
      b.addEventListener("click", () => {
        const tid = Number(b.dataset.tid);
        const teEl = document.getElementById("teTeamId");
        if (teEl) teEl.value = String(tid);
        populateTeamEditInputs(tid);
        document.getElementById("teTeamName")?.focus();
      });
    });

    // Right Panel: 128-Player ECGC Career Golfer Directory
    const q = state.careerSearchQuery || "";
    const careerList = (state.ecgcPlayers || []).filter((ep) => {
      if (!q) return true;
      return (
        String(ep.display_name || "").toLowerCase().includes(q) ||
        String(ep.primary_division || "").toLowerCase().includes(q)
      );
    });
    if (feesBadge) feesBadge.textContent = `${careerList.length} Golfers`;

    setHtml(
      feesThead,
      html`
        <tr>
          <th scope="col">Golfer</th>
          <th scope="col">Div</th>
          <th scope="col" class="num">Seasons</th>
          <th scope="col" class="num">Rounds</th>
          <th scope="col" class="num">Avg Gross</th>
          <th scope="col" class="num">Avg Net</th>
          <th scope="col" class="num">Best 9H</th>
          <th scope="col" class="num">Career PT</th>
        </tr>
      `
    );
    setHtml(
      feesTbody,
      html`${careerList.map(
        (ep) => html`
          <tr>
            <th scope="row">
              <button type="button" class="link-btn career-dir-btn" data-pid="${ep.id}">
                <strong>${ep.display_name}</strong> 📊
              </button>
            </th>
            <td>${ep.primary_division === "womens" ? "Women's" : "Men's"}</td>
            <td class="num">${ep.seasons_played || 1}</td>
            <td class="num">${ep.career_rounds || 0}</td>
            <td class="num">${ep.avg_gross ? fmtNum(ep.avg_gross, 1) : "-"}</td>
            <td class="num">${ep.avg_net ? fmtNum(ep.avg_net, 1) : "-"}</td>
            <td class="num"><strong>${ep.best_gross ?? "-"}</strong></td>
            <td class="num">${fmtPtBadge(ep.total_pt_points)}</td>
          </tr>
        `
      )}`
    );
    feesTbody.querySelectorAll(".career-dir-btn").forEach((btn) => {
      btn.addEventListener(
        "click",
        guarded(async () => {
          await openCareerDrawer(Number(btn.dataset.pid));
        })
      );
    });
  } else {
    teamForm?.classList.add("hidden");
    searchInp?.classList.add("hidden");
    if (subsTitle) subsTitle.textContent = "Substitute Roster";
    if (subsBadge) subsBadge.textContent = `${subs.length} Subs`;
    if (feesTitle) feesTitle.textContent = "League Fees & Dues Ledger";
    if (feesBadge) feesBadge.textContent = `${fees.length} Records`;

    setHtml(
      subsThead,
      html`
        <tr>
          <th scope="col">Sub ID</th>
          <th scope="col">Name</th>
          <th scope="col" class="num">Handicap</th>
          <th scope="col" class="num">Points</th>
          <th scope="col" class="num">Money</th>
          <th scope="col">Phone</th>
        </tr>
      `
    );
    setHtml(
      subsTbody,
      html`${subs.map(
        (s) => html`
          <tr>
            <td>#${s.SubID}</td>
            <th scope="row"><strong>${s.SubFirst || ""} ${s.SubLast || ""}</strong></th>
            <td class="num">${fmtHcp(s.Handicap)}</td>
            <td class="num">${fmtNum(s.Points)}</td>
            <td class="num">${fmtMoney(s.Money)}</td>
            <td>${s.HomePhone || s.WorkPhone || "-"}</td>
          </tr>
        `
      )}`
    );

    setHtml(
      feesThead,
      html`
        <tr>
          <th scope="col">Player ID</th>
          <th scope="col">Player Name</th>
          <th scope="col" class="num">Green Fees</th>
          <th scope="col" class="num">League Fee</th>
          <th scope="col" class="num">Skins Fee</th>
          <th scope="col" class="num">Banquet Fee</th>
          <th scope="col" class="num">Extra Fee</th>
        </tr>
      `
    );
    setHtml(
      feesTbody,
      html`${fees.map(
        (f) => html`
          <tr>
            <td>#${f.PlayerID}</td>
            <th scope="row">${f.PlayerFirst || ""} ${f.PlayerLast || ""}</th>
            <td class="num">${fmtMoney(f.GreenFees)}</td>
            <td class="num">${fmtMoney(f.LeagueFee)}</td>
            <td class="num">${fmtMoney(f.SkinsFee)}</td>
            <td class="num">${fmtMoney(f.BanquetFee)}</td>
            <td class="num">${fmtMoney(f.ExtraFee)}</td>
          </tr>
        `
      )}`
    );
  }
}

function populatePairingsBuilderWeek(weekNum) {
  const sched = state.scheduleData?.schedule || [];
  const teams = state.standings?.teams || [];
  const sortedTeams = [...teams].sort((a, b) => Number(a.TeamID) - Number(b.TeamID));
  const wkRow = sched.find((r) => Number(r.WeekNum) === Number(weekNum)) || {};
  const maxMatches = Math.max(2, Math.min(11, Math.ceil(sortedTeams.length / 2) || 6));

  const wkInp = document.getElementById("peWeekNum");
  const dtInp = document.getElementById("peDate");
  const hfSel = document.getElementById("peHalf");
  if (wkInp) wkInp.value = String(weekNum);
  if (dtInp && wkRow.Date) {
    const rawDt = String(wkRow.Date).split(" ")[0];
    if (/^\d{4}-\d{2}-\d{2}$/.test(rawDt)) dtInp.value = rawDt;
  }
  if (hfSel) hfSel.value = String(wkRow.Half || (weekNum <= 8 ? 1 : 2));

  const grid = document.getElementById("peMatchesGrid");
  if (!grid) return;

  const rowsHtml = [];
  for (let m = 1; m <= maxMatches; m++) {
    const t1Val = Number(wkRow[`Match${m}Team1`] || 0);
    const t2Val = Number(wkRow[`Match${m}Team2`] || 0);
    rowsHtml.push(html`
      <div class="pe-match-row" style="padding:8px;border:1px solid var(--border);border-radius:6px;background:var(--bg-card);">
        <div class="brand-sub" style="font-weight:700;margin-bottom:4px;">Match #${m}</div>
        <div class="form-row">
          <select class="pe-t1" aria-label="Match ${m} Team 1" style="flex:1;">
            <option value="0">-- Team A --</option>
            ${sortedTeams.map(
              (t) =>
                html`<option value="${t.TeamID}" ${Number(t.TeamID) === t1Val ? new SafeHtml("selected") : ""}>T${t.TeamID}: ${t.TeamName}</option>`
            )}
          </select>
          <span>vs</span>
          <select class="pe-t2" aria-label="Match ${m} Team 2" style="flex:1;">
            <option value="0">-- Team B --</option>
            ${sortedTeams.map(
              (t) =>
                html`<option value="${t.TeamID}" ${Number(t.TeamID) === t2Val ? new SafeHtml("selected") : ""}>T${t.TeamID}: ${t.TeamName}</option>`
            )}
          </select>
        </div>
      </div>
    `);
  }
  setHtml(grid, html`${rowsHtml}`);
}

async function loadScheduleTab() {
  const data = await api(`/api/leagues/${state.activeLeagueId}/schedule`);
  state.scheduleData = data;
  const sched = data.schedule || [];

  const wkSel = document.getElementById("weekSelect");
  const maxWk = Math.max(16, sched.length);
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
    html`${sched.map((w) => {
      const mList = w.matches || [];
      return html`
        <tr>
          <th scope="row"><strong>Week ${w.WeekNum}</strong></th>
          <td>${String(w.Date || "").split(" ")[0]}</td>
          <td>Half ${w.Half || 1}</td>
          <td>${w.Weather || "Clear"}</td>
          <td>
            <div class="sched-matches-grid">
              ${
                mList.length > 0
                  ? mList.map((m) => {
                      const hasScore = m.team1_pts !== null && m.team1_pts !== undefined;
                      const scoreBadge = hasScore
                        ? html`<span class="badge gold">${fmtNum(m.team1_pts, 1)}–${fmtNum(m.team2_pts, 1)}</span>`
                        : "";
                      return html`
                        <button
                          type="button"
                          class="sched-match-pill"
                          data-mid="${m.match_id || ""}"
                          data-wk="${w.WeekNum}"
                          title="Week ${w.WeekNum} Match ${m.match_num}: ${m.label}"
                        >
                          <strong>M${m.match_num}:</strong> ${m.team1_name} vs ${m.team2_name} ${scoreBadge}
                        </button>
                      `;
                    })
                  : html`<span class="brand-sub">${w.Match1Label || "No pairings"}</span>`
              }
            </div>
          </td>
          <td>
            <div class="form-row">
              <button type="button" class="open-wk-btn" data-wk="${w.WeekNum}" aria-label="Open Scorecard for Week ${w.WeekNum}">
                Scorecard <span aria-hidden="true">→</span>
              </button>
              <button type="button" class="btn small edit-wk-pairs-btn" data-wk="${w.WeekNum}" aria-label="Edit Pairings for Week ${w.WeekNum}">
                ✏️ Edit
              </button>
            </div>
          </td>
        </tr>
      `;
    })}`
  );

  tbody.querySelectorAll(".sched-match-pill").forEach((pill) => {
    pill.addEventListener(
      "click",
      guarded(async () => {
        const mid = Number(pill.dataset.mid || 0);
        if (mid > 0) {
          await openBreakdownModal(mid);
        } else {
          state.activeWeek = Number(pill.dataset.wk || 1);
          document.getElementById("weekSelect").value = String(state.activeWeek);
          activateTab(document.querySelector('.tab-btn[data-tab="scorecard"]'), { focus: true });
          await loadWeekScorecard();
        }
      })
    );
  });

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

  tbody.querySelectorAll(".edit-wk-pairs-btn").forEach((b) => {
    b.addEventListener("click", () => {
      const wk = Number(b.dataset.wk || 1);
      const box = document.getElementById("weekPairingsEditorBox");
      if (box) {
        box.classList.remove("hidden");
        populatePairingsBuilderWeek(wk);
        document.getElementById("peWeekNum")?.focus();
      }
    });
  });
}

async function loadCoursesTab() {
  const lidParam =
    state.courseAnalyticsScope === "season" && isEcgcLeague(state.activeLeagueId)
      ? `?league_id=${state.activeLeagueId}`
      : "";
  const [data, analytics] = await Promise.all([
    api("/api/courses"),
    api(`/api/ecgc/course-analytics${lidParam}`).catch(() => null),
  ]);
  state.courses = data.courses || [];
  state.courseAnalytics = analytics;

  const visibleCourses = state.showLegacyCourses
    ? state.courses
    : state.courses.filter((c) => Number(c.CourseID) === 5 || Boolean(c.is_default));
  const coursesToRender = visibleCourses.length > 0 ? visibleCourses : state.courses;

  const analyticsHoles = analytics?.holes || [];

  setHtml(
    document.getElementById("coursesContainer"),
    html`
      ${coursesToRender.map((c) => {
        const sumYards = (arr) => arr.reduce((a, x) => a + Number(x.yards || 0), 0);
        const isNine = Number(c.NumHoles || c.holes.length) === 9;
        const isDefault = Boolean(c.is_default || Number(c.CourseID) === 5);
        const teesText =
          (c.tees || []).length > 0
            ? " · Tees: " + c.tees.map((t) => `${t.TeeName} (${t.TotalYards}y ${t.Rating}/${t.Slope})`).join(", ")
            : "";
        const subText = isNine
          ? `9-Hole Course · Par ${c.total_par} · Course Rating: ${c.CourseRating} · Slope Rating: ${c.SlopeRating}${teesText}`
          : `18-Hole Course · Course Rating: ${c.CourseRating} · Slope Rating: ${c.SlopeRating} · Front Par ${c.front_par} / Back Par ${c.back_par} (Total Par ${c.total_par})`;
        return html`
          <div class="panel">
            <div class="panel-header">
              <div>
                <h2><span aria-hidden="true">⛳</span> ${c.CourseName} (${c.CourseCity || c.City || "Kinsley"}, ${c.CourseState || c.State || "KS"})</h2>
                <div class="brand-sub">${subText}</div>
              </div>
              <div class="form-row">
                ${isDefault ? html`<span class="badge gold">Default League Course · 9 Holes</span>` : html`<span class="badge">${isNine ? "9 Holes" : "18 Holes"}</span>`}
                <button type="button" id="toggleLegacyCoursesBtn" class="btn small">
                  ${state.showLegacyCourses ? "Hide Legacy Demo Courses" : "Show 4 Legacy 18H Demo Courses"}
                </button>
              </div>
            </div>
            <div class="table-wrap">
              <table>
                <caption class="sr-only">${c.CourseName} hole-by-hole card</caption>
                <thead>
                  <tr>
                    <th scope="col">Metric</th>
                    ${c.holes.map((h) => html`<th scope="col" class="num">H${h.hole}</th>`)}
                    ${isNine ? html`<th scope="col" class="num">9-Hole Total</th>` : html`<th scope="col" class="num">Front 9</th><th scope="col" class="num">Back 9</th><th scope="col" class="num">Total</th>`}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">Par</th>
                    ${c.holes.map((h) => html`<td class="num"><strong>${h.par}</strong></td>`)}
                    ${isNine ? html`<td class="num"><strong>${c.total_par}</strong></td>` : html`<td class="num">${c.front_par}</td><td class="num">${c.back_par}</td><td class="num"><strong>${c.total_par}</strong></td>`}
                  </tr>
                  <tr>
                    <th scope="row">Yards (Blue)</th>
                    ${c.holes.map((h) => html`<td class="num">${h.yards}</td>`)}
                    ${isNine ? html`<td class="num"><strong>${sumYards(c.holes)}</strong></td>` : html`<td class="num">${sumYards(c.holes.slice(0, 9))}</td><td class="num">${sumYards(c.holes.slice(9, 18))}</td><td class="num">${sumYards(c.holes)}</td>`}
                  </tr>
                  <tr>
                    <th scope="row">Handicap Stroke Index</th>
                    ${c.holes.map((h) => html`<td class="num"><span class="badge gold">#${h.handicap_rank}</span></td>`)}
                    ${isNine ? html`<td class="num">9 Holes (Odd 1..17)</td>` : html`<td class="num">-</td><td class="num">-</td><td class="num">1..18</td>`}
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        `;
      })}

      ${
        analyticsHoles.length > 0
          ? html`
              <div class="panel">
                <div class="panel-header">
                  <div>
                    <h2>📊 Edwards County Golf Course — Hole-by-Hole Scoring &amp; Toughness Analytics</h2>
                    <div class="brand-sub">
                      Actual scoring averages, relative-to-par toughness rank (#1 Hardest to #9 Easiest), and Birdie / Par / Bogey distribution across Holes 1–9
                    </div>
                  </div>
                  <div class="form-row">
                    <button
                      type="button"
                      id="analyticsScopeSeasonBtn"
                      class="btn small ${state.courseAnalyticsScope === "season" ? "primary" : ""}"
                    >
                      Active Season (#${state.activeLeagueId})
                    </button>
                    <button
                      type="button"
                      id="analyticsScopeAllBtn"
                      class="btn small ${state.courseAnalyticsScope === "all" ? "primary" : ""}"
                    >
                      All-Time (2018–2026 · 49,689 Holes)
                    </button>
                  </div>
                </div>
                <div class="table-wrap">
                  <table>
                    <caption class="sr-only">Edwards County Golf Course hole-by-hole scoring analytics</caption>
                    <thead>
                      <tr>
                        <th scope="col">Hole</th>
                        <th scope="col" class="num">Par</th>
                        <th scope="col" class="num">Blue / White / Red Yds</th>
                        <th scope="col" class="num">9H Stroke Rank</th>
                        <th scope="col" class="num">Rounds</th>
                        <th scope="col" class="num">Avg Gross</th>
                        <th scope="col" class="num">vs Par</th>
                        <th scope="col" class="num">Actual Toughness</th>
                        <th scope="col" class="num">Eagle/Birdie</th>
                        <th scope="col" class="num">Pars</th>
                        <th scope="col" class="num">Bogeys</th>
                        <th scope="col" class="num">Double+</th>
                      </tr>
                    </thead>
                    <tbody>
                      ${analyticsHoles.map(
                        (h) => html`
                          <tr>
                            <th scope="row"><strong>Hole #${h.hole}</strong></th>
                            <td class="num"><strong>${h.par}</strong></td>
                            <td class="num">${h.yards_blue} / ${h.yards_white} / ${h.yards_red}</td>
                            <td class="num">#${h.nine_hole_rank} (Cap #${h.handicap_stroke_index})</td>
                            <td class="num">${h.samples}</td>
                            <td class="num"><strong>${fmtNum(h.avg_gross, 2)}</strong></td>
                            <td class="num">
                              <span class="badge ${h.over_par_avg >= 0.8 ? "gold" : ""}">
                                ${h.over_par_avg >= 0 ? "+" + fmtNum(h.over_par_avg, 2) : fmtNum(h.over_par_avg, 2)}
                              </span>
                            </td>
                            <td class="num"><strong>#${h.toughness_rank} ${h.toughness_rank === 1 ? "(Hardest)" : h.toughness_rank === 9 ? "(Easiest)" : ""}</strong></td>
                            <td class="num">${h.eagles_plus + h.birdies}</td>
                            <td class="num">${h.pars}</td>
                            <td class="num">${h.bogeys}</td>
                            <td class="num">${h.double_plus}</td>
                          </tr>
                        `
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            `
          : ""
      }
    `
  );

  document.getElementById("toggleLegacyCoursesBtn")?.addEventListener(
    "click",
    guarded(async () => {
      state.showLegacyCourses = !state.showLegacyCourses;
      await loadCoursesTab();
    })
  );
  document.getElementById("analyticsScopeSeasonBtn")?.addEventListener(
    "click",
    guarded(async () => {
      state.courseAnalyticsScope = "season";
      await loadCoursesTab();
    })
  );
  document.getElementById("analyticsScopeAllBtn")?.addEventListener(
    "click",
    guarded(async () => {
      state.courseAnalyticsScope = "all";
      await loadCoursesTab();
    })
  );

  makeScrollRegionsFocusable(document.getElementById("coursesContainer"));
}

async function openClubhouseSheetModal() {
  state.modalFocusReturn = document.activeElement;
  const st = state.standings || (await api(`/api/leagues/${state.activeLeagueId}/standings`));
  const sc = state.scorecard || (await api(`/api/leagues/${state.activeLeagueId}/week/${state.activeWeek}`));
  const lg = st.league || {};
  const teams = [...(st.teams || [])].sort((a, b) => Number(b.Points || 0) - Number(a.Points || 0));
  const leaderPts = teams.length > 0 ? Number(teams[0].Points || 0) : 0;
  const ecgcMatches = sc.ecgc_matches || [];
  const activeCards = (sc.scorecards || []).filter((c) => Number(c.Gross || 0) > 0);
  const gSkins = sc.gross_skins || [];
  const nSkins = sc.net_skins || [];

  const sheetFragment = html`
    <div style="border-bottom:2px solid var(--border);padding-bottom:8px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:baseline;">
      <div>
        <h2 style="margin:0;">⛳ Edwards County Golf Course — Weekly Clubhouse Sheet</h2>
        <div class="brand-sub">${lg.LeagueName || "ECGC League"} · Week #${sc.week_num || state.activeWeek} (${String(sc.schedule?.Date || "").split(" ")[0] || "Current"}) · 9 Holes (Par 36)</div>
      </div>
      <span class="badge gold">2-Man Match + Per-Player Net PT (+1 / 0 / -1)</span>
    </div>

    <div class="clubhouse-sheet-grid">
      <div>
        <h3>🏆 2-Man Team Standings</h3>
        <table>
          <caption class="sr-only">Clubhouse sheet team standings</caption>
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Team</th>
              <th scope="col" class="num">Comb Hcp</th>
              <th scope="col" class="num">1st</th>
              <th scope="col" class="num">2nd</th>
              <th scope="col" class="num">Total</th>
              <th scope="col" class="num">GB</th>
            </tr>
          </thead>
          <tbody>
            ${teams.map(
              (t, i) => html`
                <tr>
                  <td>${i + 1}</td>
                  <th scope="row"><strong>T${t.TeamID}: ${t.TeamName}</strong></th>
                  <td class="num">${fmtHcp(t.CombinedHcp ?? t.Handicap)}</td>
                  <td class="num">${fmtNum(t["1stHalfPts"], 1)}</td>
                  <td class="num">${fmtNum(t["2ndHalfPts"], 1)}</td>
                  <td class="num"><strong>${fmtNum(t.Points, 1)}</strong></td>
                  <td class="num">${leaderPts - Number(t.Points || 0) === 0 ? "-" : fmtNum(leaderPts - Number(t.Points || 0), 1)}</td>
                </tr>
              `
            )}
          </tbody>
        </table>
      </div>

      <div>
        <h3>⚔️ Week #${sc.week_num || state.activeWeek} 2-Man Match Results</h3>
        <table>
          <caption class="sr-only">Clubhouse sheet weekly match results</caption>
          <thead>
            <tr>
              <th scope="col">Match</th>
              <th scope="col">Team A</th>
              <th scope="col" class="num">Pts</th>
              <th scope="col">Team B</th>
              <th scope="col" class="num">Pts</th>
            </tr>
          </thead>
          <tbody>
            ${
              ecgcMatches.length > 0
                ? ecgcMatches.map(
                    (m) => html`
                      <tr>
                        <td>#${m.match_number}</td>
                        <th scope="row">${m.team_a_name}</th>
                        <td class="num"><strong>${fmtNum(m.team_a_points, 1)}</strong></td>
                        <td>${m.team_b_name}</td>
                        <td class="num"><strong>${fmtNum(m.team_b_points, 1)}</strong></td>
                      </tr>
                    `
                  )
                : html`<tr><td colspan="5">See Scorecard Table</td></tr>`
            }
          </tbody>
        </table>

        <h3 style="margin-top:10px;">🔥 Weekly Gross &amp; Net Skins</h3>
        <div class="brand-sub" style="margin-bottom:8px;">
          <strong>Gross Skins:</strong> ${gSkins.length > 0 ? gSkins.map((s) => `H${s.hole} ${s.player} (${s.score})`).join(" · ") : "None outright"}<br />
          <strong>Net Skins:</strong> ${nSkins.length > 0 ? nSkins.map((s) => `H${s.hole} ${s.player} (${s.net_score} Net)`).join(" · ") : "None outright"}
        </div>

        <h3>📈 Week #${sc.week_num || state.activeWeek} Scores, Extra PT &amp; Next Week Handicaps</h3>
        <table>
          <caption class="sr-only">Clubhouse sheet player scores and next week handicaps</caption>
          <thead>
            <tr>
              <th scope="col">Golfer</th>
              <th scope="col">Tm</th>
              <th scope="col" class="num">Gross</th>
              <th scope="col" class="num">Hcp</th>
              <th scope="col" class="num">Net</th>
              <th scope="col" class="num">PT</th>
              <th scope="col" class="num">Next Hcp</th>
            </tr>
          </thead>
          <tbody>
            ${activeCards.map(
              (c) => html`
                <tr>
                  <th scope="row">${c.PlayerName}</th>
                  <td>T${c.TeamID}</td>
                  <td class="num">${c.Gross}</td>
                  <td class="num">${fmtHcp(c.Handicap)}</td>
                  <td class="num"><strong>${c.Net}</strong></td>
                  <td class="num">${c.ecgc_pt > 0 ? "+" + c.ecgc_pt : c.ecgc_pt}</td>
                  <td class="num"><strong>${fmtHcp(c.next_handicap)}</strong></td>
                </tr>
              `
            )}
          </tbody>
        </table>
      </div>
    </div>
  `;

  setHtml(document.getElementById("clubhouseModalContent"), sheetFragment);
  setHtml(document.getElementById("clubhousePrintSheet"), sheetFragment);
  document.getElementById("clubhouseSheetModal")?.classList.remove("hidden");
}

function closeClubhouseSheetModal() {
  document.getElementById("clubhouseSheetModal")?.classList.add("hidden");
  if (state.modalFocusReturn) {
    state.modalFocusReturn.focus();
    state.modalFocusReturn = null;
  }
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
    setHtml(tbody, html`<tr><td class="brand-sub"><span role="status">Table "${tableName}" has 0 rows.</span></td></tr>`);
    return;
  }
  const cols = Object.keys(rows[0]);
  setHtml(thead, html`<tr>${cols.map((c) => html`<th scope="col">${c}</th>`)}</tr>`);
  setHtml(
    tbody,
    html`${rows.map((r) => html`<tr>${cols.map((c) => html`<td>${r[c] === null || r[c] === undefined ? "" : String(r[c])}</td>`)}</tr>`)}`
  );
}

if (document.readyState === "loading") {
  window.addEventListener(
    "DOMContentLoaded",
    guarded(() => initApp())
  );
} else {
  guarded(() => initApp())();
}

// Exposed for automated XSS regression tests.
window.__gls = { escapeHtml, html, SafeHtml };

