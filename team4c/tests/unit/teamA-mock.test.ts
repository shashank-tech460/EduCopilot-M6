import { describe, expect, it, vi, afterEach } from "vitest";

import { mockTeamA } from "@/services/teamA/mock";

/**
 * Tests services/teamA/mock.ts directly — no route, no DB. Covers the two
 * Phase 6 requirements that are specifically about the mock's behavior:
 * "mock Team A hand-off works" and "mock Team A does not call an external
 * API" (the latter verified by spying on global fetch, not just assumed
 * from reading the code).
 */
describe("mockTeamA", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("submit() returns a deterministic ingestionId without calling fetch", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const result = await mockTeamA.submit(
      {
        document_id: "workspace-1-doc-1",
        file_type: "mp4",
        file_url: "https://example.test/lecture.mp4",
      },
      { sub: "user-1", workspace_id: "workspace-1" }
    );

    expect(result.ingestionId).toMatch(/^mock-/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("checkStatus() immediately reports 'ready' without calling fetch", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const result = await mockTeamA.checkStatus("mock-some-id");

    expect(result.status).toBe("ready");
    expect(result.error).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("produces a different ingestionId on each call", async () => {
    const a = await mockTeamA.submit(
      {
        document_id: "doc-a",
        file_type: "pdf",
        file_url: "https://example.test/a.pdf",
      },
      { sub: "user-1", workspace_id: "workspace-1" }
    );
    const b = await mockTeamA.submit(
      {
        document_id: "doc-b",
        file_type: "pdf",
        file_url: "https://example.test/b.pdf",
      },
      { sub: "user-1", workspace_id: "workspace-1" }
    );
    expect(a.ingestionId).not.toBe(b.ingestionId);
  });
});
