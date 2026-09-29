import { test, expect } from "./fixtures.js";

test.use({ ledgerScenario: true });

test("legacy future entries are excluded everywhere and become posted once on the next business day", async ({ page, appURL }) => {
  await expect(page.locator("#balance")).toHaveText("$0.00");
  await expect(page.locator("#balance-context")).toHaveText("As of 2026-09-10");
  await expect(page.locator("#recent-transactions")).not.toContainText("Future");
  await expect(page.locator("#budget-list")).toContainText("$0.00");
  await page.locator('nav [data-view="transactions"]').click();
  await expect(page.locator("#transaction-count")).toHaveText("0 records");
  await page.locator('nav [data-view="transfers"]').click();
  await expect(page.locator("#transfer-table")).not.toContainText("Future transfer");
  await page.locator('nav [data-view="reports"]').click();
  await expect(page.locator("#report-income")).toHaveText("$0.00");
  await expect(page.locator("#report-expenses")).toHaveText("$0.00");
  expect((await page.request.post(appURL + "/api/e2e/advance-business-day")).status()).toBe(200);
  for (let retry = 0; retry < 2; retry += 1) {
    await page.reload();
    await expect(page.locator("#balance")).toHaveText("$80.00");
    await expect(page.locator("#balance-context")).toHaveText("As of 2026-09-11");
    await expect(page.locator("#income")).toHaveText("$100.00");
    await expect(page.locator("#expenses")).toHaveText("$20.00");
    await expect(page.locator("#budget-list")).toContainText("$20.00");
    await expect(page.locator("#recent-transactions")).toContainText("Future income");
    const main = page.locator("#account-list .account-card").filter({ hasText: "Main Account" });
    const savings = page.locator("#account-list .account-card").filter({ hasText: "Savings" });
    await expect(main).toContainText("$50.00");
    await expect(savings).toContainText("$30.00");
    await page.locator('nav [data-view="transactions"]').click();
    await expect(page.locator("#transaction-count")).toHaveText("2 records");
    await page.locator('nav [data-view="transfers"]').click();
    await expect(page.locator("#transfer-table")).toContainText("Future transfer");
    await page.locator('nav [data-view="reports"]').click();
    await expect(page.locator("#report-net")).toHaveText("$80.00");
    const data = await (await page.request.get(appURL + "/api/dashboard")).json();
    expect(data.balance_history.at(-1)).toEqual({ date: "2026-09-11", balance: 80,
      money: { version: "decimal-v1", currency: "USD", values: { balance: "80.00" } } });
    expect(data.balance_history.every(row => row.date <= data.period.end)).toBe(true);
  }
});

test("future manual entries and CSV rows are rejected even when HTML limits are bypassed", async ({ page, appURL }) => {
  await page.locator('nav [data-view="transactions"]').click();
  for (const type of ["income", "expense"]) {
    await page.locator("#add-transaction-btn-2").click();
    await expect(page.locator("#form-date")).toHaveAttribute("max", "2026-09-10");
    await page.locator("#form-date").evaluate(input => input.removeAttribute("max"));
    await page.locator("#form-date").fill("2026-09-12");
    await page.locator("#form-type").selectOption(type);
    await page.locator("#form-category").fill("Food");
    await page.locator("#form-amount").fill("100");
    await page.getByRole("button", { name: "Save transaction", exact: true }).click();
    await expect(page.locator("#toast")).toContainText("Future-dated entries are not allowed");
    await expect(page.locator("#modal")).toBeVisible();
    await page.locator("#close-modal").click();
  }
  await page.locator("#csv-import-file").setInputFiles({
    name: "future.csv", mimeType: "text/csv",
    buffer: Buffer.from("date,type,category,amount,account_name\n2026-09-12,expense,Food,20,Main Account\n"),
  });
  await expect(page.locator("#csv-invalid-count")).toHaveText("1");
  await expect(page.locator("#confirm-csv-import-btn")).toBeDisabled();
  await expect(page.locator("#csv-preview-table tr")).toHaveAttribute("title", /Future-dated/);
  await page.locator("#cancel-csv-import-btn").click();
  await page.locator('nav [data-view="transfers"]').click();
  await page.locator("#add-transfer-btn").click();
  await expect(page.locator("#transfer-date")).toHaveAttribute("max", "2026-09-10");
  await page.locator("#transfer-date").evaluate(input => input.removeAttribute("max"));
  await page.locator("#transfer-date").fill("2026-09-12");
  const accounts = await (await page.request.get(appURL + "/api/accounts")).json();
  await page.locator("#transfer-from").selectOption(String(accounts[0].id));
  await page.locator("#transfer-to").selectOption(String(accounts[1].id));
  await page.locator("#transfer-amount").fill("25");
  await page.getByRole("button", { name: "Create transfer", exact: true }).click();
  await expect(page.locator("#toast")).toContainText("Future-dated entries are not allowed");
  expect((await (await page.request.get(appURL + "/api/dashboard")).json()).balance).toBe(0);
});
