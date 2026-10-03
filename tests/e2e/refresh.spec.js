import { test, expect, navigateTo } from "./fixtures.js";

test("refresh reuses dashboard accounts and navigation still fetches fresh accounts", async ({ page }) => {
  const accountRequests = [];
  page.on("request", request => {
    if (new URL(request.url()).pathname === "/api/accounts" && request.method() === "GET") {
      accountRequests.push(request.url());
    }
  });
  await page.reload();
  await expect(page.locator("#form-account option")).toContainText(["Main Account"]);
  expect(accountRequests).toHaveLength(0);
  await navigateTo(page, "accounts");
  await expect(page.locator("#accounts-full")).toContainText("Main Account");
  expect(accountRequests).toHaveLength(1);
  await page.locator("#add-account-btn").click();
  await page.locator("#account-name").fill("Refresh Savings");
  await page.locator("#account-opening").fill("125.50");
  await page.locator("#account-form button[type=submit]").click();
  await expect(page.locator("#accounts-full")).toContainText("Refresh Savings");
  await expect(page.locator("#form-account option")).toContainText(["Main Account", "Refresh Savings"]);
  expect(accountRequests).toHaveLength(1);
});
