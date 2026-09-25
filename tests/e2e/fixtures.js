import { test as base, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";

export const test = base.extend({
  appURL: async ({}, use) => {
    const python = process.env.E2E_PYTHON || (existsSync(".venv/bin/python") ? ".venv/bin/python" : "python");
    const child = spawn(python, ["tests/e2e/server.py"], { stdio: ["ignore", "pipe", "pipe"] });
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
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => {
      const url = route.request().url();
      return url.startsWith(appURL) || url.startsWith("blob:") ? route.continue() : route.abort();
    });
    await page.goto(appURL);
    await expect(page.locator("#account-list")).toContainText("Main Account");
    await use(page);
    expect(errors).toEqual([]);
  },
});
export { expect };
