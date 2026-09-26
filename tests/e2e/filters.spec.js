import { test, expect } from "./fixtures.js";

test("type, category and account dropdowns apply without clicking Filter", async ({ page, appURL }) => {
  const account = await (await page.request.post(appURL + "/api/accounts", {
    data: { name: "Cash" },
  })).json();
  for (const data of [
    { type: "income", category: "Salary", description: "Monthly salary" },
    { type: "expense", category: "Food", description: "Lunch", account_id: account.id },
    { type: "expense", category: "Travel", description: "Bus" },
  ]) {
    expect((await page.request.post(appURL + "/api/transactions", {
      data: { date: "2026-09-25", amount: 10, ...data },
    })).status()).toBe(201);
  }
  await page.reload();
  await page.locator('nav [data-view="transactions"]').click();
  await expect(page.locator("#transaction-count")).toHaveText("3 records");
  await page.locator("#type-filter").selectOption("expense");
  await expect(page.locator("#transaction-count")).toHaveText("2 records");
  await expect(page.locator("#transaction-table")).not.toContainText("Monthly salary");
  await page.locator("#category-filter").selectOption("Food");
  await expect(page.locator("#transaction-count")).toHaveText("1 record");
  await expect(page.locator("#transaction-table")).toContainText("Lunch");
  await page.locator("#category-filter").selectOption("");
  await page.locator("#account-filter").selectOption(String(account.id));
  await expect(page.locator("#transaction-count")).toHaveText("1 record");
  await expect(page.locator("#transaction-table")).toContainText("Lunch");
  await page.locator("#account-filter").selectOption("");
  await page.locator("#type-filter").selectOption("income");
  await expect(page.locator("#transaction-count")).toHaveText("1 record");
  await expect(page.locator("#transaction-table")).toContainText("Monthly salary");
  await page.locator("#type-filter").selectOption("");
  await expect(page.locator("#transaction-count")).toHaveText("3 records");
});

test("a delayed expense response cannot replace a newer income selection", async ({ page, appURL }) => {
  for (const type of ["income", "expense"]) {
    await page.request.post(appURL + "/api/transactions", {
      data: { date: "2026-09-25", amount: 10, type, category: type, description: type + " entry" },
    });
  }
  await page.locator('nav [data-view="transactions"]').click();
  await expect(page.locator("#transaction-count")).toHaveText("2 records");
  let release;
  let started;
  const gate = new Promise(resolve => { release = resolve; });
  const waiting = new Promise(resolve => { started = resolve; });
  await page.route("**/api/transactions?**", async route => {
    if (new URL(route.request().url()).searchParams.get("type") !== "expense") return route.fallback();
    const response = await route.fetch();
    started();
    await gate;
    await route.fulfill({ response });
  });
  await page.locator("#type-filter").selectOption("expense");
  await waiting;
  await page.locator("#type-filter").selectOption("income");
  await expect(page.locator("#transaction-table")).toContainText("income entry");
  await expect(page.locator("#transaction-table")).not.toContainText("expense entry");
  const lateResponse = page.waitForResponse(response => new URL(response.url()).searchParams.get("type") === "expense");
  release();
  await lateResponse;
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.locator("#type-filter")).toHaveValue("income");
  await expect(page.locator("#transaction-table")).toContainText("income entry");
  await expect(page.locator("#transaction-table")).not.toContainText("expense entry");
});
