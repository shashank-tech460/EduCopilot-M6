import { expect, test } from "@playwright/test";

import { createWorkspace, signUp, uniqueTestAccount } from "./helpers";

/**
 * Phase 6B — Journey C (workspace isolation), real E2E.
 *
 * Proves, through the real UI + real Auth.js session + real MongoDB
 * `assertOwnership()` boundary (never mocked), that one account's
 * workspace is invisible to a different account — both on the dashboard
 * listing and via direct URL navigation to the workspace's own page.
 * This is the strongest, most meaningful form of the isolation check the
 * Phase 6B master prompt asks for ("a material/chat from workspace A
 * does not appear in B"): it exercises the real `lib/ownership.ts`
 * code path end-to-end, the same one Phase 6A's forensic audit traced
 * and verified by static code read — this test proves it live.
 */
test.describe("Journey C — workspace isolation across accounts", () => {
  test("account B cannot see or open account A's workspace", async ({ browser }) => {
    const accountA = uniqueTestAccount("iso-a");
    const accountB = uniqueTestAccount("iso-b");
    const workspaceAName = `Private Workspace A ${Date.now()}`;

    // Two fully independent browser contexts -- separate cookie jars, so
    // this genuinely proves cross-SESSION isolation, not just
    // within-one-page-state isolation.
    const contextA = await browser.newContext();
    const pageA = await contextA.newPage();
    await signUp(pageA, accountA);
    const workspaceAHref = await createWorkspace(pageA, workspaceAName);

    const contextB = await browser.newContext();
    const pageB = await contextB.newPage();
    await signUp(pageB, accountB);

    // B's own dashboard must never list A's workspace. (Dashboard workspace
    // cards render via shadcn CardTitle -> plain <div>, not a heading role
    // — see helpers.ts's createWorkspace() note — so getByText, not
    // getByRole("heading"), is the correct query here.)
    await expect(pageB.getByRole("heading", { name: "Your Workspaces" })).toBeVisible();
    await expect(pageB.getByText(workspaceAName, { exact: true })).not.toBeVisible();
    await expect(pageB.getByText("You don't have any workspaces yet.")).toBeVisible();

    // B navigating DIRECTLY to A's workspace URL must be rejected --
    // the real security boundary (assertOwnership -> 404, not a UI-only
    // hide), not merely "the link isn't shown."
    await pageB.goto(workspaceAHref);
    // app/not-found.tsx's own real copy -- also what renders for "exists
    // but isn't yours" by deliberate design (see that file's own comment):
    // indistinguishable from a genuinely missing route.
    await expect(pageB.getByText("Page not found")).toBeVisible();
    await expect(pageB.getByRole("heading", { name: workspaceAName })).not.toBeVisible();

    await contextA.close();
    await contextB.close();
  });

  test("two workspaces under the SAME account stay independent of each other", async ({ page }) => {
    const account = uniqueTestAccount("iso-same");
    await signUp(page, account);

    const nameOne = `Course One ${Date.now()}`;
    const hrefOne = await createWorkspace(page, nameOne);
    const nameTwo = `Course Two ${Date.now()}`;
    const hrefTwo = await createWorkspace(page, nameTwo);

    expect(hrefOne).not.toBe(hrefTwo);

    await page.goto(hrefOne);
    await expect(page.getByRole("heading", { name: nameOne })).toBeVisible();
    await expect(page.getByRole("heading", { name: nameTwo })).not.toBeVisible();

    await page.goto(hrefTwo);
    await expect(page.getByRole("heading", { name: nameTwo })).toBeVisible();
    await expect(page.getByRole("heading", { name: nameOne })).not.toBeVisible();
  });
});
