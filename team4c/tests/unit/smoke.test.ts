import { describe, expect, it } from "vitest";

import { cn } from "@/lib/utils";

describe("Phase 2 smoke test — unit", () => {
  it("verifies the test runner and TypeScript path aliases work", () => {
    expect(1 + 1).toBe(2);
  });

  it("verifies the cn() utility (from lib/utils) merges class names", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
    expect(cn("text-sm", false && "hidden", "font-medium")).toBe(
      "text-sm font-medium"
    );
  });
});
