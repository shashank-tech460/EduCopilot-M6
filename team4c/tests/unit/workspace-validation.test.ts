import { describe, expect, it } from "vitest";

import { validateWorkspaceName, MAX_WORKSPACE_NAME_LENGTH } from "@/lib/validation";

describe("validateWorkspaceName", () => {
  it("accepts a valid name", () => {
    expect(validateWorkspaceName("DBMS").valid).toBe(true);
  });

  it("rejects an empty name", () => {
    const result = validateWorkspaceName("");
    expect(result.valid).toBe(false);
    expect(result.error).toBeDefined();
  });

  it("rejects a whitespace-only name", () => {
    const result = validateWorkspaceName("   ");
    expect(result.valid).toBe(false);
    expect(result.error).toBeDefined();
  });

  it("trims surrounding whitespace before validating length", () => {
    expect(validateWorkspaceName("  DBMS  ").valid).toBe(true);
  });

  it(`rejects a name longer than ${MAX_WORKSPACE_NAME_LENGTH} characters`, () => {
    const result = validateWorkspaceName("x".repeat(MAX_WORKSPACE_NAME_LENGTH + 1));
    expect(result.valid).toBe(false);
    expect(result.error).toBeDefined();
  });

  it(`accepts a name exactly ${MAX_WORKSPACE_NAME_LENGTH} characters long`, () => {
    expect(validateWorkspaceName("x".repeat(MAX_WORKSPACE_NAME_LENGTH)).valid).toBe(true);
  });

  it("rejects a non-string value", () => {
    const result = validateWorkspaceName(undefined);
    expect(result.valid).toBe(false);
  });
});
