import type { Page } from "@playwright/test";

/**
 * Phase 6B E2E helpers.
 *
 * No hardcoded/shared credential is used anywhere in these E2E tests —
 * each test signs up its OWN fresh, uniquely-generated throwaway account
 * through the real signup flow (the same one a real student uses), so
 * there is nothing that needs to live in an env var or be committed as a
 * "test secret." The password is a fixed, clearly-non-sensitive,
 * dev-local-only string (this MongoDB instance is the same local
 * development database every other test in this project already writes
 * to — never a shared/production credential).
 */
export interface TestAccount {
  name: string;
  email: string;
  password: string;
}

export function uniqueTestAccount(label: string): TestAccount {
  const unique = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    name: `E2E ${label}`,
    email: `e2e-${label}-${unique}@example.test`,
    password: "E2E-test-password-1",
  };
}

/** Signs up a fresh account via the real UI form and waits for the
 * post-signup redirect to /dashboard (signup auto-signs-in — see
 * app/(auth)/signup/page.tsx). */
export async function signUp(page: Page, account: TestAccount): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Name").fill(account.name);
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByLabel("Confirm password").fill(account.password);
  await page.getByRole("button", { name: "Sign up" }).click();
  await page.waitForURL("/dashboard");
}

export async function logOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Open user menu" }).click();
  await page.getByRole("menuitem", { name: "Log out" }).click();
  await page.waitForURL("/");
}

export async function logIn(page: Page, account: TestAccount): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(account.email);
  // { exact: true } -- otherwise this also matches the password-visibility
  // toggle button, whose own accessible name ("Show password") contains
  // "password" as a substring (Playwright's default getByLabel match).
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.waitForURL("/dashboard");
}

/** Creates a workspace from the dashboard (must already be there) and
 * waits for its own card to appear. Returns that specific card's "Open"
 * link href (not `.first()` — the dashboard may already list other
 * workspaces, so this locates the card by its exact, just-created name).
 *
 * NOTE: a dashboard workspace card's name renders via shadcn's
 * `CardTitle`, which is a plain `<div>` (confirmed:
 * components/ui/card.tsx), not a semantic heading element — `getByText`
 * is the correct query here. The workspace's own detail page
 * (app/(dashboard)/workspace/[id]/page.tsx) DOES render its name in a
 * real `<h1>`, so callers checking that page should keep using
 * `getByRole("heading", ...)`. */
export async function createWorkspace(page: Page, name: string): Promise<string> {
  await page.getByRole("button", { name: "Create Workspace" }).click();
  await page.getByLabel("Workspace name").fill(name);
  await page.getByRole("dialog").getByRole("button", { name: "Create Workspace" }).click();

  // Scoped to the Card's own root element specifically (its shadcn
  // className, components/ui/card.tsx) -- a bare `div:has(text)` locator
  // matches every ANCESTOR div too (the grid wrapper, the page body,
  // etc.), and `.last()`/`.first()` on that set does not reliably land on
  // the Card itself (verified: `.last()` actually landed on CardTitle's
  // own innermost div, too narrow to also contain the Open link).
  const card = page.locator(".rounded-xl.border.bg-card", { has: page.getByText(name, { exact: true }) });
  const openLink = card.getByRole("link", { name: "Open" });
  await openLink.waitFor();
  const href = await openLink.getAttribute("href");
  if (!href) {
    throw new Error(`Workspace card for "${name}" has no Open link href.`);
  }
  return href;
}
