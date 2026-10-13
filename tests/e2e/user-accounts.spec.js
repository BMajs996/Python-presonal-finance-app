import { test, expect, navigateTo } from "./fixtures.js";

test.use({ accountScenario: true });
const password = "synthetic-member-password";
const replacement = "synthetic-replacement-password";

async function register(page, appURL, token, fromLogin = false) {
  if (fromLogin) {
    await page.goto(appURL + "/login");
    await page.getByRole("link", { name: "Create account", exact: true }).click();
    await page.getByLabel("Invitation link").fill(`${appURL}/register#token=${token}`);
  } else {
    await page.goto(`${appURL}/register#token=${encodeURIComponent(token)}`);
    await expect(page.getByLabel("Invitation link")).toBeHidden();
  }
  await expect(page).toHaveURL(appURL + "/register");
  await page.getByLabel("Name", { exact: true }).fill("Member One");
  await page.getByLabel("Username", { exact: true }).fill("member");
  await page.getByLabel("Email", { exact: true }).fill("member@example.com");
  await page.getByLabel("Phone (international)").fill("+381641234567");
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password", { exact: true }).fill(password);
  if (fromLogin) {
    const requests = [];
    page.on("request", request => {
      if (request.url().endsWith("/api/auth/register")) requests.push(request);
    });
    await page.getByLabel("Invitation link").fill(`https://untrusted.example/register#token=${token}`);
    await page.getByRole("button", { name: "Create account", exact: true }).click();
    await expect(page.locator("#account-error")).toHaveText("A valid account link is required.");
    expect(requests).toHaveLength(0);
    await expect(page.getByLabel("Email", { exact: true })).toHaveValue("member@example.com");
    await page.getByLabel("Invitation link").fill(`${appURL}/register#token=${token}`);
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

test("invited member has private data, editable profile and persistent password changes", async ({ page, appURL }, testInfo) => {
  const today = (await (await page.request.get(appURL + "/api/ledger-policy")).json()).business_date;
  expect((await page.request.post(appURL + "/api/transactions", { data: {
    date: today, type: "income", category: "Salary", amount: "777.77", description: "Owner-only salary",
  } })).status()).toBe(201);
  const invitation = await (await page.request.post(appURL + "/api/e2e/invite-member")).json();
  await register(page, appURL, invitation.token);
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

test("login offers invite-only registration with a pasted invitation link", async ({ page, appURL }, testInfo) => {
  const invitation = await (await page.request.post(appURL + "/api/e2e/invite-member")).json();
  await register(page, appURL, invitation.token, true);
  await signIn(page, appURL, password);
  await expect(page.locator("#balance")).toHaveText("$0.00");
  await page.goto(appURL + "/login");
  await page.screenshot({ path: `/tmp/finance-login-${testInfo.project.name}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("administrator-issued recovery link resets a member once and invalidates old sessions", async ({ page, appURL }) => {
  const invitation = await (await page.request.post(appURL + "/api/e2e/invite-member")).json();
  await register(page, appURL, invitation.token);
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
