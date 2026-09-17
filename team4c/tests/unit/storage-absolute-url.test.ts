// @vitest-environment node
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { rm } from "fs/promises";
import path from "path";

/**
 * MVP M6 local-stack correction — proves `storeFile()`'s local
 * development mock now produces a FULLY QUALIFIED http(s) URL (Team
 * 4A's frozen canonical contract requires `file_url` to start with
 * `http://`/`https://` -- a relative path like
 * `/api/local-storage/...` fails validation before Team 4A's secure
 * remote-source resolver ever runs).
 */

const originalAuthUrl = process.env.AUTH_URL;
const originalAuthSecret = process.env.AUTH_SECRET;
const originalStorageProvider = process.env.STORAGE_PROVIDER;

function fakeFile(name: string, contents: string) {
  return {
    name,
    async arrayBuffer() {
      return new TextEncoder().encode(contents).buffer;
    },
  };
}

beforeEach(() => {
  delete process.env.STORAGE_PROVIDER;
  process.env.AUTH_SECRET = "test-secret-for-local-storage-capability-tokens";
});

afterEach(async () => {
  if (originalAuthUrl === undefined) {
    delete process.env.AUTH_URL;
  } else {
    process.env.AUTH_URL = originalAuthUrl;
  }
  if (originalAuthSecret === undefined) {
    delete process.env.AUTH_SECRET;
  } else {
    process.env.AUTH_SECRET = originalAuthSecret;
  }
  if (originalStorageProvider === undefined) {
    delete process.env.STORAGE_PROVIDER;
  } else {
    process.env.STORAGE_PROVIDER = originalStorageProvider;
  }
  await rm(path.join(process.cwd(), ".local-uploads"), { recursive: true, force: true });
  vi.resetModules();
});

describe("storeFile — MVP M6 local-stack correction: absolute storage URL", () => {
  it("produces an absolute http(s) URL, using AUTH_URL as the local public origin", async () => {
    process.env.AUTH_URL = "http://localhost:3000";
    const { storeFile } = await import("@/services/storage");

    const result = await storeFile(fakeFile("notes.pdf", "pdf bytes"), "workspace-1");

    expect(result.storageUrl).toMatch(/^https?:\/\//);
    expect(result.storageUrl.startsWith("http://localhost:3000/api/local-storage/workspace-1/")).toBe(true);
  });

  it("respects a configured AUTH_URL pointing at a different local host/port (M6: reachable by Team 4A on 127.0.0.1:8001)", async () => {
    process.env.AUTH_URL = "http://127.0.0.1:3000";
    const { storeFile } = await import("@/services/storage");

    const result = await storeFile(fakeFile("notes.pdf", "pdf bytes"), "workspace-1");

    expect(result.storageUrl.startsWith("http://127.0.0.1:3000/api/local-storage/")).toBe(true);
  });

  it("falls back to http://localhost:3000 if AUTH_URL is entirely unset — never produces a relative URL", async () => {
    delete process.env.AUTH_URL;
    const { storeFile } = await import("@/services/storage");

    const result = await storeFile(fakeFile("notes.pdf", "pdf bytes"), "workspace-1");

    expect(result.storageUrl.startsWith("http://localhost:3000/api/local-storage/")).toBe(true);
  });

  it("preserves the exact existing path shape (workspaceId/publicId), only prefixing the origin", async () => {
    process.env.AUTH_URL = "http://localhost:3000";
    const { storeFile } = await import("@/services/storage");

    const result = await storeFile(fakeFile("notes.pdf", "pdf bytes"), "workspace-42");

    const url = new URL(result.storageUrl);
    expect(url.pathname.startsWith("/api/local-storage/workspace-42/")).toBe(true);
    expect(decodeURIComponent(url.pathname.split("/").pop()!)).toBe(result.publicId);
  });

  it("YouTube references remain untouched by this correction (never relative to begin with)", async () => {
    const { referenceYoutubeUrl } = await import("@/services/storage");

    const result = referenceYoutubeUrl("https://www.youtube.com/watch?v=abc123");

    expect(result.storageUrl).toBe("https://www.youtube.com/watch?v=abc123");
  });
});
