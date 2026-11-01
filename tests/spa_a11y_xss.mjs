// Browser-level XSS + WCAG 2.2 AA regression checks for the GLS9 SPA.
//
//   BASE_URL=http://127.0.0.1:8104 node tests/spa_a11y_xss.mjs
//
// Optional: AXE_CORE_PATH=/path/to/node_modules/axe-core/axe.min.js runs a full axe-core
// WCAG 2.0/2.1/2.2 A+AA scan of every workspace tab in every theme as well.
// Run via tests/test_spa_browser.py, which starts a server on a throwaway DB copy.
import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch {
  ({ chromium } = require("playwright-core"));
}

const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:8104";
const LEAGUE = Number(process.env.XSS_LEAGUE || 10);
const AXE_PATH = process.env.AXE_CORE_PATH || "";
const launchOpts = { args: ["--no-sandbox", "--disable-gpu"] };
if (process.env.CHROMIUM_PATH) launchOpts.executablePath = process.env.CHROMIUM_PATH;

const checks = [];
function record(name, ok, detail = "") {
  checks.push({ name, ok: Boolean(ok), detail: String(detail).slice(0, 2000) });
  if (!ok) console.error(`FAIL: ${name} — ${detail}`);
}

const XSS_FIRST = `<img src=x onerror="window.__xss=1">`;
const XSS_LAST = `"><svg onload="window.__xss=2">`;

async function seedXss() {
  const res = await fetch(`${BASE_URL}/api/leagues/${LEAGUE}/players`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ PlayerFirst: XSS_FIRST, PlayerLast: XSS_LAST, TeamID: 1, Handicap: 3 }),
  });
  if (!res.ok) throw new Error(`seed failed: ${res.status} ${await res.text()}`);
}

const browser = await chromium.launch(launchOpts);
try {
  await seedXss();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("dialog", async (d) => {
    errors.push(`unexpected dialog: ${d.message()}`);
    await d.dismiss();
  });

  await page.goto(BASE_URL, { waitUntil: "networkidle" });
  await page.waitForSelector("#playersLeaderTable tbody tr");

  // ---------------------------------------------------------------- XSS
  const leaderText = await page.locator("#playersLeaderTable tbody").innerText();
  record(
    "XSS: payload rendered as literal text in leaderboard",
    leaderText.includes(XSS_FIRST) && leaderText.includes(XSS_LAST),
    leaderText.split("\n").slice(-3).join(" | ")
  );
  // Visit every tab so every renderer runs with the hostile data.
  for (const tab of ["scorecard", "roster", "schedule", "courses", "standings", "explorer"]) {
    await page.click(`.tab-btn[data-tab="${tab}"]`);
  }
  await page.selectOption("#rawTableSelect", `${LEAGUE}Players`);
  await page.waitForFunction((n) => document.querySelector("#rawTableGrid tbody")?.innerText.includes(n), XSS_FIRST);
  const injected = await page.evaluate(() => ({
    flag: window.__xss,
    imgs: document.querySelectorAll('main img[src="x"], option img').length,
    svgs: document.querySelectorAll("main svg[onload]").length,
    handlers: Array.from(document.querySelectorAll("main *")).filter((el) =>
      Array.from(el.attributes).some((a) => a.name.startsWith("on"))
    ).length,
  }));
  record("XSS: no script executed", injected.flag === undefined, JSON.stringify(injected));
  record("XSS: no injected elements / inline handlers in DOM", injected.imgs === 0 && injected.svgs === 0 && injected.handlers === 0, JSON.stringify(injected));
  const unit = await page.evaluate(() => {
    const { escapeHtml, html } = window.__gls;
    return {
      esc: escapeHtml(`<a href="x" onclick='y'>&\``),
      nested: String(html`<b>${["<i>", html`<u>${"<s>"}</u>`]}</b>`),
      nullish: String(html`${null}${undefined}`),
    };
  });
  record("XSS: escapeHtml escapes all metacharacters", unit.esc === "&lt;a href=&quot;x&quot; onclick=&#39;y&#39;&gt;&amp;&#96;", unit.esc);
  record("XSS: html`` escapes nested values but keeps trusted fragments", unit.nested === "<b>&lt;i&gt;<u>&lt;s&gt;</u></b>", unit.nested);
  record("XSS: html`` renders null/undefined as empty", unit.nullish === "", unit.nullish);

  // ---------------------------------------------------------------- Keyboard / ARIA
  await page.reload({ waitUntil: "networkidle" });
  await page.keyboard.press("Tab");
  const firstFocus = await page.evaluate(() => document.activeElement?.className);
  record("A11y 2.4.1: first Tab stop is the skip link", firstFocus === "skip-link", firstFocus);
  await page.keyboard.press("Enter");
  record("A11y 2.4.1: skip link moves focus to <main>", await page.evaluate(() => document.activeElement?.id === "main"));

  await page.focus("#tabbtn-standings");
  await page.keyboard.press("ArrowRight");
  let st = await page.evaluate(() => ({
    focus: document.activeElement?.id,
    selected: document.querySelector('[role="tab"][aria-selected="true"]')?.id,
    paneVisible: !document.getElementById("tab-scorecard").classList.contains("hidden"),
    tabindexes: Array.from(document.querySelectorAll('[role="tab"]')).map((t) => t.tabIndex),
  }));
  record(
    "A11y 2.1.1: ArrowRight moves to & activates next tab (roving tabindex)",
    st.focus === "tabbtn-scorecard" && st.selected === "tabbtn-scorecard" && st.paneVisible && st.tabindexes.filter((t) => t === 0).length === 1,
    JSON.stringify(st)
  );
  await page.keyboard.press("End");
  st = await page.evaluate(() => document.activeElement?.id);
  record("A11y 2.1.1: End jumps to last tab", st === "tabbtn-explorer", st);
  await page.keyboard.press("Home");
  await page.keyboard.press("ArrowLeft");
  st = await page.evaluate(() => document.activeElement?.id);
  record("A11y 2.1.1: ArrowLeft wraps from first to last tab", st === "tabbtn-explorer", st);

  const tabsWired = await page.evaluate(() =>
    Array.from(document.querySelectorAll('[role="tab"]')).every((t) => {
      const panel = document.getElementById(t.getAttribute("aria-controls"));
      return panel && panel.getAttribute("role") === "tabpanel" && panel.getAttribute("aria-labelledby") === t.id;
    })
  );
  record("A11y 4.1.2: every tab controls a labelled tabpanel", tabsWired);

  const fileFocusable = await page.evaluate(() => {
    const el = document.getElementById("mdbUploadInput");
    el.focus();
    return document.activeElement === el && getComputedStyle(el).display !== "none";
  });
  record("A11y 2.1.1: .mdb import control is keyboard-focusable", fileFocusable);

  await page.click("#tabbtn-scorecard");
  const caddy = page.locator("#toggleCaddyBtn");
  const before = await caddy.getAttribute("aria-expanded");
  await caddy.click();
  const after = await caddy.getAttribute("aria-expanded");
  record("A11y 4.1.2: caddy toggle exposes aria-expanded state", before === "false" && after === "true", `${before}->${after}`);

  // Every visible form control & button has an accessible name.
  for (const tab of ["standings", "scorecard", "roster", "schedule", "courses", "explorer"]) {
    await page.click(`#tabbtn-${tab}`);
    const unnamed = await page.evaluate(() => {
      const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) || el.classList.contains("sr-only");
      const name = (el) => {
        if (el.getAttribute("aria-label")) return el.getAttribute("aria-label");
        const lb = el.getAttribute("aria-labelledby");
        if (lb) return lb.split(" ").map((id) => document.getElementById(id)?.textContent || "").join(" ");
        if (el.labels && el.labels.length) return Array.from(el.labels).map((l) => l.textContent).join(" ");
        if (el.tagName === "BUTTON" || el.tagName === "A") return el.textContent;
        return el.getAttribute("title") || "";
      };
      return Array.from(document.querySelectorAll("input:not([type=hidden]), select, button, a[href]"))
        .filter(visible)
        .filter((el) => !name(el).trim())
        .map((el) => el.outerHTML.slice(0, 120));
    });
    record(`A11y 4.1.2/3.3.2: all controls named on "${tab}" tab`, unnamed.length === 0, unnamed.join(" | "));
  }

  const scoreLabel = await page.evaluate(() => {
    document.getElementById("tabbtn-scorecard").click();
    return document.querySelector("#scorecardTable .score-input")?.getAttribute("aria-label") || "";
  });
  record("A11y 1.3.1: score inputs name player + hole", /, hole \d+ score/.test(scoreLabel), scoreLabel);

  // Client-side validation of hole scores is announced, not silently sent.
  const firstInput = page.locator("#scorecardTable .score-input").first();
  await firstInput.fill("25");
  await page.locator("#scorecardTable .save-score-btn").first().click();
  const invalid = await firstInput.getAttribute("aria-invalid");
  const alertText = await page.locator("#toastAlert").textContent();
  record("A11y 3.3.1: invalid score flagged with aria-invalid + alert", invalid === "true" && /between 0 and 20/.test(alertText || ""), `${invalid} / ${alertText}`);

  // Server errors surface to the user instead of failing silently.
  await page.evaluate(() => {
    document.getElementById("tabbtn-roster").click();
    document.getElementById("pfFirst").value = "Ann";
    document.getElementById("pfLast").value = "Lee";
    document.getElementById("pfTeam").value = "99";
  });
  await page.evaluate(() => document.getElementById("pfTeam").removeAttribute("max"));
  await page.click('#playerForm button[type="submit"]');
  await page.waitForFunction(() => /Team 99/.test(document.getElementById("toastAlert").textContent || ""));
  record("Errors: API 422 surfaces as an accessible alert", true);

  // Reflow (1.4.10): no horizontal page scroll at 320 CSS px (tables scroll inside their wrapper).
  await page.setViewportSize({ width: 320, height: 800 });
  await page.click("#tabbtn-standings");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  record("A11y 1.4.10: no horizontal page scroll at 320px", overflow <= 1, `overflow=${overflow}px`);
  await page.setViewportSize({ width: 1440, height: 900 });

  // ---------------------------------------------------------------- axe-core (optional)
  if (AXE_PATH && existsSync(AXE_PATH)) {
    const axeSrc = readFileSync(AXE_PATH, "utf8");
    // Disable CSS transitions (the app honours prefers-reduced-motion) so axe never samples
    // colours mid-transition right after a tab click.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.mouse.move(0, 0);
    for (const theme of ["emerald-dark", "zinc-dark", "slate-light", "cyber-indigo", "sunset-amber"]) {
      await page.selectOption("#themeSelect", theme);
      for (const tab of ["standings", "scorecard", "roster", "schedule", "courses", "explorer"]) {
        await page.click(`#tabbtn-${tab}`);
        await page.evaluate(axeSrc);
        const result = await page.evaluate(async () =>
          // eslint-disable-next-line no-undef
          axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] } })
        );
        const v = result.violations.map((x) => `${x.id}(${x.impact}) x${x.nodes.length}: ${x.nodes[0]?.target?.join(" ")}`);
        record(`axe WCAG 2.2 AA: ${theme} / ${tab}`, v.length === 0, v.join(" | "));
      }
    }
  } else {
    console.log("axe-core not provided (AXE_CORE_PATH); skipping full axe scan");
  }

  record("Zero uncaught JS errors / dialogs", errors.length === 0, errors.join("; "));
} catch (e) {
  record("Unexpected exception", false, e.stack || e);
} finally {
  await browser.close();
}

const passed = checks.filter((c) => c.ok).length;
console.log(JSON.stringify({ passed, total: checks.length, failed: checks.filter((c) => !c.ok) }, null, 2));
process.exit(passed === checks.length ? 0 : 1);
