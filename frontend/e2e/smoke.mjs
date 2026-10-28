/**
 * End-to-end smoke test against a running stack (backend :8000 + frontend :5173).
 * Usage: node e2e/smoke.mjs [baseUrl]   (requires the `playwright` package and a Chromium build)
 * NOTE: it creates records (an inspection, an acknowledgement, a report) in the configured database.
 */
import { createRequire } from "node:module";

// Prefer a local install; fall back to a global one via NODE_PATH.
const { chromium } = await import("playwright").catch(() => createRequire(import.meta.url)("playwright"));

const BASE = process.argv[2] ?? "http://127.0.0.1:5173";
const results = [];
const step = async (name, fn) => {
  try {
    await fn();
    results.push(["PASS", name]);
  } catch (e) {
    results.push(["FAIL", name, e.message.split("\n")[0]]);
  }
};
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1600, height: 950 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

await step("digital twin loads with 3D canvas and record-derived KPIs", async () => {
  await page.goto(`${BASE}/twin`);
  await page.waitForSelector("canvas", { timeout: 20000 });
  await page.waitForFunction(() => document.body.innerText.includes("Components"), null, { timeout: 15000 });
  expect(await page.locator("canvas").count() === 1, "expected one canvas");
});

await step("layer toggle switches state", async () => {
  await page.getByRole("tab", { name: "Layers" }).click();
  const sw = page.getByRole("switch", { name: "Wireframe" });
  await sw.click();
  expect((await sw.getAttribute("aria-checked")) === "true", "wireframe not enabled");
  await sw.click();
});

await step("component tree selection opens component details", async () => {
  await page.getByRole("tab", { name: "Components" }).click();
  await page.getByRole("button", { name: "West pylon", exact: true }).click();
  await page.locator('aside[aria-label="Details"]').getByText("TWR-W", { exact: true }).waitFor({ timeout: 10000 });
});

await step("defect registry → 'Show in 3D' navigates to the twin with evidence open", async () => {
  await page.goto(`${BASE}/defects`);
  await page.waitForSelector('[data-testid="defect-table"] tbody tr', { timeout: 15000 });
  const id = (await page.locator('[data-testid="defect-table"] tbody tr td.mono').first().innerText()).trim();
  await page.getByRole("button", { name: `Show ${id} in 3D` }).click();
  await page.waitForURL(/\/twin$/);
  await page.getByText("Finding evidence").waitFor({ timeout: 10000 });
  await page.locator('aside[aria-label="Details"]').getByText(id).first().waitFor({ timeout: 10000 });
});

await step("priority filter restricts the registry", async () => {
  await page.goto(`${BASE}/defects`);
  await page.waitForSelector('[data-testid="defect-table"] tbody tr');
  await page.getByRole("button", { name: "Critical review", exact: true }).click();
  await page.waitForTimeout(800);
  const badges = await page.locator('[data-testid="defect-table"] tbody tr td:first-child').allInnerTexts();
  expect(badges.length > 0 && badges.every((b) => /critical/i.test(b)), `unexpected rows: ${badges.join(",")}`);
});

await step("image upload creates an inspection with explicit model-unavailable status", async () => {
  const png = await (await fetch(`${BASE}/api/v1/demo-images/crack?seed=7`)).arrayBuffer();
  await page.goto(`${BASE}/inspections`);
  await page.setInputFiles('[data-testid="file-input"]', { name: "upload.png", mimeType: "image/png", buffer: Buffer.from(png) });
  await page.getByRole("button", { name: "Upload & inspect" }).click();
  await page.getByText(/^Inspection INS-/).waitFor({ timeout: 15000 });
  const status = await (await fetch(`${BASE}/api/v1/system/status`)).json();
  if (!status.models.available) await page.getByText("Stored without AI analysis").waitFor();
});

await step("alert acknowledgement is recorded in the audit trail", async () => {
  await page.goto(`${BASE}/alerts`);
  await page.getByRole("button", { name: "acknowledged", exact: true }).click(); // show only open alerts
  await page.locator("table tbody tr").first().click();
  await page.getByPlaceholder("Required for audit trail").fill("e2e.tester");
  await page.getByRole("button", { name: "Acknowledge", exact: true }).click();
  await page.getByText("by e2e.tester").waitFor({ timeout: 10000 });
});

await step("PDF report is generated and downloadable", async () => {
  await page.goto(`${BASE}/reports`);
  await page.getByRole("button", { name: /Generate PDF report/ }).click();
  const link = page.getByRole("link", { name: "PDF" }).first();
  await link.waitFor({ timeout: 30000 });
  const href = await link.getAttribute("href");
  const res = await fetch(`${BASE}${href}`);
  expect(res.ok && res.headers.get("content-type") === "application/pdf", "PDF not served");
  const head = new Uint8Array(await res.arrayBuffer()).slice(0, 5);
  expect(String.fromCharCode(...head) === "%PDF-", "not a PDF");
});

await step("all sections render without page errors", async () => {
  for (const p of ["assets", "devices", "sensors", "history", "settings"]) {
    await page.goto(`${BASE}/${p}`);
    await page.waitForTimeout(1200);
  }
  expect(errors.length === 0, `page errors: ${errors.join(" | ")}`);
});

await browser.close();
for (const r of results) console.log(r.join("  "));
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`\n${results.length - failed}/${results.length} steps passed`);
process.exit(failed ? 1 : 0);
