import { test, expect } from "./fixtures.js";
import { todayIso } from "../../frontend/utils/dates.js";

test("saved draft, exact transfer totals and read-only statement history", async ({ page, appURL }, testInfo) => {
  const account = await (await page.request.post(appURL + "/api/accounts", {
    data: { name: "Checking", opening_balance: "100" },
  })).json();
  for (const data of [
    { type: "income", amount: "50", description: "Deposit" },
    { type: "expense", amount: "12.34", description: '<img src=x onerror="alert(1)"> Lunch' },
  ]) {
    expect((await page.request.post(appURL + "/api/transactions", {
      data: { ...data, date: todayIso(), category: "Statement", account_id: account.id },
    })).status()).toBe(201);
  }
  await page.request.post(appURL + "/api/transfers", {
    data: { date: todayIso(), from_account_id: account.id, to_account_id: 1, amount: "20", description: "Savings transfer" },
  });
  await page.locator('nav [data-view="reconciliation"]').click();
  await page.locator("#reconciliation-account").selectOption(String(account.id));
  await page.locator("#reconciliation-balance").fill("117.66");
  await page.getByRole("button", { name: "Start reconciliation", exact: true }).click();
  await expect(page.locator("#reconciliation-entries tr")).toHaveCount(3);
  await expect(page.locator("#reconciliation-opening")).toHaveText("$100.00");
  await expect(page.locator("#reconciliation-difference")).toHaveText("$17.66");
  await expect(page.locator("#reconciliation-complete")).toBeDisabled();
  await expect(page.locator("#reconciliation-entries img")).toHaveCount(0);
  await page.getByRole("checkbox", { name: "Cleared Deposit", exact: true }).check();
  await expect(page.locator("#reconciliation-difference")).toHaveText("-$32.34");
  await page.reload();
  await page.locator('nav [data-view="reconciliation"]').click();
  await page.locator("#reconciliation-account").selectOption(String(account.id));
  await expect(page.getByRole("checkbox", { name: "Cleared Deposit", exact: true })).toBeChecked();
  await page.getByRole("checkbox", { name: "Cleared <img", exact: false }).check();
  await expect(page.locator("#reconciliation-difference")).toHaveText("-$20.00");
  await page.getByRole("checkbox", { name: "Cleared Savings transfer", exact: true }).check();
  await expect(page.locator("#reconciliation-difference")).toHaveText("$0.00");
  await expect(page.locator("#reconciliation-complete")).toBeEnabled();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("reconciliation.png"), fullPage: true });
  page.once("dialog", dialog => dialog.accept());
  await page.locator("#reconciliation-complete").click();
  await expect(page.locator("#reconciliation-status")).toHaveText("Completed");
  await expect(page.getByRole("checkbox", { name: "Cleared Deposit", exact: true })).toBeDisabled();
  await page.reload();
  await page.locator('nav [data-view="reconciliation"]').click();
  await page.locator("#reconciliation-account").selectOption(String(account.id));
  await page.locator("#reconciliation-history").getByRole("button", { name: "View", exact: true }).click();
  await expect(page.locator("#reconciliation-cleared")).toHaveText("$117.66");
  await expect(page.locator("#reconciliation-status")).toHaveText("Completed");
  await page.locator("#reconciliation-account").selectOption("1");
  await page.locator("#reconciliation-balance").fill("20");
  await page.getByRole("button", { name: "Start reconciliation", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: "Cleared Savings transfer", exact: true })).not.toBeChecked();
  await page.getByRole("checkbox", { name: "Cleared Savings transfer", exact: true }).check();
  await expect(page.locator("#reconciliation-difference")).toHaveText("$0.00");
});

test("failed clear is reverted and discarded drafts release entries", async ({ page, appURL }) => {
  const entry = await (await page.request.post(appURL + "/api/transactions", {
    data: { date: todayIso(), type: "income", category: "Salary", amount: "10", description: "Retry entry" },
  })).json();
  await page.locator('nav [data-view="reconciliation"]').click();
  await page.locator("#reconciliation-balance").fill("10");
  await page.getByRole("button", { name: "Start reconciliation", exact: true }).click();
  const checkbox = page.getByRole("checkbox", { name: "Cleared Retry entry", exact: true });
  await page.route("**/api/reconciliations/*/entries", route => route.fulfill({
    status: 409, contentType: "application/json", body: JSON.stringify({ detail: "Entry changed elsewhere" }),
  }));
  await checkbox.check();
  await expect(page.locator("#toast")).toContainText("Entry changed elsewhere");
  await expect(checkbox).not.toBeChecked();
  await page.unroute("**/api/reconciliations/*/entries");
  await checkbox.check();
  await expect(page.locator("#reconciliation-difference")).toHaveText("$0.00");
  expect((await page.request.delete(appURL + "/api/transactions/" + entry.id)).status()).toBe(409);
  page.once("dialog", dialog => dialog.accept());
  await page.locator("#reconciliation-cancel").click();
  await expect(page.locator("#reconciliation-detail")).toBeHidden();
  await expect(page.locator("#reconciliation-history")).toContainText("No statements.");
  expect((await page.request.delete(appURL + "/api/transactions/" + entry.id)).status()).toBe(204);
});
