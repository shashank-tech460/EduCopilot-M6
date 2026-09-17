import { describe, expect, it } from "vitest";
import path from "path";

import { resolveLocalStoragePath } from "@/services/storage";

/**
 * Verifies resolveLocalStoragePath() rejects any publicId that would
 * resolve outside the intended workspace directory, regardless of how many
 * `../` segments or what form they take. This is the fix for a real path
 * traversal gap: the local-storage serve route previously joined a
 * URL-derived `publicId` directly into a filesystem path with no check
 * that the result stayed inside that workspace's directory.
 */
describe("resolveLocalStoragePath", () => {
  const workspaceId = "workspace-123";

  it("resolves a normal publicId to a path inside the workspace directory", () => {
    const result = resolveLocalStoragePath(workspaceId, "abc-lecture.pdf");
    expect(result).not.toBeNull();
    expect(result).toContain(path.join(".local-uploads", workspaceId, "abc-lecture.pdf"));
  });

  it("rejects a publicId that attempts to traverse out of the workspace directory", () => {
    const result = resolveLocalStoragePath(workspaceId, "../../../etc/passwd");
    expect(result).toBeNull();
  });

  it("rejects a publicId that attempts to traverse into a sibling workspace's directory", () => {
    const result = resolveLocalStoragePath(workspaceId, "../other-workspace-id/secret.pdf");
    expect(result).toBeNull();
  });

  it("rejects an absolute path passed as publicId", () => {
    const result = resolveLocalStoragePath(workspaceId, "/etc/passwd");
    expect(result).toBeNull();
  });

  it("rejects a publicId that traverses out and back in to a different location", () => {
    // Nominally "returns" to a workspace-shaped path, but actually escapes
    // to a completely different root first — must still be rejected.
    const result = resolveLocalStoragePath(workspaceId, `../../../tmp/${workspaceId}/x`);
    expect(result).toBeNull();
  });
});
