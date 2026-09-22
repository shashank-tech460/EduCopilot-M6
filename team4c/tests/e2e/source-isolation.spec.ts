import path from "path";
import { expect, test } from "@playwright/test";

import { createWorkspace, signUp, uniqueTestAccount } from "./helpers";

/**
 * Phase 6D — Step 12 (PDF + YouTube source isolation) and Step 16
 * (document scope), real E2E.
 *
 * ONE account, TWO real workspaces: Workspace A gets the PDF fixture,
 * Workspace B gets the stable YouTube fixture. Verifies a question asked
 * in A never cites B's video, and vice versa -- exercising the real
 * chain: Team4C ownership -> lib/sourceScope.ts -> Team4B workspace
 * identity (JWT claim, never a request-body field) -> real Qdrant
 * workspace-scoped retrieval -> lib/workspaceFilter.ts citation
 * filtering. Team4B itself is never modified; this only proves the
 * existing, real isolation boundary holds under live integration.
 */
async function isReachable(url: string, timeoutMs = 3000): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const response = await fetch(url, { signal: controller.signal }).catch(() => null);
    clearTimeout(timer);
    return response !== null;
  } catch {
    return false;
  }
}

const STABLE_YOUTUBE_URL = "https://youtu.be/wdaBwIv7Jso";

test.describe("Phase 6D — cross-source workspace isolation + document scope", () => {
  test.beforeEach(async () => {
    const teamAUrl = process.env.TEAM_A_API_URL ?? "http://localhost:8001";
    const teamBUrl = process.env.TEAM_B_API_URL ?? "http://localhost:8002";
    const [teamAUp, teamBUp] = await Promise.all([isReachable(teamAUrl), isReachable(teamBUrl)]);

    test.skip(
      !teamAUp || !teamBUp,
      `Team4A (${teamAUrl}, reachable=${teamAUp}) and/or Team4B (${teamBUrl}, reachable=${teamBUp}) are not running.`
    );
  });

  test("PDF in workspace A and YouTube in workspace B never cross-cite; document scope restricts retrieval to the selected material", async ({
    page,
  }) => {
    test.setTimeout(480_000); // two full real ingestion + generation cycles

    const account = uniqueTestAccount("src-iso");
    await signUp(page, account);

    // --- Workspace A: PDF only ---
    const hrefA = await createWorkspace(page, `Source Isolation A ${Date.now()}`);
    await page.goto(hrefA);
    await page.getByRole("tab", { name: "Materials" }).click({ timeout: 2000 }).catch(() => undefined);
    await page.getByRole("button", { name: "Add Material" }).click();
    const fixturePath = path.join(__dirname, "..", "fixtures", "sample-course-notes.pdf");
    await page.getByLabel("PDF file").setInputFiles(fixturePath);
    await page.getByRole("dialog").getByRole("button", { name: "Add Material" }).click();
    await expect(page.getByText("Ready")).toBeVisible({ timeout: 120_000 });

    // --- Workspace B: YouTube only ---
    await page.goto("/dashboard");
    const hrefB = await createWorkspace(page, `Source Isolation B ${Date.now()}`);
    await page.goto(hrefB);
    await page.getByRole("tab", { name: "Materials" }).click({ timeout: 2000 }).catch(() => undefined);
    await page.getByRole("button", { name: "Add Material" }).click();
    await page.getByRole("button", { name: "Add YouTube URL" }).click();
    await page.getByLabel("YouTube URL").fill(STABLE_YOUTUBE_URL);
    await page.getByRole("dialog").getByRole("button", { name: "Add Material" }).click();
    await expect(page.getByText("Ready")).toBeVisible({ timeout: 180_000 });

    // --- Ask a real question in B (YouTube-only workspace) ---
    await page.getByRole("tab", { name: "AI Tutor" }).click({ timeout: 2000 }).catch(() => undefined);
    const chatInputB = page.getByLabel("Chat message");
    await expect(chatInputB).toBeEnabled({ timeout: 30_000 });
    await chatInputB.fill("What is this video about?");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Thinking…")).toBeVisible();
    await expect(page.getByText("Thinking…")).not.toBeVisible({ timeout: 150_000 });

    // Workspace B's answer must never cite the PDF from workspace A --
    // the real isolation boundary, not a UI-only hide.
    await expect(page.getByRole("button", { name: /sample-course-notes/i })).toHaveCount(0);

    // --- Ask a real question in A (PDF-only workspace) ---
    await page.goto(hrefA);
    await page.getByRole("tab", { name: "AI Tutor" }).click({ timeout: 2000 }).catch(() => undefined);
    const chatInputA = page.getByLabel("Chat message");
    await expect(chatInputA).toBeEnabled({ timeout: 30_000 });
    await chatInputA.fill("What is this document about?");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Thinking…")).toBeVisible();
    await expect(page.getByText("Thinking…")).not.toBeVisible({ timeout: 150_000 });

    // Workspace A's answer must never cite workspace B's YouTube video.
    await expect(page.getByRole("button", { name: /Trigonometry/i })).toHaveCount(0);
    // And it should correctly cite its own real PDF (a retrieval-quality
    // sanity check, not just an absence check).
    await expect(page.getByRole("button", { name: /sample-course-notes/i }).first()).toBeVisible({
      timeout: 5000,
    });

    // --- Step 16: document scope, using workspace A's single ready material ---
    // Selecting the scope picker and confirming the one available
    // document exercises the real lib/sourceScope.ts
    // validateAndNormalizeSourceScope()/resolveEffectiveDocumentIds()
    // path end-to-end (server-revalidated on every chat call, never
    // trusting a client-supplied document_ids list directly) -- the same
    // contract locked by tests/unit/scope-route.test.ts and
    // tests/unit/sourceScope.test.ts, now proven live.
    const scopeButton = page.getByRole("button", { name: "Using all workspace materials" });
    await scopeButton.click();
    const pdfOption = page.getByRole("menuitemcheckbox", { name: /sample-course-notes/i });
    await expect(pdfOption).toBeVisible({ timeout: 5000 });
    await pdfOption.click();
    await page.keyboard.press("Escape");
    // The trigger label reflects the real, server-confirmed scope change
    // (useSourceScope -> PATCH /api/conversations/[id]/scope), not just
    // optimistic client state.
    await expect(page.getByRole("button", { name: /Using: sample-course-notes/i })).toBeVisible({
      timeout: 10_000,
    });

    // A follow-up question, now explicitly scoped, still gets a real,
    // grounded, correctly-cited answer -- the scope narrows retrieval
    // without breaking it.
    await chatInputA.fill("Summarize the key point.");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Thinking…")).toBeVisible();
    await expect(page.getByText("Thinking…")).not.toBeVisible({ timeout: 150_000 });
    await expect(page.getByRole("button", { name: /sample-course-notes/i }).first()).toBeVisible({
      timeout: 5000,
    });
  });
});
