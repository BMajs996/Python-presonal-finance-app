import { test as base, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";

export const test = base.extend({
  ledgerScenario: [false, { option: true }],
  appURL: async ({ ledgerScenario }, use) => {
    const python = process.env.E2E_PYTHON || (existsSync(".venv/bin/python") ? ".venv/bin/python" : "python");
    const child = spawn(python, ["tests/e2e/server.py"], {
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, E2E_LEDGER_SCENARIO: ledgerScenario ? "1" : "" },
    });
    let output = "";
    let errors = "";
    child.stderr.on("data", chunk => { errors += chunk; });
    const closed = new Promise(resolve => child.once("close", resolve));
    try {
      const url = await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("Test server startup timed out: " + errors)), 10000);
        child.once("error", error => { clearTimeout(timer); reject(error); });
        child.once("exit", () => { clearTimeout(timer); reject(new Error("Test server exited: " + errors)); });
        child.stdout.on("data", chunk => {
          output += chunk;
          const match = output.match(/E2E_URL=(http:\/\/127\.0\.0\.1:\d+)/);
          if (match) { clearTimeout(timer); resolve(match[1]); }
        });
      });
      await expect.poll(async () => {
        try { return (await fetch(url + "/api/health")).status; } catch { return 0; }
      }).toBe(200);
      await use(url);
    } finally {
      child.kill("SIGTERM");
      const force = setTimeout(() => child.kill("SIGKILL"), 5000);
      await closed;
      clearTimeout(force);
    }
  },
  page: async ({ page, appURL }, use) => {
    const errors = [];
    await page.addInitScript(() => {
      window.cspViolations = [];
      document.addEventListener("securitypolicyviolation", event =>
        window.cspViolations.push(event.violatedDirective));
    });
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => {
      const url = route.request().url();
      return url.startsWith(appURL) || url.startsWith("blob:") ? route.continue() : route.abort();
    });
    const login = await page.request.post(appURL + "/api/auth/login", {
      headers: { Origin: appURL }, data: { username: "owner", password: "synthetic-owner-password" },
    });
    expect(login.status()).toBe(200);
    const session = await login.json();
    await page.context().setExtraHTTPHeaders({ Origin: appURL, "X-CSRF-Token": session.csrf_token });
    await page.goto(appURL);
    await expect(page.locator("#account-list")).toContainText("Main Account");
    await use(page);
    expect(errors).toEqual([]);
    expect(await page.evaluate(() => window.cspViolations)).toEqual([]);
  },
});
export { expect };
