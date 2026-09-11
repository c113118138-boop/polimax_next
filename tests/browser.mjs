import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import assert from "node:assert/strict";
// Node 18 compatibility: derive the project directory from the test URL.
const project = new URL("../", import.meta.url).pathname;
const dir = await mkdtemp(tmpdir() + "/polimax-browser-");
const port = 18021,
  base = `http://127.0.0.1:${port}`;
const server = spawn(
  project + ".venv/bin/python",
  [
    "-m",
    "uvicorn",
    "app:app",
    "--app-dir",
    project + "backend",
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
  ],
  {
    cwd: project,
    env: {
      ...process.env,
      PREVIEW_DATA_DIR: dir,
      AMS_DATABASE_MODE: "demo",
      PREVIEW_DATABASE_URL: "",
      PREVIEW_LOGIN_ENABLED: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
  },
);
let serverLog = "";
server.stdout.on("data", (b) => (serverLog += b));
server.stderr.on("data", (b) => (serverLog += b));
let browser;
const errors = [];
try {
  for (let i = 0; i < 150; i++) {
    try {
      if ((await fetch(base + "/api/health")).ok) break;
    } catch {}
    if (server.exitCode !== null) throw new Error(serverLog);
    await new Promise((r) => setTimeout(r, 200));
    if (i === 149) throw new Error("Server timeout " + serverLog);
  }
  browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const context = await browser.newContext({
    viewport: process.env.AMS_TEST_MOBILE
      ? { width: 390, height: 844 }
      : { width: 1440, height: 1000 },
    isMobile: !!process.env.AMS_TEST_MOBILE,
    hasTouch: !!process.env.AMS_TEST_MOBILE,
    timezoneId: "America/Los_Angeles",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(base);
  await page.getByRole("button", { name: /進入工作空間/ }).click();
  await page.getByText("每一段行程，都安排妥當。").waitFor();
  console.log("PASS login");
  if (!process.env.AMS_TEST_MOBILE) {
    await page.getByRole("button", { name: "收合側欄", exact: true }).click();
    assert.equal(await page.locator(".sidebar-collapsed").count(), 1);
    await page.getByRole("button", { name: "展開側欄", exact: true }).click();
  }
  assert.equal(await page.getByText("時間顯示：臺北 UTC+8").count(), 1);
  const resources = await (
    await context.request.get(base + "/api/resources")
  ).json();
  const car = resources.find((r) => r.kind === "vehicle");
  await page.goto(base + "/bookings/new/A");
  await page.locator('input[name="title"]').fill("瀏覽器完整流程測試");
  await page.getByRole("button", { name: "下一步" }).click();
  await page.locator('input[name="details.0.name"]').fill("BROWSER-001");
  await page.locator('select[name="details.0.city"]').selectOption("新竹市");
  await page.locator('select[name="details.0.district"]').selectOption("東區");
  await page.getByRole("button", { name: "下一步" }).click();
  await page
    .locator('select[name="slots.0.resource_id"]')
    .selectOption(String(car.id));
  await page.locator('input[name="slots.0.start"]').fill("2027-11-01T09:00:17");
  await page.locator('input[name="slots.0.end"]').fill("2027-11-01T10:00:33");
  await page.getByRole("button", { name: "下一步" }).click();
  await page.getByRole("button", { name: "下一步" }).click();
  assert.match(
    await page.locator(".slot-summary").first().innerText(),
    /11\/01 09:00/,
  );
  await page.getByRole("button", { name: "確認送出", exact: true }).click();
  await page.waitForURL(/\/bookings\/\d/);
  const bookingId = new URL(page.url()).pathname.split("/").at(-1);
  console.log("PASS booking", bookingId);
  const checksB = [
    "擋風玻璃清潔",
    "照後鏡清潔",
    "油量檢查",
    "輪胎檢查",
    "車輛內部清潔",
    "車體外部檢查",
    "隨車設備檢查",
  ];
  const checksC = [
    "車輛內部清潔",
    "車輛內部物品歸位",
    "車輛鑰匙歸位",
    "油量檢查",
    "車體外部檢查",
    "隨車設備檢查",
  ];
  for (const [button, mileage, checks] of [
    ["填寫發車表", 100, checksB],
    ["填寫發車抵達", 120, null],
    ["填寫還車表", 130, checksC],
    ["填寫還車抵達", 155, null],
  ]) {
    await page.getByRole("button", { name: button, exact: true }).click();
    const dialog = page.getByRole("dialog");
    if (checks) {
      await dialog.getByLabel(/^駕駛人員/).selectOption("林品安");
      await dialog.getByLabel(/^(去程|回程)發車地點/).fill("測試廠區");
      for (const label of checks)
        await dialog.getByLabel(label, { exact: true }).check();
    }
    if (button === "填寫還車表") {
      await dialog
        .locator("input[type=file]")
        .first()
        .setInputFiles({
          name: "test-photo.png",
          mimeType: "image/png",
          buffer: Buffer.from(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=",
            "base64",
          ),
        });
      await dialog
        .getByRole("link", { name: "test-photo.png", exact: true })
        .waitFor();
    }
    await dialog.locator("input[type=number]").fill(String(mileage));
    await dialog.getByLabel("我已確認本階段里程").check();
    await dialog.getByRole("button", { name: "確認提交本階段" }).click();
    await dialog.waitFor({ state: "hidden" });
    console.log("PASS stage", button);
  }
  await page.getByText("55.0 km", { exact: true }).waitFor();
  const booking = await (
    await context.request.get(base + "/api/bookings/" + bookingId)
  ).json();
  assert.equal(booking.status, "RETURN_ARRIVED");
  assert.equal(
    booking.stages.find((s) => s.kind === "C").content.start.interior_files
      .length,
    1,
  );
  assert.match(booking.slots[0].start, /09:00:17/);
  await page.getByRole("button", { name: "發車與抵達", exact: true }).click();
  await page.getByRole("link", { name: "查看／修正此階段" }).click();
  await page.getByRole("button", { name: "修正階段內容" }).click();
  const editDialog = page.getByRole("dialog");
  await editDialog.locator("textarea").first().fill("瀏覽器修訂備註");
  await editDialog.getByRole("button", { name: "儲存修訂" }).click();
  await editDialog.waitFor({ state: "hidden" });
  for (const path of [
    "/vehicles",
    "/equipment",
    "/stages",
    "/beacons",
    "/integrations",
    "/positions",
    "/scans",
    "/findmy",
  ]) {
    await page.goto(base + path);
    await page.locator(".page-heading").waitFor();
  }
  await page.getByLabel("定位設備", { exact: true }).selectOption("000b");
  await page.getByText(/major 11/).waitFor();
  await mkdir(project + "test-results", { recursive: true });
  await page.screenshot({
    path:
      project +
      "test-results/findmy-" +
      (process.env.AMS_TEST_MOBILE ? "mobile" : "desktop") +
      ".png",
    fullPage: true,
  });
  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    timezoneId: "Asia/Taipei",
  });
  const phone = await mobile.newPage();
  phone.on("pageerror", (e) => errors.push(e.message));
  await phone.goto(base);
  await phone.getByRole("button", { name: /唯讀使用者/ }).click();
  await phone.getByRole("button", { name: /進入工作空間/ }).click();
  await phone.locator(".calendar-panel").waitFor();
  assert.equal(
    await phone
      .locator("label")
      .filter({ hasText: "測試假日" })
      .last()
      .isVisible(),
    false,
  );
  await phone.getByRole("button", { name: "開啟選單" }).click();
  await phone.getByRole("link", { name: "公務車輛", exact: true }).click();
  await phone.locator(".asset-grid").waitFor();
  assert.equal(await phone.locator(".sidebar.is-open").count(), 0);
  assert.equal(
    await phone.getByRole("button", { name: "新增車輛", exact: true }).count(),
    0,
  );
  await phone.screenshot({
    path: project + "test-results/mobile-assets.png",
    fullPage: true,
  });
  const viewerForms = await (
    await mobile.request.get(base + "/api/bookings")
  ).json();
  assert(!JSON.stringify(viewerForms).includes("機密備註"));
  await phone.goto(base + "/bookings/new/A");
  await phone.getByRole("alert").waitFor();
  assert.deepEqual(errors, []);
  console.log(
    "PASS: desktop full A/B/C flow, seconds/timezone, stage correction, all module pages, Beacon major, mobile navigation and read-only permissions.",
  );
  await context.close();
  await mobile.close();
} catch (e) {
  await mkdir(project + "test-results", { recursive: true });
  await writeFile(project + "test-results/server.log", serverLog);
  console.error("Page errors:", errors);
  if (browser) {
    for (const [i, c] of browser.contexts().entries()) {
      for (const page of c.pages()) {
        console.error(await page.locator("body").innerText());
        await page.screenshot({
          path: project + "test-results/failure-" + i + ".png",
          fullPage: true,
        });
      }
    }
  }
  throw e;
} finally {
  if (browser) await browser.close();
  if (server.exitCode === null) {
    server.kill("SIGTERM");
    await new Promise((r) => server.once("exit", r));
  }
  await rm(dir, { recursive: true, force: true });
}
