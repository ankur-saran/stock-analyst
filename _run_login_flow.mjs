import { chromium } from "playwright";

const OUT = process.env.SHOT_DIR || ".";
const log = (...a) => console.log("[flow]", ...a);

const browser = await chromium.launch({ channel: "msedge", headless: true });
const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
const page = await ctx.newPage();
page.on("console", (m) => log("page.console:", m.type(), m.text()));

try {
  // 1. Hit a protected route -> should redirect to our /login page.
  log("goto /coverages (protected)");
  await page.goto("http://localhost:3000/coverages", { waitUntil: "networkidle", timeout: 60000 });
  log("landed on:", page.url());
  await page.screenshot({ path: `${OUT}/01-login.png`, fullPage: true });

  // 2. Click the app's "Sign in with your organization" button -> Keycloak.
  const signInBtn = page.getByRole("button", { name: /sign in/i });
  await signInBtn.first().click({ timeout: 15000 });
  log("clicked sign-in, now at:", page.url());

  // 3. Keycloak login form.
  await page.waitForSelector("#username", { timeout: 30000 });
  await page.fill("#username", "analyst-a");
  await page.fill("#password", "TestPass123!");
  await page.screenshot({ path: `${OUT}/02-keycloak.png`, fullPage: true });
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle", timeout: 60000 }).catch(() => {}),
    page.click("#kc-login"),
  ]);

  // 4. Wait to land back on the app.
  await page.waitForURL(/localhost:3000/, { timeout: 60000 }).catch(() => {});
  await page.waitForLoadState("networkidle", { timeout: 60000 }).catch(() => {});
  log("post-login url:", page.url());

  // 4b. Is a session actually established? Dump it.
  const session = await page.evaluate(async () => {
    const r = await fetch("/api/auth/session");
    return await r.json();
  });
  log("session:", JSON.stringify(session));
  if (session.accessToken) {
    const claims = await page.evaluate((tok) => {
      const p = JSON.parse(atob(tok.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      return { aud: p.aud, azp: p.azp, iss: p.iss, tenant_id: p.tenant_id, realm_access: p.realm_access };
    }, session.accessToken);
    log("token-claims:", JSON.stringify(claims));
    const fs = await import("node:fs");
    fs.writeFileSync(`${OUT}/token.txt`, session.accessToken);
    log("wrote token.txt");
  }

  // 4c. Now explicitly navigate to the protected dashboard (signIn used no
  //     callbackUrl, so it defaulted back to /login).
  log("goto /coverages with session cookie present");
  await page.goto("http://localhost:3000/coverages", { waitUntil: "networkidle", timeout: 60000 });
  log("dashboard url:", page.url());
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${OUT}/03-dashboard.png`, fullPage: true });

  // 5. Report page title + a bit of visible text for sanity.
  log("title:", await page.title());
  const bodyText = (await page.locator("body").innerText()).slice(0, 800).replace(/\n+/g, " | ");
  log("body-excerpt:", bodyText);
  log("DONE");
} catch (e) {
  log("ERROR:", e.message);
  await page.screenshot({ path: `${OUT}/99-error.png`, fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await browser.close();
}
