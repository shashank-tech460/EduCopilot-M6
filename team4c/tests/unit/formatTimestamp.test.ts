import { describe, expect, it } from "vitest";

import { formatTimestamp } from "@/lib/formatTimestamp";

describe("formatTimestamp", () => {
  it.each([
    [0, "0:00"],
    [65, "1:05"],
    [125, "2:05"],
    [3665, "1:01:05"],
    [59, "0:59"],
    [3600, "1:00:00"],
  ])("formats %i seconds as %s", (seconds, expected) => {
    expect(formatTimestamp(seconds)).toBe(expected);
  });

  it("clamps negative values to 0:00", () => {
    expect(formatTimestamp(-5)).toBe("0:00");
  });
});
