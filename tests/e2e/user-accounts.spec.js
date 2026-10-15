import { test, expect, navigateTo } from "./fixtures.js";
import { request } from "@playwright/test";

test.use({ accountScenario: true });
const password = "synthetic-member-password";
const replacement = "synthetic-replacement-password";

async function register(page, appURL, fromLogin = false) {
  if (fromLogin) {
    await page.goto(appURL + "/login");
    await page.getByRole("link", { name: "Create account", exact: true }).click();
  } else {
    await page.goto(`${appURL}/register`);
  }
  await expect(page).toHaveURL(appURL + "/register");
  await expect(page.locator("#invitation")).toHaveCount(0);
  await page.getByLabel("Name", { exact: true }).fill("Member One");
  await page.getByLabel("Username", { exact: true }).fill("member");
  await page.getByLabel("Email", { exact: true }).fill("member@example.com");
  await page.getByLabel("Phone (international)").fill("+381641234567");
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password", { exact: true }).fill(password);
  if (fromLogin) {
    await page.getByLabel("Confirm password", { exact: true }).fill("synthetic-mismatched-password");
    await page.getByRole("button", { name: "Create account", exact: true }).click();
    await expect(page.locator("#account-error")).toHaveText("Passwords do not match.");
    await expect(page.getByLabel("Email", { exact: true })).toHaveValue("member@example.com");
    await page.getByLabel("Confirm password", { exact: true }).fill(password);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `/tmp/finance-register-${page.viewportSize().width}.png`, fullPage: true });
  }
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page).toHaveURL(appURL + "/login");
}

async function signIn(page, appURL, value) {
  // Let the app send its new session's CSRF token, not the fixture's original owner token.
  await page.context().setExtraHTTPHeaders({ Origin: appURL });
  await page.getByLabel("Username or email").fill("member@example.com");
  await page.getByLabel("Password", { exact: true }).fill(value);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(appURL + "/");
  await expect(page.locator("#signed-in-name")).toContainText("Member");
}

test("publicly registered member has private data, editable profile and persistent password changes", async ({ page, appURL }, testInfo) => {
  const today = (await (await page.request.get(appURL + "/api/ledger-policy")).json()).business_date;
  expect((await page.request.post(appURL + "/api/transactions", { data: {
    date: today, type: "income", category: "Salary", amount: "777.77", description: "Owner-only salary",
  } })).status()).toBe(201);
  await register(page, appURL);
  await signIn(page, appURL, password);
  await expect(page.locator("#balance")).toHaveText("$0.00");
  expect((await (await page.request.get(appURL + "/api/transactions")).json()).total).toBe(0);
  expect((await page.request.get(appURL + "/api/operations/health")).status()).toBe(403);
  await navigateTo(page, "profile");
  const profile = page.locator("#profile-form");
  await expect(profile.getByLabel("Name", { exact: true })).toHaveValue("Member One");
  await profile.getByLabel("Name", { exact: true }).fill("Member Updated");
  await profile.getByLabel("Current password").fill(password);
  await profile.getByRole("button", { name: "Save profile" }).click();
  await expect(page.locator("#toast")).toHaveText("Profile saved");
  await expect(page.locator("#signed-in-name")).toHaveText("Member Updated");
  await expect(page.locator("#profile-sessions")).toContainText("Current");
  await page.screenshot({ path: `/tmp/finance-profile-${testInfo.project.name}.png`, fullPage: true });
  const layout = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(layout).toBe(true);
  const change = page.locator("#password-form");
  await change.getByLabel("Current password").fill(password);
  await change.getByLabel("New password", { exact: true }).fill(replacement);
  await change.getByLabel("Confirm new password").fill(replacement);
  await change.getByRole("button", { name: "Change password" }).click();
  await expect(page).toHaveURL(appURL + "/login");
  await signIn(page, appURL, replacement);
  await navigateTo(page, "profile");
  await expect(page.locator("#profile-name")).toHaveValue("Member Updated");
});

test("login offers public registration without an invitation", async ({ page, appURL }, testInfo) => {
  await page.context().clearCookies();
  await register(page, appURL, true);
  await signIn(page, appURL, password);
  await expect(page.locator("#balance")).toHaveText("$0.00");
  await page.goto(appURL + "/login");
  await page.screenshot({ path: `/tmp/finance-login-${testInfo.project.name}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("registration throttling preserves input and permits retry after the limit clears", async ({ page, appURL }) => {
  await page.context().clearCookies();
  await page.route("**/api/auth/register", route => route.fulfill({
    status: 429, contentType: "application/json", headers: { "Retry-After": "3600" },
    body: JSON.stringify({ detail: "Too many registration attempts. Try again later." }),
  }));
  await page.goto(appURL + "/register");
  await page.getByLabel("Name", { exact: true }).fill("Member One");
  await page.getByLabel("Username", { exact: true }).fill("member");
  await page.getByLabel("Email", { exact: true }).fill("member@example.com");
  await page.getByLabel("Phone (international)").fill("+381641234567");
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.locator("#account-error")).toContainText("Too many registration attempts");
  await expect(page.getByLabel("Username", { exact: true })).toHaveValue("member");
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue(password);
  await expect(page.getByRole("button", { name: "Create account", exact: true })).toBeEnabled();
  await page.unroute("**/api/auth/register");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page).toHaveURL(appURL + "/login");
  await signIn(page, appURL, password);
});

test("administrator-issued recovery link resets a member once and invalidates old sessions", async ({ page, appURL }) => {
  await register(page, appURL);
  // Registration leaves the owner's cookie intact until a member signs in.
  const recovery = await (await page.request.post(appURL + "/api/e2e/reset-member")).json();
  await signIn(page, appURL, password);
  const session = await (await page.request.get(appURL + "/api/auth/session")).json();
  const oldCookie = (await page.context().cookies()).find(cookie => cookie.name === "finance_session");
  await page.goto(`${appURL}/reset-password#token=${encodeURIComponent(recovery.token)}`);
  await expect(page).toHaveURL(appURL + "/reset-password");
  await page.getByLabel("New password", { exact: true }).fill(replacement);
  await page.getByLabel("Confirm password", { exact: true }).fill(replacement);
  await page.getByRole("button", { name: "Reset password", exact: true }).click();
  await expect(page).toHaveURL(appURL + "/login");
  expect((await page.request.get(appURL + "/api/accounts", { headers: {
    Cookie: `finance_session=${oldCookie.value}`, "X-CSRF-Token": session.csrf_token,
  } })).status()).toBe(401);
  expect((await page.request.post(appURL + "/api/auth/reset-password", { data: {
    token: recovery.token, password: replacement,
  } })).status()).toBe(400);
  await signIn(page, appURL, replacement);
});

test("session controls preserve profile drafts and invalidate only selected sessions", async ({ page, appURL }) => {
  await page.context().setExtraHTTPHeaders({ Origin: appURL });
  // A separate request context has its own cookie jar, like another device.
  const other = await request.newContext({ baseURL: appURL, extraHTTPHeaders: { Origin: appURL } });
  try {
    const login = () => other.post("/api/auth/login", { data: {
      username: "owner", password: "synthetic-owner-password",
    } });
    expect((await login()).status()).toBe(200);
    await navigateTo(page, "profile");
    await expect(page.locator("#profile-sessions tr")).toHaveCount(2);
    const profile = page.locator("#profile-form");
    await profile.getByLabel("Name", { exact: true }).fill("Unsaved profile draft");
    await page.locator("#profile-sessions tr").filter({ hasText: "Other" })
      .getByRole("button", { name: "Sign out" }).click();
    await expect(page.locator("#profile-sessions tr")).toHaveCount(1);
    await expect(profile.getByLabel("Name", { exact: true })).toHaveValue("Unsaved profile draft");
    expect((await other.get("/api/auth/session")).status()).toBe(401);
    expect((await login()).status()).toBe(200);
    await page.getByRole("button", { name: "Sign out other sessions" }).click();
    await expect(page.locator("#profile-sessions tr")).toHaveCount(1);
    await expect(profile.getByLabel("Name", { exact: true })).toHaveValue("Unsaved profile draft");
    expect((await other.get("/api/auth/session")).status()).toBe(401);
    expect((await page.request.get(appURL + "/api/auth/session")).status()).toBe(200);
    await page.locator("#profile-sessions tr").getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(appURL + "/login");
    expect((await page.request.get(appURL + "/api/auth/session")).status()).toBe(401);
  } finally { await other.dispose(); }
});

test("failed profile saves retain input and session refresh does not discard it", async ({ page, appURL }) => {
  await page.context().setExtraHTTPHeaders({ Origin: appURL });
  await navigateTo(page, "profile");
  const profile = page.locator("#profile-form");
  await profile.getByLabel("Name", { exact: true }).fill("Retained name");
  await profile.getByLabel("Email", { exact: true }).fill("owner@example.com");
  await profile.getByLabel("Phone (international)").fill("+381641234567");
  await profile.getByLabel("Current password").fill("synthetic-owner-password");
  await page.route("**/api/auth/profile", route => route.request().method() === "PUT"
    ? route.fulfill({ status: 429, contentType: "application/json", headers: { "Retry-After": "60" },
      body: JSON.stringify({ detail: "Too many attempts. Try again shortly." }) }) : route.continue());
  await profile.getByRole("button", { name: "Save profile" }).click();
  await expect(page.locator("#toast")).toContainText("Too many attempts");
  await expect(profile.getByLabel("Name", { exact: true })).toHaveValue("Retained name");
  await expect(profile.getByLabel("Current password")).toHaveValue("synthetic-owner-password");
  await expect(profile.getByRole("button", { name: "Save profile" })).toBeEnabled();
  await page.getByRole("button", { name: "Sign out other sessions" }).click();
  await expect(profile.getByLabel("Name", { exact: true })).toHaveValue("Retained name");
  await page.unroute("**/api/auth/profile");
  await profile.getByRole("button", { name: "Save profile" }).click();
  await expect(page.locator("#toast")).toHaveText("Profile saved");
  await expect(profile.getByLabel("Current password")).toHaveValue("");
  await page.reload();
  await navigateTo(page, "profile");
  await expect(profile.getByLabel("Name", { exact: true })).toHaveValue("Retained name");
});
