import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

import { createWorkspace, signUp, uniqueTestAccount } from "./helpers";

/**
 * Phase 6E — automated accessibility regression (master prompt §15/§23).
 *
 * Real axe-core scans (WCAG 2A/2AA rule set) against the actual rendered
 * pages, not a hand-picked assertion list — this is intentionally the
 * kind of test that can fail on something nobody thought to check by
 * hand. Runs against pages that don't require live Team4A/Team4B (the
 * real RAG chat screen is exercised by the accessible-name/role
 * assertions already embedded throughout core-rag.spec.ts/
 * youtube-rag.spec.ts instead, since a full axe scan mid-stream would
 * need those live services and isn't needed to validate this phase's
 * UI-only changes).
 */
test.describe("Phase 6E — accessibility (axe)", () => {
  test("landing page has no detectable WCAG 2A/2AA violations", async ({ page }) => {
    await page.goto("/");
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });

  test("login page has no detectable WCAG 2A/2AA violations", async ({ page }) => {
    await page.goto("/login");
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });

  test("signup page has no detectable WCAG 2A/2AA violations", async ({ page }) => {
    await page.goto("/signup");
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });

  test("dashboard (app shell + workspace grid) has no detectable WCAG 2A/2AA violations", async ({ page }) => {
    const account = uniqueTestAccount("a11y");
    await signUp(page, account);

    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });

  test("workspace page (sidebar + materials panel, no live services) has no detectable WCAG 2A/2AA violations", async ({
    page,
  }) => {
    const account = uniqueTestAccount("a11y-ws");
    await signUp(page, account);
    const href = await createWorkspace(page, `Accessibility ${Date.now()}`);
    await page.goto(href);

    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });
});
