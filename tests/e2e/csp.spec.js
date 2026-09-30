import { test, expect } from "./fixtures.js";

test("enforced CSP blocks inline scripts and event handlers", async ({ appURL, browser }) => {
  const page = await browser.newPage();
  try {
    const response = await page.goto(appURL + "/login");
    const policy = response.headers()["content-security-policy"];
    expect(policy).toContain("script-src 'self'");
    expect(policy).toContain("script-src-attr 'none'");
    expect(policy).toContain("style-src-attr 'none'");
    expect(response.headers()["content-security-policy-report-only"]).toBeUndefined();
    expect(response.headers()["x-frame-options"]).toBe("DENY");

    await page.evaluate(() => {
      window.inlineScriptRan = false;
      window.inlineHandlerRan = false;
      window.blockedPolicies = [];
      document.addEventListener("securitypolicyviolation", event => {
        window.blockedPolicies.push({ directive: event.effectiveDirective, disposition: event.disposition });
      });
      const script = document.createElement("script");
      script.textContent = "window.inlineScriptRan = true";
      document.body.append(script);
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("onclick", "window.inlineHandlerRan = true");
      document.body.append(button);
      button.click();
    });

    await expect.poll(() => page.evaluate(() => window.blockedPolicies.length)).toBeGreaterThanOrEqual(2);
    const result = await page.evaluate(() => ({
      script: window.inlineScriptRan,
      handler: window.inlineHandlerRan,
      violations: window.blockedPolicies,
    }));
    expect(result.script).toBe(false);
    expect(result.handler).toBe(false);
    expect(result.violations.every(event => event.disposition === "enforce")).toBe(true);
    expect(result.violations.some(event => event.directive.startsWith("script-src"))).toBe(true);
  } finally {
    await page.close();
  }
});
