import { test, expect, navigateTo } from "./fixtures.js";

test.use({ ledgerScenario: true, timezoneId: "America/Los_Angeles" });

test("forms refresh the server calendar across Belgrade midnight in a different browser timezone", async ({ page, appURL }, testInfo) => {
  await page.clock.setFixedTime(new Date("2026-09-10T22:00:00Z"));
  await navigateTo(page, "reconciliation");
  await expect(page.locator("#reconciliation-date")).toHaveValue("2026-09-10");
  await expect(page.locator("#reconciliation-date")).toHaveAttribute("max", "2026-09-10");
  expect((await page.request.post(appURL + "/api/e2e/cross-midnight")).status()).toBe(200);
  const policy = await (await page.request.get(appURL + "/api/ledger-policy")).json();
  expect(policy.business_date).toBe("2026-09-11");
  expect(policy.business_timezone).toBe("Europe/Belgrade");
  expect(await page.evaluate(() => new Date().getDate())).toBe(10);

  await navigateTo(page, "transactions");
  await page.locator("#add-transaction-btn-2").click();
  await expect(page.locator("#form-date")).toHaveValue("2026-09-11");
  await expect(page.locator("#form-date")).toHaveAttribute("max", "2026-09-11");
  await page.locator("#close-modal").click();
  await navigateTo(page, "transfers");
  await page.locator("#add-transfer-btn").click();
  await expect(page.locator("#transfer-date")).toHaveValue("2026-09-11");
  await page.locator("#close-transfer-modal").click();
  await navigateTo(page, "recurring");
  await page.locator("#add-recurring-btn").click();
  await expect(page.locator("#recurring-date")).toHaveValue("2026-09-11");
  await page.locator("#close-recurring-modal").click();
  await navigateTo(page, "reconciliation");
  await expect(page.locator("#reconciliation-date")).toHaveValue("2026-09-11");
  await expect(page.locator("#reconciliation-date")).toHaveAttribute("max", "2026-09-11");
  await navigateTo(page, "dashboard");
  await expect(page.locator("#balance-context")).toHaveText("As of 2026-09-11");
  await page.screenshot({ path: testInfo.outputPath("business-timezone.png"), fullPage: true });
});
