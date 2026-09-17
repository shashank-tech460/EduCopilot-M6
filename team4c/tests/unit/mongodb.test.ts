import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";

/**
 * Tests the connection helper's guard clause only — must NOT open a real
 * MongoDB connection, and must fail immediately, not hang.
 *
 * Root cause of a previously-observed timeout/hang: `delete
 * process.env.MONGODB_URI` alone isn't a reliable guarantee in every
 * environment. Vite/Vitest's default env loading can populate
 * `process.env` from a real `.env.local` (e.g. on a machine with a real
 * local MongoDB configured for manual testing), and this module also
 * caches its connection *promise* on `globalThis` across module resets, so
 * a real, unreachable-during-tests URI could leak in and cause an actual
 * connection attempt that hangs for the driver's default server-selection
 * timeout — which looks exactly like a stuck test, not a clean failure.
 *
 * Fixed on two sides:
 *  1. Here: `vi.stubEnv` (Vitest's supported override mechanism, more
 *     reliable than mutating `process.env` directly when Vite's own env
 *     system is involved) PLUS an explicit reset of the module's global
 *     connection cache, so no leftover state from any other test/process
 *     can possibly cause a real connection attempt in this test.
 *  2. lib/mongodb.ts: added `serverSelectionTimeoutMS` so that even if a
 *     real (but unreachable) URI were ever used here, it fails in seconds
 *     rather than hanging for the driver's ~30s default — this matters for
 *     real usage too, not just this test.
 */
describe("connectToDatabase", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("MONGODB_URI", "");
    delete process.env.MONGODB_URI;
    // Guarantees no other test/process left a pending real connection
    // promise cached on globalThis that this test could accidentally await.
    // Cast rather than re-declaring `var _mongooseCache` here, since
    // lib/mongodb.ts already declares that global with its own type —
    // redeclaring it with a different shape is a TypeScript error
    // ("subsequent variable declarations must have the same type").
    (globalThis as typeof globalThis & { _mongooseCache?: unknown })._mongooseCache = undefined;
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    (globalThis as typeof globalThis & { _mongooseCache?: unknown })._mongooseCache = undefined;
  });

  it("throws a clear error immediately when MONGODB_URI is not set, without attempting a connection", async () => {
    const { connectToDatabase } = await import("@/lib/mongodb");

    await expect(connectToDatabase()).rejects.toThrow(/MONGODB_URI is not set/);
  }, 2000); // Deliberately tight timeout — this must fail immediately, not after any network wait.
});
