import { expect, test } from "@playwright/test";

test("Phase 2 smoke test — landing page loads with nav and heading", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("link", { name: /Educational Intelligence Copilot/i })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /Ask your own course material anything/i })
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Log in" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign up" })).toBeVisible();
});
