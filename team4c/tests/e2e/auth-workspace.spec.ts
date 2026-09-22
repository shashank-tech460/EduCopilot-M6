import { expect, test } from "@playwright/test";

import { createWorkspace, logIn, logOut, signUp, uniqueTestAccount } from "./helpers";

/**
 * Phase 6B — Journey A (authentication + workspace), real E2E.
 *
 * Exercises the real Next.js server, real Auth.js credential flow, and
 * real MongoDB (via `services/teamA`/`teamB` are never reached by this
 * journey at all — signup/login/workspace CRUD only ever touch Team4C's
 * own database, so this journey runs fully for real regardless of
 * whether Team4A/Team4B happen to be up).
 */
test.describe("Journey A — signup, workspace creation, session persistence", () => {
  test("signup creates a real account, lands on the dashboard, and a created workspace persists across logout/login", async ({
    page,
  }) => {
    const account = uniqueTestAccount("auth");

    await signUp(page, account);
    await expect(page.getByRole("heading", { name: `Welcome, ${account.name}` })).toBeVisible();

    const workspaceName = `E2E Workspace ${Date.now()}`;
    const workspaceHref = await createWorkspace(page, workspaceName);
    expect(workspaceHref).toMatch(/^\/workspace\/[a-f0-9]{24}$/);

    // Opening it shows the real, server-persisted workspace (not a
    // client-only optimistic card) — a fresh navigation re-fetches it.
    await page.goto(workspaceHref);
    await expect(page.getByRole("heading", { name: workspaceName })).toBeVisible();

    await logOut(page);
    await expect(page).toHaveURL("/");

    // A logged-out visitor is redirected away from a protected route —
    // proves the auth boundary is real, not merely client-side UI state.
    await page.goto(workspaceHref);
    await page.waitForURL(/\/login/);

    await logIn(page, account);
    await expect(page.getByRole("heading", { name: `Welcome, ${account.name}` })).toBeVisible();
    // Dashboard workspace card (shadcn CardTitle -> plain <div>, not a
    // heading role) — see helpers.ts's createWorkspace() note.
    await expect(page.getByText(workspaceName, { exact: true })).toBeVisible();

    await page.goto(workspaceHref);
    await expect(page.getByRole("heading", { name: workspaceName })).toBeVisible();
  });

  test("signing up with an email that already exists is rejected, not silently allowed", async ({ page }) => {
    const account = uniqueTestAccount("dup");
    await signUp(page, account);
    await logOut(page);

    await page.goto("/signup");
    await page.getByLabel("Name").fill(account.name);
    await page.getByLabel("Email").fill(account.email);
    await page.getByLabel("Password", { exact: true }).fill(account.password);
    await page.getByLabel("Confirm password").fill(account.password);
    await page.getByRole("button", { name: "Sign up" }).click();

    await expect(page.getByText("An account with this email already exists.")).toBeVisible();
    await expect(page).toHaveURL("/signup");
  });
});
