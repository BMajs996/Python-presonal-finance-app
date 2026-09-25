import { test, expect } from "./fixtures.js";
import { parseCsv } from "../../frontend/utils/csv.js";

async function transactions(page) {
  await page.locator('nav [data-view="transactions"]').click();
  await expect(page.locator("#transactions-view")).toBeVisible();
}

async function entry(page, description = "Lunch") {
  await page.locator("#add-transaction-btn-2").click();
  await page.locator("#form-category").fill("Food");
  await page.locator("#form-amount").fill("12.34");
  await page.locator("#form-description").fill(description);
}

test("transaction create, edit, cancelled deletion and confirmed deletion", async ({ page }) => {
  await transactions(page);
  const text = '<img src=x onerror="alert(1)"> Lunch';
  await entry(page, text);
  await page.getByRole("button", { name: "Save transaction", exact: true }).click();
  const row = page.locator("#transaction-table tr").filter({ hasText: text });
  await expect(row).toHaveCount(1);
  await expect(row.locator("img")).toHaveCount(0);
  await expect(row).toContainText("$12.34");
  await row.getByRole("button", { name: "Edit", exact: true }).click();
  await page.locator("#form-amount").fill("20.50");
  await page.getByRole("button", { name: "Save transaction", exact: true }).click();
  await expect(row).toContainText("$20.50");
  page.once("dialog", dialog => dialog.dismiss());
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(row).toHaveCount(1);
  await page.reload();
  await transactions(page);
  await expect(row).toContainText("$20.50");
  page.once("dialog", dialog => dialog.accept());
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.locator("#transaction-count")).toHaveText("0 records");
  await page.reload();
  await transactions(page);
  await expect(page.locator("#transaction-table tr")).toHaveCount(0);
});

test("CSV previews valid, invalid and duplicate rows, imports and exports", async ({ page }, testInfo) => {
  await transactions(page);
  const csv = 'date,type,category,amount,description,account_name\n'
    + '2026-09-25,expense,Food,12.34,"Lunch, cafe",Main Account\n'
    + '2026-09-25,expense,Food,12.34,"Lunch, cafe",Main Account\n'
    + '2026-02-30,expense,Food,10,Bad date,Main Account\n'
    + '2026-09-25,expense,Food,10,Unknown account,Missing\n';
  const upload = () => page.locator("#csv-import-file").setInputFiles({
    name: "transactions.csv", mimeType: "text/csv", buffer: Buffer.from(csv),
  });
  await upload();
  await expect(page.locator("#csv-valid-count")).toHaveText("1");
  await expect(page.locator("#csv-invalid-count")).toHaveText("2");
  await expect(page.locator("#csv-duplicate-count")).toHaveText("1");
  await expect(page.locator("#csv-preview-table")).toContainText("Main Account");
  await expect(page.locator("#confirm-csv-import-btn")).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath("csv-preview.png"), fullPage: true });
  await page.locator("#cancel-csv-import-btn").click();
  await expect(page.locator("#transaction-count")).toHaveText("0 records");
  await upload();
  await page.locator("#confirm-csv-import-btn").click();
  await expect(page.locator("#transaction-count")).toHaveText("1 record");
  await expect(page.locator("#transaction-table")).toContainText("Lunch, cafe");
  await upload();
  await expect(page.locator("#csv-duplicate-count")).toHaveText("2");
  await expect(page.locator("#confirm-csv-import-btn")).toBeDisabled();
  await page.locator("#cancel-csv-import-btn").click();

  const downloadPromise = page.waitForEvent("download");
  await page.locator("#export-csv-btn").click();
  const download = await downloadPromise;
  const chunks = [];
  for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  const rows = parseCsv(Buffer.concat(chunks).toString("utf8"));
  expect(rows).toHaveLength(2);
  expect(rows[0]).toContain("currency");
  expect(rows[1]).toContain("Lunch, cafe");
  expect(rows[1]).toContain("12.34");
});

test("transfer creation and deletion preserve global totals and charts render locally", async ({ page, appURL }, testInfo) => {
  const response = await page.request.post(appURL + "/api/accounts", {
    data: { name: "Savings", type: "savings", opening_balance: 100 },
  });
  expect(response.status()).toBe(201);
  const savings = await response.json();
  const accounts = await (await page.request.get(appURL + "/api/accounts")).json();
  const main = accounts.find(account => account.name === "Main Account");
  await page.locator('nav [data-view="transfers"]').click();
  await page.locator("#add-transfer-btn").click();
  await page.locator("#transfer-from").selectOption(String(savings.id));
  await page.locator("#transfer-to").selectOption(String(main.id));
  await page.locator("#transfer-amount").fill("25");
  await page.locator("#transfer-description").fill("Moving savings");
  await page.getByRole("button", { name: "Create transfer", exact: true }).click();
  const row = page.locator("#transfer-table tr").filter({ hasText: "Moving savings" });
  await expect(row).toContainText("$25.00");
  const after = await (await page.request.get(appURL + "/api/accounts")).json();
  expect(after.find(account => account.id === savings.id).balance).toBe(75);
  expect(after.find(account => account.id === main.id).balance).toBe(25);
  await page.locator('nav [data-view="dashboard"]').click();
  await expect(page.locator("#balance")).toHaveText("$100.00");
  await expect(page.locator("#income")).toHaveText("$0.00");
  await expect(page.locator("#expenses")).toHaveText("$0.00");
  await expect(page.locator("#net")).toHaveText("$0.00");
  await expect.poll(() => page.locator("#balance-chart").evaluate(canvas =>
    Array.from(canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data)
      .some((value, index) => index % 4 === 3 && value > 0)
  )).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("dashboard.png"), fullPage: true });
  await page.locator('nav [data-view="reports"]').click();
  await expect(page.locator("#report-income")).toHaveText("$0.00");
  await expect.poll(() => page.evaluate(() => Boolean(Chart.getChart("monthly-chart")))).toBe(true);
  await page.locator('nav [data-view="transfers"]').click();
  page.once("dialog", dialog => dialog.accept());
  await row.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(row).toHaveCount(0);
  const restored = await (await page.request.get(appURL + "/api/accounts")).json();
  expect(restored.find(account => account.id === savings.id).balance).toBe(100);
  expect(restored.find(account => account.id === main.id).balance).toBe(0);
});

test("failed saves retain input and invalid date filters show an error", async ({ page, appURL }) => {
  await transactions(page);
  await entry(page, "Keep my input");
  await page.route("**/api/transactions", route => route.request().method() === "POST"
    ? route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: "Account is inactive" }) })
    : route.fallback());
  await page.getByRole("button", { name: "Save transaction", exact: true }).click();
  await expect(page.locator("#toast")).toContainText("Account is inactive");
  await expect(page.locator("#modal")).toBeVisible();
  await expect(page.locator("#form-description")).toHaveValue("Keep my input");
  expect((await (await page.request.get(appURL + "/api/transactions")).json()).total).toBe(0);
  await page.locator("#close-modal").click();
  await page.locator("#date-start-filter").fill("2026-09-30");
  await page.locator("#date-end-filter").fill("2026-09-01");
  await page.locator("#filter-btn").click();
  await expect(page.locator("#toast")).toContainText("Start date cannot be after end date");
});
