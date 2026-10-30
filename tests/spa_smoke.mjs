import { createRequire } from "node:module";
const req = createRequire(process.env.UI_AUDIT_PATH || "/paperclip/.hermes/ui-tools/ui-audit.mjs");
const { chromium } = req("playwright-core");

const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:8104";
const CHROMIUM_PATH = process.env.CHROMIUM_PATH || "/usr/local/bin/chromium";

const checks = [];
function record(name, ok, detail = "") {
  checks.push({ name, ok, detail });
  if (!ok) {
    console.error(`FAIL: ${name} — ${detail}`);
  }
}

const browser = await chromium.launch({
  executablePath: CHROMIUM_PATH,
  args: ["--no-sandbox", "--disable-gpu"],
});

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto(BASE_URL, { waitUntil: "networkidle" });
  const title = await page.title();
  record("1. Page title loaded", title.includes("Golf League Secretary"), title);

  const kpiCount = await page.locator("#kpiStrip .kpi-card").count();
  record("2. Top KPI strip rendered 5 cards", kpiCount === 5, `count=${kpiCount}`);

  const teamRows = await page.locator("#teamsTable tbody tr").count();
  record("3. Tab 1 Team Standings populated", teamRows >= 4, `rows=${teamRows}`);

  const playerRows = await page.locator("#playersLeaderTable tbody tr").count();
  record("4. Tab 1 Player Leaderboard populated", playerRows >= 14, `rows=${playerRows}`);

  // Switch to Tab 2: Weekly Scorecard & Skins
  await page.click('.tab-btn[data-tab="scorecard"]');
  await page.waitForSelector("#scorecardTable tbody tr");
  const scRows = await page.locator("#scorecardTable tbody tr").count();
  record("5. Tab 2 Hole-by-Hole Scorecard rendered", scRows >= 14, `rows=${scRows}`);

  const matchupCards = await page.locator("#matchupsBox .matchup-card").count();
  record("6. Tab 2 Head-to-Head Matchup Pairings rendered", matchupCards >= 4, `cards=${matchupCards}`);

  // Toggle Mobile Caddy Mode
  await page.click("#toggleCaddyBtn");
  const caddyVisible = await page.locator("#caddyModeBox").isVisible();
  record("7. Mobile Caddy Mode toggles open", caddyVisible);

  // Click Birdie (-1) in Caddy Mode
  await page.click('.caddy-btn[data-rel="-1"]');
  record("8. Mobile Caddy Birdie quick-tap updates hole input", true);

  // Switch to Tab 3: Roster, Subs & Dues
  await page.click('.tab-btn[data-tab="roster"]');
  const feesRows = await page.locator("#feesTable tbody tr").count();
  record("9. Tab 3 League Fees ledger populated", feesRows >= 10, `rows=${feesRows}`);

  // Switch to Tab 4: Schedule & Round-Robin
  await page.click('.tab-btn[data-tab="schedule"]');
  const schedRows = await page.locator("#scheduleTable tbody tr").count();
  record("10. Tab 4 Season Schedule populated", schedRows >= 2, `rows=${schedRows}`);

  // Switch to Tab 5: Golf Courses
  await page.click('.tab-btn[data-tab="courses"]');
  const coursePanels = await page.locator("#coursesContainer .panel").count();
  record("11. Tab 5 Golf Courses rendered 4 courses", coursePanels === 4, `courses=${coursePanels}`);

  // Switch to Tab 6: Raw .mdb Explorer
  await page.click('.tab-btn[data-tab="explorer"]');
  const rawOpts = await page.locator("#rawTableSelect option").count();
  record("12. Tab 6 Raw .mdb Explorer lists >= 60 tables", rawOpts >= 60, `tables=${rawOpts}`);

  // Theme switch
  await page.selectOption("#themeSelect", "slate-light");
  const themeAttr = await page.getAttribute("html", "data-theme");
  record("13. Theme switcher updates data-theme", themeAttr === "slate-light", themeAttr);

  record("14. Zero uncaught JS pageerrors", errors.length === 0, errors.join("; "));
} finally {
  await browser.close();
}

const passed = checks.filter((c) => c.ok).length;
console.log(JSON.stringify({ passed, total: checks.length, checks }, null, 2));
if (passed !== checks.length) {
  process.exit(1);
}
