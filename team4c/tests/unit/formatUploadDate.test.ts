import { describe, expect, it } from "vitest";

import { formatUploadDate } from "@/components/shared/workspace-files";

/**
 * Regression test for a real SSR/client hydration mismatch:
 *
 *   SERVER: "Aug 28, 2026"   CLIENT: "28 Aug 2026"
 *
 * Root cause: `toLocaleDateString(undefined, {...})` let the output depend
 * on the runtime's default locale, which differs between the Node.js
 * server process (SSR) and the browser (client render) — not a bug in the
 * date value itself, purely a formatting non-determinism.
 *
 * The fix pins an explicit locale ("en-US") so the same ISO input always
 * produces the exact same string everywhere, regardless of either
 * environment's actual locale configuration. These tests verify that
 * determinism directly, not just that "some string" renders.
 */
describe("formatUploadDate — deterministic, locale-independent formatting", () => {
  it("formats a known date to the exact expected string", () => {
    expect(formatUploadDate("2026-01-15T00:00:00.000Z")).toBe("Jan 15, 2026");
  });

  it("produces the same output across repeated calls with the same input", () => {
    const results = Array.from({ length: 5 }, () =>
      formatUploadDate("2026-08-28T00:00:00.000Z")
    );
    expect(new Set(results).size).toBe(1);
    expect(results[0]).toBe("Aug 28, 2026");
  });

  it("never produces the day-first format that caused the original mismatch", () => {
    const result = formatUploadDate("2026-08-28T00:00:00.000Z");
    expect(result).not.toBe("28 Aug 2026");
    expect(result).toBe("Aug 28, 2026");
  });

  it("formats dates across different months/years correctly and consistently", () => {
    expect(formatUploadDate("2025-12-01T00:00:00.000Z")).toBe("Dec 1, 2025");
    expect(formatUploadDate("2026-03-09T00:00:00.000Z")).toBe("Mar 9, 2026");
  });
});
