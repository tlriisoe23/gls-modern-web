"use strict";

const state = {
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

  let filtered = state.leagues.filter((l) => {
    const lid = Number(l.LeagueID);
    if (seasonVal === "legacy" || divVal === "legacy") return lid < 20180;
    if (seasonVal !== "all" && lid >= 20180) {
      if (String(Math.floor(lid / 10)) !== seasonVal) return false;
    }
    if (divVal === "mens" && lid >= 20180) {
      if (lid % 10 !== 1) return false;
    } else if (divVal === "womens" && lid >= 20180) {
      if (lid % 10 !== 2) return false;
    }
    return true;
  });
  if (filtered.length === 0) filtered = state.leagues;

  setHtml(
    lgSel,
    html`${filtered.map(
      (l) =>
        html`<option value="${l.LeagueID}">League #${l.LeagueID}: ${l.LeagueName} (${l.LeagueHoles}H ?? ${l.player_count} Players)</option>`
    )}`
  );
  if (filtered.some((l) => Number(l.LeagueID) === state.activeLeagueId)) {
    lgSel.value = String(state.activeLeagueId);
  } else if (filtered.length > 0) {
    state.activeLeagueId = Number(filtered[0].LeagueID);
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
          showToast("Switched to 2026 ECGC Men's Twilight League!");
        }
      })
    );
  }

  const runEcgcSync = guarded(async () => {
    showToast("Synchronizing 2018???2026 ECGC historical league data...");
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
      closeBreakdownModal();
      closeCareerDrawer();
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
    if (badge) badge.textContent = `League #${state.activeLeagueId} ?? ${cfg.rule_type || "ecgc_2person_match"}`;
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
        <div class="kpi-sub">9 Hole Pts + Per-Player Net Bonus (+1 &lt;36 ?? 0 =36 ?? -1 &gt;36)</div>
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
      <div class="kpi-value">#${lg.LeagueID} ?? ${lg.LeagueHoles || 9} Holes</div>
      <div class="kpi-sub">${lg.LeagueName || ""} (${rs.LeagueDay || ""} @ ${rs.FirstTeeTime || ""})</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Home Course</div>
      <div class="kpi-value">${c.CourseName || "Edwards County Golf Course"}</div>
      <div class="kpi-sub">Par ${c.front_par || c.total_par || 36} ?? Rating ${c.CourseRating || 34.4} / Slope ${c.SlopeRating || 113}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Teams &amp; Players</div>
      <div class="kpi-value">${(st.teams || []).length} Teams ?? ${players.length} Players</div>
      <div class="kpi-sub">${rs.NumManTeams || 2}-Person Teams ?? ${(st.subs || []).length} Subs</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">League Avg Handicap &amp; ESC</div>
      <div class="kpi-value">${avgHcp} Hcp</div>
      <div class="kpi-sub">${rs.PercentHandicap || 90}% Factor ?? Max ${rs.MaximumHandicap || 18} ?? ${rs.AdjustScoresLabel || "ESC"}</div>
    </div>
    ${extraCard}
  `
  );
}

function renderSplitStandingsView() {
  const splitBox = document.getElementById("splitStandingsContainer");
  const playBox = document.getElementById("playoffsContainer");
  if (!splitBox || !playBox) return;

  if (!isEcgcLeague(state.activeLeagueId) || !state.ecgcStandings) {
    splitBox.classList.add("hidden");
    playBox.classList.add("hidden");
    return;
  }

  if (state.activeSplit === "playoffs") {
    splitBox.classList.add("hidden");
    playBox.classList.remove("hidden");
    const brs = state.ecgcBrackets || [];
    setHtml(
      playBox,
      brs.length > 0
        ? html`
            <div class="panel">
              <div class="panel-header">
                <h2>???? ECGC Official Playoff Brackets (Rounds 1???4)</h2>
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
                        ???? <strong>Champion:</strong> ${b.playoff_champion || "TBD"}<br />
                        ???? <strong>Runner-Up:</strong> ${b.playoff_runner_up || "TBD"}<br />
                        ???? <strong>Finalists:</strong> ${b.playoff_finalists || "-"}
                      </div>
                    </div>
                  `
                )}
              </div>
            </div>
          `
        : html`<div class="panel"><div class="brand-sub">No playoff bracket recorded for this season-division.</div></div>`
    );
    return;
  }

  playBox.classList.add("hidden");
  const rows = state.ecgcStandings[state.activeSplit] || [];
  if (rows.length === 0) {
    splitBox.classList.add("hidden");
    return;
  }

  splitBox.classList.remove("hidden");
  const splitTitle =
    state.activeSplit === "first_half"
      ? "???? First Half Official Standings"
      : state.activeSplit === "second_half"
      ? "???? Second Half Official Standings"
      : "???? Final Combined Official Standings";

  setHtml(
    splitBox,
    html`
      <div class="panel">
        <div class="panel-header">
          <h2>${splitTitle}</h2>
          <span class="badge gold">${rows.length} Teams</span>
        </div>
        <div class="table-wrap">
          <table>
            <caption class="sr-only">${splitTitle}</caption>
            <thead>
              <tr>
                <th scope="col">Rank</th>
                <th scope="col">Team</th>
                <th scope="col">Players</th>
                <th scope="col" class="num">Total Points</th>
                <th scope="col" class="num">Gross Avg</th>
                <th scope="col" class="num">Net Avg</th>
                <th scope="col" class="num">GB</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map(
                (r) => html`
                  <tr>
                    <td><strong>#${r.rank}</strong></td>
                    <th scope="row"><strong>${r.team_name}</strong></th>
                    <td>${r.players_label}</td>
                    <td class="num"><span class="badge gold">${fmtNum(r.points, 1)} pts</span></td>
                    <td class="num">${fmtNum(r.gross_avg, 1)}</td>
                    <td class="num">${fmtNum(r.net_avg, 1)}</td>
                    <td class="num">${fmtNum(r.games_behind, 1)}</td>
                  </tr>
                `
              )}
            </tbody>
          </table>
        </div>
      </div>
    `
  );
  makeScrollRegionsFocusable(splitBox);
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
      <td class="num">${fmtHcp(t.Handicap)}</td>
      <td class="num">${fmtNum(t.PrevPts)}</td>
      <td class="num"><span class="badge">${fmtNum(t.Points)} pts</span></td>
      <td class="num">${fmtMoney(t.Money)}</td>
    </tr>`
    )}`
  );

  setHtml(
    document.querySelector("#playersLeaderTable tbody"),
    html`${players.map((p, i) => {
      const fullName = `${p.PlayerFirst || ""} ${p.PlayerLast || ""}`.trim();
      const canOpenCareer = isEcgcLeague(state.activeLeagueId) || state.ecgcPlayers.some((ep) => ep.id === Number(p.PlayerID));
      return html`
      <tr>
        <td><strong>#${i + 1}</strong></td>
        <th scope="row">
          ${
            canOpenCareer
              ? html`<button type="button" class="link-btn career-player-btn" data-pid="${p.PlayerID}"><strong>${fullName}</strong> ????</button>`
              : html`<strong>${fullName}</strong>`
          }
        </th>
        <td>Team ${p.TeamID || "-"}</td>
        <td class="num">${fmtHcp(p.Handicap)}</td>
        <td class="num">${fmtNum(p.PrevPts)}</td>
        <td class="num"><span class="badge">${fmtNum(p.Points)} pts</span></td>
        <td class="num">${fmtMoney(p.Money)}</td>
      </tr>`;
    })}`
  );

  document.querySelectorAll(".career-player-btn").forEach((btn) => {
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
      <div class="kpi-label">Handicap &amp; ESC Policy</div>
      <div class="kpi-value">${rs.PercentHandicap || 90}% Over-Par (Max ${rs.MaximumHandicap || 18})</div>
      <div class="kpi-sub">Plus-Handicaps Enabled (+1..+10) ?? Weekly PT Progression (HCP = Prev - PT)</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">9-Hole Team Match Play Points</div>
      <div class="kpi-value">1.0 Hole Win / 0.5 Tie (9.0 Max)</div>
      <div class="kpi-sub">2-Person Combined Gross vs Team Handicap Differential on Holes 1???9</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Per-Player Net Bonus / Penalty (PT)</div>
      <div class="kpi-value">+1 (&lt;36 Net) ?? 0 (=36) ?? -1 (&gt;36)</div>
      <div class="kpi-sub">Awarded per player: if both teammates shoot 34 net, team earns +2 bonus pts!</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Tee Times &amp; Divisions</div>
      <div class="kpi-value">${rs.FirstTeeTime || "06:00 PM"} (${rs.MinsBetweenGroups || 9}m)</div>
      <div class="kpi-sub">${(rs.Divisions || []).join(" / ")}</div>
    </div>
  `
  );
}

async function openCareerDrawer(playerId) {
  const data = await api(`/api/ecgc/players/${playerId}`);
  const drawer = document.getElementById("playerCareerDrawer");
  const titleEl = document.getElementById("careerDrawerTitle");
  const metaEl = document.getElementById("careerPlayerMeta");
  const bodyEl = document.getElementById("careerDrawerContent");
  if (!drawer || !bodyEl) return;

  const p = data.player || {};
  const seasons = data.season_summary || [];
  const rounds = data.rounds || [];
  if (titleEl) titleEl.textContent = `${p.display_name || "Player"} ??? Career Profile (2018???2026)`;
  if (metaEl) metaEl.textContent = `Division: ${(p.primary_division || "mens").toUpperCase()} ?? ${data.career_seasons || 0} Seasons ?? ${rounds.length} Recent Rounds Shown`;

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
                    <td>${s.league_slug}</td>
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
}

async function openBreakdownModal(matchId) {
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
              <th scope="col">Player</th>
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
}

async function loadWeekScorecard() {
  const sc = await api(`/api/leagues/${state.activeLeagueId}/week/${state.activeWeek}`);
  state.scorecard = sc;
  const holesMeta = sc.holes_meta || [];
  document.getElementById("weekCourseBadge").textContent = `${sc.course?.CourseName || "Course"} ?? ${sc.num_holes} Holes`;

  setHtml(
    document.getElementById("caddyPlayerSelect"),
    html`${(sc.scorecards || []).map(
      (c) => html`<option value="${c.PlayerID}">${c.PlayerName} (T${c.TeamID} ?? Hcp ${fmtHcp(c.Handicap)})</option>`
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
          html`<th scope="col" class="hole-cell"><abbr title="Hole ${h.hole}">H${h.hole}</abbr><div class="brand-sub">P${h.par}??#${h.handicap_rank}</div></th>`
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

  setHtml(
    tbody,
    html`${(sc.scorecards || []).map((row) => {
      const name = row.PlayerName || `Player ${row.PlayerID}`;
      const holeInputs = row.holes.map((val, idx) => {
        const strokes = row.strokes_received[idx] || 0;
        const holeNo = holesMeta[idx]?.hole ?? idx + 1;
        const dotStr = strokes > 0 ? "???".repeat(strokes) : strokes < 0 ? "+" + Math.abs(strokes) : "";
        const label = `${name}, hole ${holeNo} score${strokes ? `, handicap strokes ${strokes}` : ""}`;
        return html`<td class="hole-cell">
            <span class="stroke-dots" aria-hidden="true" title="${strokes} handicap stroke(s)">${dotStr}</span>
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
          <td class="num"><input type="number" min="0" max="18" class="stat-input gir-inp" value="${row.GreensInRegulation || 0}" aria-label="${name}, greens in regulation" /></td>
          <td class="num"><input type="number" step="0.5" class="stat-input pts-inp" value="${row.IndividualPts || 0}" aria-label="${name}, individual points" /></td>
          <td><button type="button" class="primary save-score-btn" data-pid="${row.PlayerID}" aria-label="Save scores for ${name}">Save</button></td>
        </tr>
      `;
    })}`
  );

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
            <button type="button" class="btn small open-breakdown-btn" data-mid="${em.match_id}">???? 9-Hole &amp; PT Breakdown</button>
          </div>
        </div>`
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
              <strong>${m.PlayerA_Name} (T${m.PlayerA_Team} ?? Hcp ${fmtHcp(m.PlayerA_Hcp)})</strong>
              <span class="badge">${m.computed_pts_a} pts (${m.holes_won_a}W)</span>
            </div>
            <div class="matchup-row">
              <strong>${m.PlayerB_Name} (T${m.PlayerB_Team} ?? Hcp ${fmtHcp(m.PlayerB_Hcp)})</strong>
              <span class="badge">${m.computed_pts_b} pts (${m.holes_won_b}W)</span>
            </div>
            <div class="matchup-status">${m.status} ?? ${m.holes_halved} Halved</div>
          </div>`
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
          (s) => html`<div class="skin-pill"><strong>Hole #${s.hole}</strong> (Par ${s.par}): ${s.player} ??? <span class="badge gold">${s.score} Gross</span></div>`
        )}`
      : html`<div class="brand-sub"><span role="status">No outright gross skins on this week's card.</span></div>`
  );

  const nSkins = sc.net_skins || [];
  setHtml(
    document.getElementById("netSkinsBox"),
    nSkins.length > 0
      ? html`${nSkins.map(
          (s) => html`<div class="skin-pill"><strong>Hole #${s.hole}</strong> (Par ${s.par}): ${s.player} ??? <span class="badge gold">${s.net_score} Net</span></div>`
        )}`
      : html`<div class="brand-sub"><span role="status">No outright net skins on this week's card.</span></div>`
  );

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
  metaEl.textContent = `Hole #${hm.hole} ?? Par ${hm.par} ?? ${hm.yards} yds ?? Stroke Index #${hm.handicap_rank} (${strokes} Pop${strokes === 1 ? "" : "s"})`;
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
    }),
  });
  showToast(`Saved Week ${state.activeWeek} scorecard for Player #${pid}!`);
  await refreshLeagueData();
}

function renderRosterTab(st) {
  const subs = st.subs || [];
  const fees = st.fees || [];

  setHtml(
    document.querySelector("#subsTable tbody"),
    html`${subs.map(
      (s) => html`
    <tr>
      <td>#${s.SubID}</td>
      <th scope="row"><strong>${s.SubFirst || ""} ${s.SubLast || ""}</strong></th>
      <td class="num">${fmtHcp(s.Handicap)}</td>
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
      <th scope="row">${f.PlayerFirst || ""} ${f.PlayerLast || ""}</th>
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
    html`${sched.map(
      (w) => html`
    <tr>
      <th scope="row"><strong>Week ${w.WeekNum}</strong></th>
      <td>${String(w.Date || "").split(" ")[0]}</td>
      <td>Half ${w.Half || 1}</td>
      <td>${w.Weather || "Clear"}</td>
      <td>${w.Match1Label || ""}</td>
      <td>${w.Match2Label || ""}</td>
      <td><button type="button" class="open-wk-btn" data-wk="${w.WeekNum}" aria-label="Open Scorecard for Week ${w.WeekNum}">Open Scorecard <span aria-hidden="true">???</span></button></td>
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
            <h2><span aria-hidden="true">???</span> ${c.CourseName} (${c.CourseCity || c.City || "Kinsley"}, ${c.CourseState || c.State || "KS"})</h2>
            <div class="brand-sub">Course Rating: ${c.CourseRating} ?? Slope Rating: ${c.SlopeRating} ?? Front Par ${c.front_par} / Back Par ${c.back_par} (Total Par ${c.total_par})</div>
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

window.addEventListener(
  "DOMContentLoaded",
  guarded(() => initApp())
);

// Exposed for automated XSS regression tests.
window.__gls = { escapeHtml, html, SafeHtml };

