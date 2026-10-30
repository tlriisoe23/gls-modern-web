const state = {
  leagues: [],
  activeLeagueId: 10,
  standings: null,
  activeWeek: 1,
  scorecard: null,
  courses: [],
  tables: [],
};

function showToast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 3200);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`API ${res.status}: ${txt}`);
  }
  return res.json();
}

function fmtMoney(v) {
  const n = Number(v || 0);
  return "$" + n.toFixed(2);
}

function fmtNum(v, d = 1) {
  const n = Number(v || 0);
  return Number.isInteger(n) ? String(n) : n.toFixed(d);
}

async function initApp() {
  const themeSel = document.getElementById("themeSelect");
  themeSel.addEventListener("change", () => {
    document.documentElement.setAttribute("data-theme", themeSel.value);
  });

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      const target = btn.dataset.tab;
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.add("hidden"));
      document.getElementById(`tab-${target}`).classList.remove("hidden");
    });
  });

  const lgData = await api("/api/leagues");
  state.leagues = lgData.leagues || [];
  const lgSel = document.getElementById("leagueSelect");
  lgSel.innerHTML = state.leagues
    .map(
      (l) =>
        `<option value="${l.LeagueID}">League #${l.LeagueID}: ${l.LeagueName} (${l.LeagueHoles}H · ${l.player_count} Players)</option>`
    )
    .join("");
  if (state.leagues.length > 0) {
    const has10 = state.leagues.some((l) => Number(l.LeagueID) === 10);
    state.activeLeagueId = has10 ? 10 : Number(state.leagues[0].LeagueID);
    lgSel.value = String(state.activeLeagueId);
  }

  lgSel.addEventListener("change", async () => {
    state.activeLeagueId = Number(lgSel.value);
    state.activeWeek = 1;
    await refreshLeagueData();
  });

  document.getElementById("weekSelect").addEventListener("change", async (e) => {
    state.activeWeek = Number(e.target.value);
    await loadWeekScorecard();
  });

  document.getElementById("recalcHcpBtn").addEventListener("click", async () => {
    const res = await api(`/api/leagues/${state.activeLeagueId}/recalculate-handicaps`, {
      method: "POST",
    });
    showToast(`Recalculated ESC handicaps for ${res.updated_players} players!`);
    await refreshLeagueData();
  });

  document.getElementById("printSheetBtn").addEventListener("click", () => {
    window.print();
  });

  document.getElementById("toggleCaddyBtn").addEventListener("click", () => {
    document.getElementById("caddyModeBox").classList.toggle("hidden");
  });

  document.getElementById("autoScoreMatchesBtn").addEventListener("click", async () => {
    await api(`/api/leagues/${state.activeLeagueId}/week/${state.activeWeek}/auto-score-matches`, {
      method: "POST",
    });
    showToast(`Auto-scored Week ${state.activeWeek} Head-to-Head Match Play & Standings!`);
    await refreshLeagueData();
  });

  document.getElementById("mdbUploadInput").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    showToast(`Importing ${file.name}...`);
    const res = await api("/api/import/mdb", { method: "POST", body: fd });
    showToast(`Migrated ${res.migrated_count} tables from ${file.name}!`);
    await initApp();
  });

  document.getElementById("playerForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      PlayerID: document.getElementById("pfPlayerID").value
        ? Number(document.getElementById("pfPlayerID").value)
        : null,
      PlayerFirst: document.getElementById("pfFirst").value.trim(),
      PlayerLast: document.getElementById("pfLast").value.trim(),
      TeamID: Number(document.getElementById("pfTeam").value || 1),
      Handicap: Number(document.getElementById("pfHcp").value || 0),
      Points: Number(document.getElementById("pfPts").value || 0),
      Money: Number(document.getElementById("pfMoney").value || 0),
      EMail: document.getElementById("pfEmail").value.trim(),
      HomePhone: document.getElementById("pfPhone").value.trim(),
    };
    await api(`/api/leagues/${state.activeLeagueId}/players`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    showToast(`Saved player ${payload.PlayerFirst} ${payload.PlayerLast}`);
    e.target.reset();
    document.getElementById("pfPlayerID").value = "";
    await refreshLeagueData();
  });

  document.getElementById("genSchedBtn").addEventListener("click", async () => {
    const weeks = Number(document.getElementById("schedWeeksInput").value || 16);
    const start_date = document.getElementById("schedStartInput").value || "2026-05-05";
    const res = await api(`/api/leagues/${state.activeLeagueId}/schedule/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ weeks, start_date }),
    });
    showToast(`Generated ${res.generated_weeks}-week round-robin schedule!`);
    await loadScheduleTab();
  });

  setupCaddyModeHandlers();

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
  const totalPrizeMoney = (st.players || []).reduce((acc, p) => acc + Number(p.Money || 0), 0);
  const avgHcp =
    (st.players || []).length > 0
      ? (st.players.reduce((a, p) => a + Number(p.Handicap || 0), 0) / st.players.length).toFixed(1)
      : "0.0";

  document.getElementById("kpiStrip").innerHTML = `
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
      <div class="kpi-value">${(st.teams || []).length} Teams · ${(st.players || []).length} Players</div>
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
  `;
}

function renderStandingsTab(st) {
  const teams = st.teams || [];
  const players = st.players || [];
  const rs = st.rules_summary || {};

  document.getElementById("teamMetaBadge").textContent = `${teams.length} Teams`;
  document.getElementById("playerMetaBadge").textContent = `${players.length} Players`;

  const tBody = document.querySelector("#teamsTable tbody");
  tBody.innerHTML = teams
    .map(
      (t, i) => `
    <tr>
      <td><strong>#${i + 1}</strong></td>
      <td>Team ${t.TeamID}</td>
      <td><strong>${t.TeamName || "Team " + t.TeamID}</strong></td>
      <td>${t.Division ?? 1}</td>
      <td class="num">${fmtNum(t.Handicap)}</td>
      <td class="num">${fmtNum(t.PrevPts)}</td>
      <td class="num"><span class="badge">${fmtNum(t.Points)} pts</span></td>
      <td class="num">${fmtMoney(t.Money)}</td>
    </tr>
  `
    )
    .join("");

  const pBody = document.querySelector("#playersLeaderTable tbody");
  pBody.innerHTML = players
    .map(
      (p, i) => `
    <tr>
      <td><strong>#${i + 1}</strong></td>
      <td><strong>${p.PlayerFirst || ""} ${p.PlayerLast || ""}</strong></td>
      <td>Team ${p.TeamID || "-"}</td>
      <td class="num">${fmtNum(p.Handicap)}</td>
      <td class="num">${fmtNum(p.PrevPts)}</td>
      <td class="num"><span class="badge">${fmtNum(p.Points)} pts</span></td>
      <td class="num">${fmtMoney(p.Money)}</td>
    </tr>
  `
    )
    .join("");

  document.getElementById("leagueRulesSummary").innerHTML = `
    <div class="kpi-card">
      <div class="kpi-label">Handicap &amp; ESC Policy</div>
      <div class="kpi-value">${rs.PercentHandicap || 90}% Over-Par (Max ${rs.MaximumHandicap || 18})</div>
      <div class="kpi-sub">ESC Cap: ${rs.AdjustScoresLabel || "Double Bogey Max"} · Sub Factor: ${rs.SubPercent || 100}%</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Match Play Points (` + "`LeagueRules`" + `)</div>
      <div class="kpi-value">${rs.HolePts || 1} Hole / ${rs.IndMatchPts || 2} Match</div>
      <div class="kpi-sub">Team Match Bonus: ${rs.TeamMatchPts || 4} pts · Field Top: ${rs.FieldTopPts || 0} pts</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Season Dues &amp; Fees (` + "`*LeagueFees`" + `)</div>
      <div class="kpi-value">${fmtMoney(rs.GreenFees)} Green / ${fmtMoney(rs.LeagueFee)} League</div>
      <div class="kpi-sub">Skins: ${fmtMoney(rs.SkinsFee)} · Banquet: ${fmtMoney(rs.BanquetFee)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Tee Times &amp; Divisions</div>
      <div class="kpi-value">${rs.FirstTeeTime || "05:00 PM"} (${rs.MinsBetweenGroups || 9}m)</div>
      <div class="kpi-sub">${(rs.Divisions || []).join(" / ")}</div>
    </div>
  `;
}

async function loadWeekScorecard() {
  const sc = await api(`/api/leagues/${state.activeLeagueId}/week/${state.activeWeek}`);
  state.scorecard = sc;
  const holesMeta = sc.holes_meta || [];
  document.getElementById("weekCourseBadge").textContent = `${sc.course?.CourseName || "Course"} · ${sc.num_holes} Holes`;

  // Populate Mobile Caddy selects
  const caddyPlayerSel = document.getElementById("caddyPlayerSelect");
  caddyPlayerSel.innerHTML = (sc.scorecards || [])
    .map((c) => `<option value="${c.PlayerID}">${c.PlayerName} (T${c.TeamID} · Hcp ${fmtNum(c.Handicap)})</option>`)
    .join("");
  const caddyHoleSel = document.getElementById("caddyHoleSelect");
  caddyHoleSel.innerHTML = holesMeta
    .map((h, i) => `<option value="${i}">Hole #${h.hole} (Par ${h.par})</option>`)
    .join("");
  updateCaddyHoleMeta();

  const thead = document.querySelector("#scorecardTable thead");
  const tbody = document.querySelector("#scorecardTable tbody");

  const holeHeaders = holesMeta
    .map((h) => `<th class="hole-cell">H${h.hole}<div class="brand-sub">P${h.par}·#${h.handicap_rank}</div></th>`)
    .join("");

  thead.innerHTML = `
    <tr>
      <th>Player</th>
      <th>Team</th>
      <th class="num">Hcp</th>
      ${holeHeaders}
      <th class="num">Front</th>
      ${sc.num_holes > 9 ? '<th class="num">Back</th>' : ""}
      <th class="num">Gross</th>
      <th class="num" title="Equitable Stroke Control Adjusted Score">ESC Adj</th>
      <th class="num">Net</th>
      <th class="num">+/-</th>
      <th class="num" title="Modified Stableford Net Points">Stbl</th>
      <th class="num">Putts</th>
      <th class="num">GIR</th>
      <th class="num">Pts</th>
      <th>Save</th>
    </tr>
  `;

  tbody.innerHTML = (sc.scorecards || [])
    .map((row) => {
      const holeInputs = row.holes
        .map((val, idx) => {
          const dots = "•".repeat(row.strokes_received[idx] || 0);
          return `<td class="hole-cell">
            <span class="stroke-dots" title="${row.strokes_received[idx]} handicap stroke(s)">${dots}</span>
            <input type="number" min="0" max="15" class="score-input" data-pid="${row.PlayerID}" data-hidx="${idx}" value="${val || ""}" placeholder="-" />
          </td>`;
        })
        .join("");

      const overStr = row.Gross > 0 ? (row.OverPar > 0 ? `+${row.OverPar}` : String(row.OverPar)) : "-";
      const adjStr = row.AdjGross > 0 ? `${row.AdjGross}${row.ESC_CappedStrokes > 0 ? " (-" + row.ESC_CappedStrokes + ")" : ""}` : "-";
      return `
        <tr data-row-pid="${row.PlayerID}">
          <td><strong>${row.PlayerName}</strong></td>
          <td>T${row.TeamID || "-"}</td>
          <td class="num">${fmtNum(row.Handicap)}</td>
          ${holeInputs}
          <td class="num"><strong>${row.FrontNine || "-"}</strong></td>
          ${sc.num_holes > 9 ? `<td class="num"><strong>${row.BackNine || "-"}</strong></td>` : ""}
          <td class="num"><span class="badge">${row.Gross || "-"}</span></td>
          <td class="num">${adjStr}</td>
          <td class="num"><span class="badge gold">${row.Net || "-"}</span></td>
          <td class="num">${overStr}</td>
          <td class="num">${row.Gross > 0 ? row.StablefordNet : "-"}</td>
          <td class="num"><input type="number" class="stat-input putts-inp" value="${row.NumPutts || 0}" /></td>
          <td class="num"><input type="number" class="stat-input gir-inp" value="${row.GreensInRegulation || 0}" /></td>
          <td class="num"><input type="number" step="0.5" class="stat-input pts-inp" value="${row.IndividualPts || 0}" /></td>
          <td><button class="primary save-score-btn" data-pid="${row.PlayerID}">Save</button></td>
        </tr>
      `;
    })
    .join("");

  tbody.querySelectorAll(".save-score-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const pid = Number(btn.dataset.pid);
      const tr = tbody.querySelector(`tr[data-row-pid="${pid}"]`);
      const holes = Array.from(tr.querySelectorAll(".score-input")).map((inp) => Number(inp.value || 0));
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
    });
  });

  // Render Head-to-Head Matchup Pairings
  const matchups = sc.matchups || [];
  document.getElementById("matchupsCountBadge").textContent = `${matchups.length} Pairings`;
  const mBox = document.getElementById("matchupsBox");
  mBox.innerHTML =
    matchups.length > 0
      ? matchups
          .map(
            (m) => `
        <div class="matchup-card">
          <div class="matchup-row">
            <strong>${m.PlayerA_Name} (T${m.PlayerA_Team} · Hcp ${fmtNum(m.PlayerA_Hcp)})</strong>
            <span class="badge">${m.computed_pts_a} pts (${m.holes_won_a}W)</span>
          </div>
          <div class="matchup-row">
            <strong>${m.PlayerB_Name} (T${m.PlayerB_Team} · Hcp ${fmtNum(m.PlayerB_Hcp)})</strong>
            <span class="badge">${m.computed_pts_b} pts (${m.holes_won_b}W)</span>
          </div>
          <div class="kpi-sub" style="margin-top:6px;border-top:1px solid var(--border);padding-top:6px">
            <strong>${m.status}</strong> · Halved Holes: ${m.holes_halved} · Net: ${m.PlayerA_Net || "-"} vs ${m.PlayerB_Net || "-"}
          </div>
        </div>`
          )
          .join("")
      : `<div class="brand-sub">Individual Flight mode (Field Points awarded across all golfers).</div>`;

  // Render Gross & Net Skins
  const gBox = document.getElementById("grossSkinsBox");
  gBox.innerHTML =
    (sc.gross_skins || []).length > 0
      ? sc.gross_skins
          .map(
            (s) => `
        <div class="skin-card">
          <div class="kpi-label">Hole #${s.hole} (Par ${s.par})</div>
          <div class="kpi-value">${s.player}</div>
          <div class="kpi-sub">Gross Score: <strong>${s.score}</strong></div>
        </div>`
          )
          .join("")
      : `<div class="brand-sub">No outright Gross Skins on Week ${state.activeWeek} (all low scores tied or no scores entered).</div>`;

  const nBox = document.getElementById("netSkinsBox");
  nBox.innerHTML =
    (sc.net_skins || []).length > 0
      ? sc.net_skins
          .map(
            (s) => `
        <div class="skin-card">
          <div class="kpi-label">Hole #${s.hole} (Par ${s.par})</div>
          <div class="kpi-value">${s.player}</div>
          <div class="kpi-sub">Net Score: <strong>${s.net_score}</strong></div>
        </div>`
          )
          .join("")
      : `<div class="brand-sub">No outright Net Skins on Week ${state.activeWeek}.</div>`;
}

function renderRosterTab(st) {
  const subs = st.subs || [];
  const fees = st.fees || [];
  const pMap = {};
  (st.players || []).forEach((p) => {
    pMap[p.PlayerID] = `${p.PlayerFirst || ""} ${p.PlayerLast || ""}`.trim();
  });

  document.querySelector("#subsTable tbody").innerHTML = subs
    .map(
      (s) => `
    <tr>
      <td>#${s.SubID}</td>
      <td><strong>${s.SubFirst || ""} ${s.SubLast || ""}</strong></td>
      <td class="num">${fmtNum(s.Handicap)}</td>
      <td class="num">${fmtNum(s.Points)}</td>
      <td class="num">${fmtMoney(s.Money)}</td>
      <td>${s.HomePhone || s.WorkPhone || "-"}</td>
    </tr>
  `
    )
    .join("");

  document.querySelector("#feesTable tbody").innerHTML = fees
    .map(
      (f) => `
    <tr>
      <td>#${f.PlayerID}</td>
      <td><strong>${pMap[f.PlayerID] || "Player #" + f.PlayerID}</strong></td>
      <td class="num">${fmtMoney(f.GreenFees)}</td>
      <td class="num">${fmtMoney(f.LeagueFee)}</td>
      <td class="num">${fmtMoney(f.SkinsFee)}</td>
      <td class="num">${fmtMoney(f.BanquetFee)}</td>
      <td class="num">${fmtMoney(f.ExtraFee)}</td>
    </tr>
  `
    )
    .join("");
}

async function loadScheduleTab() {
  const data = await api(`/api/leagues/${state.activeLeagueId}/schedule`);
  const sched = data.schedule || [];
  const wkSel = document.getElementById("weekSelect");
  const maxWk = Math.max(17, sched.length);
  const opts = [];
  for (let w = 1; w <= maxWk; w++) {
    const row = sched.find((r) => Number(r.WeekNum) === w);
    const dtLabel = row?.Date ? String(row.Date).split(" ")[0] : "";
    opts.push(`<option value="${w}">Week ${w}${dtLabel ? " (" + dtLabel + ")" : ""}</option>`);
  }
  wkSel.innerHTML = opts.join("");
  wkSel.value = String(state.activeWeek);

  document.querySelector("#scheduleTable tbody").innerHTML = sched
    .map(
      (w) => `
    <tr>
      <td><strong>Week ${w.WeekNum}</strong></td>
      <td>${String(w.Date || "").split(" ")[0]}</td>
      <td>Half ${w.Half || 1}</td>
      <td>${w.Weather || "Clear"}</td>
      <td>${w.Match1Label || ""}</td>
      <td>${w.Match2Label || ""}</td>
      <td><button class="open-wk-btn" data-wk="${w.WeekNum}">Open Scorecard →</button></td>
    </tr>
  `
    )
    .join("");

  document.querySelectorAll(".open-wk-btn").forEach((b) => {
    b.addEventListener("click", async () => {
      state.activeWeek = Number(b.dataset.wk);
      document.getElementById("weekSelect").value = String(state.activeWeek);
      document.querySelector('.tab-btn[data-tab="scorecard"]').click();
      await loadWeekScorecard();
    });
  });
}

async function loadCoursesTab() {
  const data = await api("/api/courses");
  state.courses = data.courses || [];
  const box = document.getElementById("coursesContainer");
  box.innerHTML = state.courses
    .map((c) => {
      const hCols = c.holes.map((h) => `<th class="num">H${h.hole}</th>`).join("");
      const pCols = c.holes.map((h) => `<td class="num"><strong>${h.par}</strong></td>`).join("");
      const yCols = c.holes.map((h) => `<td class="num">${h.yards}</td>`).join("");
      const rCols = c.holes.map((h) => `<td class="num"><span class="badge gold">#${h.handicap_rank}</span></td>`).join("");
      return `
      <div class="panel">
        <div class="panel-header">
          <div>
            <h2>⛳ ${c.CourseName} (${c.City || ""}, ${c.State || ""})</h2>
            <div class="brand-sub">Course Rating: ${c.CourseRating} · Slope Rating: ${c.SlopeRating} · Front Par ${c.front_par} / Back Par ${c.back_par} (Total Par ${c.total_par})</div>
          </div>
          <span class="badge">Course ID #${c.CourseID}</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Metric</th>${hCols}<th class="num">Front 9</th><th class="num">Back 9</th><th class="num">Total</th></tr>
            </thead>
            <tbody>
              <tr><td><strong>Par</strong></td>${pCols}<td class="num">${c.front_par}</td><td class="num">${c.back_par}</td><td class="num"><strong>${c.total_par}</strong></td></tr>
              <tr><td><strong>Yards</strong></td>${yCols}<td class="num">${c.holes.slice(0,9).reduce((a,x)=>a+x.yards,0)}</td><td class="num">${c.holes.slice(9,18).reduce((a,x)=>a+x.yards,0)}</td><td class="num">${c.holes.reduce((a,x)=>a+x.yards,0)}</td></tr>
              <tr><td><strong>Handicap Stroke Index</strong></td>${rCols}<td class="num">-</td><td class="num">-</td><td class="num">1..18</td></tr>
            </tbody>
          </table>
        </div>
      </div>`;
    })
    .join("");
}

async function loadExplorerTab() {
  const data = await api("/api/tables");
  state.tables = data.tables || [];
  const sel = document.getElementById("rawTableSelect");
  sel.innerHTML = state.tables
    .map((t) => `<option value="${t.name}">${t.name} (${t.row_count} rows)</option>`)
    .join("");
  document.getElementById("rawTableCountBadge").textContent = `${data.table_count} SQLite Tables`;

  sel.addEventListener("change", () => inspectRawTable(sel.value));
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
    thead.innerHTML = "<tr><th>Empty Table</th></tr>";
    tbody.innerHTML = `<tr><td class="brand-sub">Table "${tableName}" has 0 rows.</td></tr>`;
    return;
  }
  const cols = Object.keys(rows[0]);
  thead.innerHTML = `<tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr>`;
  tbody.innerHTML = rows
    .map(
      (r) =>
        `<tr>${cols
          .map((c) => `<td>${r[c] === null || r[c] === undefined ? "" : String(r[c])}</td>`)
          .join("")}</tr>`
    )
    .join("");
}

window.addEventListener("DOMContentLoaded", initApp);
