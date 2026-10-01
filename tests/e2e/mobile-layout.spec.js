import { test, expect, navigateTo } from "./fixtures.js";

async function expectNoHorizontalOverflow(page) {
  const widths = await page.evaluate(() => ({
    page: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
    overflow: [...document.querySelectorAll("body, body *")]
      .filter(element => element.scrollWidth > element.clientWidth + 1)
      .slice(0, 12)
      .map(element => ({ tag: element.tagName, id: element.id, className: element.className,
        width: element.clientWidth, scroll: element.scrollWidth, right: element.getBoundingClientRect().right })),
  }));
  expect(widths.page, JSON.stringify(widths.overflow)).toBeLessThanOrEqual(widths.viewport + 1);
}

test("small screens keep navigation, transactions and actions usable", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.locator("#mobile-nav-toggle")).toBeVisible();
  await expect(page.locator("#primary-nav")).toBeHidden();
  await expectNoHorizontalOverflow(page);

  await navigateTo(page, "transactions");
  await expect(page.locator("#primary-nav")).toBeHidden();
  await page.locator("#add-transaction-btn-2").click();
  await page.locator("#form-category").fill("Groceries");
  await page.locator("#form-amount").fill("12.34");
  await page.locator("#form-description").fill("Market lunch");
  await page.getByRole("button", { name: "Save transaction" }).click();
  const row = page.locator("#transaction-table tr").filter({ hasText: "Market lunch" });
  await expect(row).toBeVisible();
  await expect(row.locator('[data-label="Amount"]')).toContainText("$12.34");
  await expect(row.getByRole("button", { name: "Edit" })).toBeVisible();
  await expect(row.getByRole("button", { name: "History" })).toBeVisible();
  await expect(row.getByRole("button", { name: "Delete" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("mobile-transactions.png"), fullPage: true });

  for (const width of [320, 430]) {
    await page.setViewportSize({ width, height: 700 });
    await expectNoHorizontalOverflow(page);
    await expect(row).toBeVisible();
  }
  await navigateTo(page, "reports");
  await expectNoHorizontalOverflow(page);
  await navigateTo(page, "reconciliation");
  await expectNoHorizontalOverflow(page);
});
