import { test, expect } from "./fixtures.js";
import { parseCsv } from "../../frontend/utils/csv.js";

test("history, immediate undo and recovery after reload", async ({ page, appURL }, testInfo) => {
  await page.locator('nav [data-view="transactions"]').click();
  await page.locator("#add-transaction-btn-2").click();
  await page.locator("#form-category").fill("Food");
  await page.locator("#form-amount").fill("12.34");
  const description = '<img src=x onerror="alert(1)"> Lunch';
  await page.locator("#form-description").fill(description);
  await page.getByRole("button", { name: "Save transaction", exact: true }).click();
  const row = page.locator("#transaction-table tr").filter({ hasText: description });
  await expect(row).toHaveCount(1);
  await row.getByRole("button", { name: "Edit", exact: true }).click();
  await page.locator("#form-amount").fill("20.50");
  await page.getByRole("button", { name: "Save transaction", exact: true }).click();
  await expect(row).toContainText("$20.50");
  await row.getByRole("button", { name: "History", exact: true }).click();
  const history = page.locator("#transaction-history-modal");
  await expect(history.locator(".history-event")).toHaveCount(2);
  await expect(history).toContainText("$12.34");
  await expect(history).toContainText("$20.50");
  await expect(history).toContainText(description);
  await expect(history.locator("img")).toHaveCount(0);
  await expect(page.locator("#close-transaction-history")).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath("transaction-history.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await expect(history).toBeHidden();
  await expect(row.getByRole("button", { name: "History", exact: true })).toBeFocused();

  page.once("dialog", dialog => dialog.accept());
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(row).toHaveCount(0);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(row).toContainText("$20.50");
  page.once("dialog", dialog => dialog.accept());
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(row).toHaveCount(0);
  await page.reload();
  await page.locator('nav [data-view="transactions"]').click();

  const downloadPromise = page.waitForEvent("download");
  await page.locator("#export-csv-btn").click();
  const download = await downloadPromise;
  const chunks = [];
  for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  expect(parseCsv(Buffer.concat(chunks).toString("utf8"))).toHaveLength(1);

  await page.locator("#deleted-transactions-btn").click();
  const deleted = page.locator("#deleted-transactions-modal");
  await expect(deleted).toContainText(description);
  await expect(deleted.locator("img")).toHaveCount(0);
  await expect(deleted.getByRole("button", { name: "Restore", exact: true })).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath("deleted-transactions.png"), fullPage: true });
  await deleted.getByRole("button", { name: "History", exact: true }).click();
  await expect(history.locator(".history-event")).toHaveCount(5);
  await page.keyboard.press("Escape");
  await expect(deleted.getByRole("button", { name: "History", exact: true })).toBeFocused();
  await deleted.getByRole("button", { name: "Restore", exact: true }).click();
  await expect(deleted).toContainText("No deleted transactions.");
  await page.locator("#close-deleted-transactions").click();
  await expect(page.locator("#deleted-transactions-btn")).toBeFocused();
  await expect(row).toHaveCount(1);
  await page.locator('nav [data-view="dashboard"]').click();
  await expect(page.locator("#balance")).toHaveText("-$20.50");
  const entries = await (await page.request.get(appURL + "/api/transactions")).json();
  const events = await (await page.request.get(appURL + "/api/transactions/" + entries.items[0].id + "/history")).json();
  expect(events.items.map(event => event.action)).toEqual(["restored", "deleted", "restored", "deleted", "updated", "created"]);
});

test("failed recovery leaves the deleted entry available", async ({ page, appURL }) => {
  const response = await page.request.post(appURL + "/api/transactions", {
    data: { date: "2026-09-25", type: "expense", category: "Food", amount: 12.34, description: "Retry recovery" },
  });
  const entry = await response.json();
  await page.request.delete(appURL + "/api/transactions/" + entry.id);
  await page.locator('nav [data-view="transactions"]').click();
  await page.locator("#deleted-transactions-btn").click();
  await page.route("**/api/transactions/*/restore", route => route.fulfill({
    status: 400, contentType: "application/json", body: JSON.stringify({ detail: "Account is inactive" }),
  }));
  const restore = page.locator("#deleted-table").getByRole("button", { name: "Restore", exact: true });
  await restore.click();
  await expect(page.locator("#toast")).toContainText("Account is inactive");
  await expect(restore).toBeEnabled();
  await expect(page.locator("#deleted-table")).toContainText("Retry recovery");
  await page.unroute("**/api/transactions/*/restore");
  await restore.click();
  await expect(page.locator("#deleted-table")).toContainText("No deleted transactions.");
});
