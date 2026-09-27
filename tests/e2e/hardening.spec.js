import { test, expect } from "./fixtures.js";
import { parseCsv } from "../../frontend/utils/csv.js";

test("legacy date and type payloads remain text in transaction and recurring tables", async ({ page }) => {
  const malicious = '<img src=x onerror="window.injected=true">';
  const item = {
    id: 1, date: malicious, type: malicious, category: "Legacy", description: "Legacy",
    amount: 1, currency: "USD", account_id: 1, account_name: "Main Account",
  };
  await page.route("**/api/transactions?**", route => route.fulfill({ json: { items: [item], total: 1 } }));
  await page.route("**/api/recurring", route => route.fulfill({
    json: [{ ...item, next_date: malicious, frequency: malicious }],
  }));
  await page.locator('nav [data-view="transactions"]').click();
  await expect(page.locator("#transaction-table")).toContainText(malicious);
  await expect(page.locator("#transaction-table img")).toHaveCount(0);
  await page.locator('nav [data-view="recurring"]').click();
  await expect(page.locator("#recurring-table")).toContainText(malicious);
  await expect(page.locator("#recurring-table img")).toHaveCount(0);
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
});

test("CSV distinguishes categories, neutralizes formulas and survives a lost import response", async ({ page, appURL }) => {
  await page.locator('nav [data-view="transactions"]').click();
  const csv = "date,type,category,amount,description,account_name\n"
    + '2026-01-01,expense,Food,12.34,=1+1,Main Account\n'
    + '2026-01-01,expense,Travel,12.34,=1+1,Main Account\n';
  await page.locator("#csv-import-file").setInputFiles({
    name: "safe.csv", mimeType: "text/csv", buffer: Buffer.from(csv),
  });
  await expect(page.locator("#csv-valid-count")).toHaveText("2");
  let interrupted = false;
  await page.route("**/api/transactions/import", async route => {
    if (interrupted) return route.continue();
    interrupted = true;
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    await route.abort("failed");
  });
  await page.locator("#confirm-csv-import-btn").click();
  await expect(page.locator("#toast")).toContainText(/fetch|network/i);
  await expect(page.locator("#csv-preview-modal")).toBeVisible();
  await page.locator("#confirm-csv-import-btn").click();
  await expect(page.locator("#transaction-count")).toHaveText("2 records");
  expect((await (await page.request.get(appURL + "/api/transactions")).json()).total).toBe(2);
  const downloaded = page.waitForEvent("download");
  await page.locator("#export-csv-btn").click();
  const chunks = [];
  for await (const chunk of await (await downloaded).createReadStream()) chunks.push(chunk);
  const rows = parseCsv(Buffer.concat(chunks).toString());
  for (const row of rows.slice(1)) {
    expect(row[5]).toBe("'=1+1");
    expect(row[3]).toBe("12.34");
  }
});

test("statement pagination preserves totals and clearing on later pages", async ({ page, appURL }, testInfo) => {
  const accounts = await (await page.request.get(appURL + "/api/accounts")).json();
  const rows = Array.from({ length: 105 }, (_, index) => ({
    date: "2020-01-01", type: "income", category: "Paging", amount: "0.01",
    description: "Entry " + index, account_id: accounts[0].id,
  }));
  expect((await page.request.post(appURL + "/api/transactions/import", {
    data: { batch_id: crypto.randomUUID(), rows },
  })).status()).toBe(200);
  await page.request.post(appURL + "/api/reconciliations", { data: {
    account_id: accounts[0].id, closing_date: "2020-01-31", closing_balance: "1.05",
  } });
  await page.locator('nav [data-view="reconciliation"]').click();
  await expect(page.locator("#reconciliation-entries input")).toHaveCount(100);
  await expect(page.locator("#reconciliation-entry-count")).toHaveText("0 / 105 cleared");
  await page.locator("#reconciliation-next").click();
  await expect(page.locator("#reconciliation-entries input")).toHaveCount(5);
  await page.screenshot({ path: testInfo.outputPath("reconciliation-page.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator("#reconciliation-entries input").first().check();
  await expect(page.locator("#reconciliation-entry-count")).toHaveText("1 / 105 cleared");
  await expect(page.locator("#reconciliation-entries input")).toHaveCount(5);
  await page.locator("#reconciliation-previous").click();
  await expect(page.locator("#reconciliation-entries input")).toHaveCount(100);
  await expect(page.locator("#reconciliation-entry-count")).toHaveText("1 / 105 cleared");
});
