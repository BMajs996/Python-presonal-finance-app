import { test, expect } from "./fixtures.js";
import { parseCsv } from "../../frontend/utils/csv.js";

test("case-sensitive CSV identity agrees with budgets and reports while exact exports retain cents", async ({ page, appURL }) => {
  const policy = await (await page.request.get(appURL + "/api/ledger-policy")).json();
  await page.locator('nav [data-view="transactions"]').click();
  const lines = ["date,type,category,amount,description",
    ...["Food", "food", "FOOD", " Food "].map(category =>
      policy.business_date + ",expense," + category + ",2.00,Same purchase")];
  await page.locator("#csv-import-file").setInputFiles({
    name: "categories.csv", mimeType: "text/csv", buffer: Buffer.from(lines.join("\n")),
  });
  await expect(page.locator("#csv-valid-count")).toHaveText("3");
  await expect(page.locator("#csv-duplicate-count")).toHaveText("1");
  await page.locator("#confirm-csv-import-btn").click();
  await expect(page.locator("#transaction-count")).toHaveText("3 records");
  const pageData = await (await page.request.get(appURL + "/api/transactions")).json();
  expect(pageData.items.map(row => row.category).sort()).toEqual(["FOOD", "Food", "food"]);
  for (const row of pageData.items) {
    expect(row.amount).toBe(2);
    expect(row.money).toEqual({ version: "decimal-v1", currency: "USD", values: { amount: "2.00" } });
  }
  const budget = await page.request.post(appURL + "/api/budgets", {
    data: { category: "Food", monthly_limit: "10.00" },
  });
  expect((await budget.json()).money.values.spent).toBe("2.00");
  const report = await (await page.request.get(appURL + "/api/reports/monthly")).json();
  expect(report.top_categories).toHaveLength(3);
  expect(report.summary.money.values.expenses).toBe("6.00");
  const download = page.waitForEvent("download");
  await page.locator("#export-csv-btn").click();
  const chunks = [];
  for await (const chunk of await (await download).createReadStream()) chunks.push(chunk);
  const rows = parseCsv(Buffer.concat(chunks).toString());
  expect(rows).toHaveLength(4);
  expect(rows.slice(1).every(row => row[3] === "2.00")).toBe(true);
});
