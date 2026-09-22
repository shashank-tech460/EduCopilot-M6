import { expect, test } from "@playwright/test";

test("Phase 2 smoke test — landing page loads with nav and heading", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("link", { name: /Educational Intelligence Copilot/i })).toBeVisible();
  // Phase 6D: updated to match the actual current landing-page copy
  // (app/page.tsx's real <h1>) -- the previous assertion text
  // ("Ask your own course material anything") predates a landing-page
  // copy change and no longer matched anything on the page (flagged as
  // a known, pre-existing, unrelated issue in Phase 6B/6C; fixed here
  // per Phase 6D's explicit instruction to make the smallest correct
  // test update, not to change the application to satisfy a stale test).
  await expect(
    page.getByRole("heading", { name: /Learn from your own course material/i })
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Log in" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign up" })).toBeVisible();
});
