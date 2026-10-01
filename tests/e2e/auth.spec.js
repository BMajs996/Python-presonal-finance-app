import { test, expect, navigateTo } from "./fixtures.js";

test("sign out, invalid sign in, sign in, and expired session", async ({ page, appURL }) => {
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(appURL + "/login");
  expect((await page.request.get(appURL + "/api/accounts")).status()).toBe(401);
  await page.getByLabel("Username").fill("owner");
  await page.getByLabel("Password", { exact: true }).fill("incorrect");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("Invalid username or password");
  await page.screenshot({ path: test.info().outputPath("login.png") });
  await page.getByLabel("Password", { exact: true }).fill("synthetic-owner-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(appURL + "/");
  await expect(page.locator("#account-list")).toContainText("Main Account");
  await page.context().clearCookies();
  await navigateTo(page, "transactions");
  await expect(page).toHaveURL(appURL + "/login");
});

test("cross-origin and missing-CSRF writes are rejected", async ({ page, appURL }) => {
  const response = await page.request.post(appURL + "/api/accounts", {
    headers: { Origin: "https://evil.example" }, data: { name: "Blocked" },
  });
  expect(response.status()).toBe(403);
  await page.context().setExtraHTTPHeaders({ Origin: appURL });
  expect((await page.request.post(appURL + "/api/accounts", { data: { name: "Blocked" } })).status()).toBe(403);
});


test("release URLs bypass obsolete unversioned scripts", async ({ page, appURL }) => {
  await page.route(appURL + "/assets/app.js", route => route.fulfill({
    contentType: "text/javascript", body: "window.obsoleteAppLoaded = true;",
  }));
  await page.route(appURL + "/assets/api/client.js", route => route.fulfill({
    contentType: "text/javascript", body: "throw new Error('Obsolete client');",
  }));
  await page.reload();
  await expect(page.locator("#account-list")).toContainText("Main Account");
  expect(await page.evaluate(() => window.obsoleteAppLoaded)).toBeUndefined();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(appURL + "/login");
  expect((await page.request.get(appURL + "/api/accounts")).status()).toBe(401);
});
