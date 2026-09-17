// @vitest-environment node
import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "fs";
import { join } from "path";

/**
 * Phase 2D — two structural checks the governing task explicitly
 * requires that don't fit naturally into the existing per-module test
 * files:
 *
 *   R. browser/client code cannot access the JWT private key
 *   T. no legacy /ingest body is silently accepted as canonical
 *      production input
 */

const PROJECT_ROOT = join(__dirname, "..", "..");
const CLIENT_SURFACE_DIRS = ["app", "components", "hooks", "store"];

function listTsFiles(dir: string): string[] {
  let results: string[] = [];
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return results;
  }
  for (const entry of entries) {
    if (entry === "node_modules" || entry === ".next" || entry.startsWith(".")) continue;
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      results = results.concat(listTsFiles(full));
    } else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.(ts|tsx)$/.test(entry) && !full.includes(`${join("app", "api")}`)) {
      // Excludes app/api/** (server-only route handlers) -- those ARE
      // permitted to reach server-only modules; this check is about the
      // BROWSER-RENDERED surface (pages, components, hooks, client store).
      results.push(full);
    }
  }
  return results;
}

describe("Phase 2D — R: browser/client code cannot access the JWT private key", () => {
  it("no file under the browser-rendered surface imports lib/serviceJwt or services/teamA/client", () => {
    const offending: string[] = [];
    for (const dir of CLIENT_SURFACE_DIRS) {
      for (const file of listTsFiles(join(PROJECT_ROOT, dir))) {
        const content = readFileSync(file, "utf-8");
        if (content.includes("lib/serviceJwt") || content.includes("services/teamA/client")) {
          offending.push(file);
        }
      }
    }
    expect(offending).toEqual([]);
  });

  it("lib/serviceJwt.ts never exports the raw private key material, only a signing function", () => {
    const content = readFileSync(join(PROJECT_ROOT, "lib", "serviceJwt.ts"), "utf-8");
    // The module exports a function that CONSUMES a private key (passed
    // in via config) and returns a signed token -- it must never export
    // the key itself, or a getter that returns it unsigned/raw.
    expect(content).not.toMatch(/export\s+(const|function)\s+getPrivateKey/);
    expect(content).not.toMatch(/export\s+.*privateKey\s*[:=]/);
  });
});

describe("Phase 2D — T: legacy request shape is never silently accepted as canonical", () => {
  it("services/teamA/client.ts never references fileUrl/fileType/workspaceId (the pre-Phase-2A shape)", () => {
    const content = readFileSync(join(PROJECT_ROOT, "services", "teamA", "client.ts"), "utf-8");
    expect(content).not.toMatch(/\bfileUrl\b/);
    expect(content).not.toMatch(/\bfileType\b/);
    expect(content).not.toMatch(/\bworkspaceId\b/);
  });

  it("TeamASubmitRequest's canonical fields are exactly document_id/file_type/file_url", async () => {
    // A compile-time-enforced structural check: constructing an object
    // with the legacy field names against the current type would fail
    // `tsc --noEmit` (already verified separately) -- this runtime
    // check confirms the exact field SET a real serialized request
    // contains, as an additional, independent guard.
    const { realTeamA } = await import("@/services/teamA/client");
    process.env.TEAM_A_API_URL = "https://team-a.example.test";
    const { generateKeyPair, exportPKCS8 } = await import("jose");
    const { privateKey } = await generateKeyPair("ES256", { extractable: true });
    process.env.SERVICE_JWT_PRIVATE_KEY = await exportPKCS8(privateKey);
    process.env.SERVICE_JWT_KID = "k1";
    process.env.SERVICE_JWT_ISSUER = "https://educopilot.internal";

    let capturedBody: string | undefined;
    const originalFetch = global.fetch;
    global.fetch = (async (_url: string, options: RequestInit) => {
      capturedBody = options.body as string;
      return { ok: true, json: async () => ({ document_id: "doc-1" }) } as Response;
    }) as typeof fetch;

    try {
      await realTeamA.submit(
        { document_id: "doc-1", file_type: "pdf", file_url: "https://x.test/f.pdf" },
        { sub: "u1", workspace_id: "w1" }
      );
    } finally {
      global.fetch = originalFetch;
    }

    const parsed = JSON.parse(capturedBody!);
    expect(Object.keys(parsed).sort()).toEqual(["document_id", "file_type", "file_url"]);
  });
});

// ============================================================
// Phase 2E — additional structural checks (mirrors Phase 2D for Team B)
// ============================================================

describe("Phase 2E — browser code cannot reach services/teamB/client either", () => {
  it("no file under the browser-rendered surface imports services/teamB/client directly", () => {
    const offending: string[] = [];
    for (const dir of CLIENT_SURFACE_DIRS) {
      for (const file of listTsFiles(join(PROJECT_ROOT, dir))) {
        const content = readFileSync(file, "utf-8");
        if (content.includes("services/teamB/client")) {
          offending.push(file);
        }
      }
    }
    expect(offending).toEqual([]);
  });
});

describe("Phase 2E — Team B real client contract", () => {
  it("services/teamB/client.ts never references the old static TEAM_B_API_KEY", () => {
    const content = readFileSync(join(PROJECT_ROOT, "services", "teamB", "client.ts"), "utf-8");
    expect(content).not.toMatch(/TEAM_B_API_KEY/);
  });

  it("services/teamB/client.ts calls exactly /api/v1/query", () => {
    const content = readFileSync(join(PROJECT_ROOT, "services", "teamB", "client.ts"), "utf-8");
    expect(content).toMatch(/\/api\/v1\/query/);
  });
});
