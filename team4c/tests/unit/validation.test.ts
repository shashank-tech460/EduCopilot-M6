import { describe, expect, it } from "vitest";

import { validateSignupInput, MIN_PASSWORD_LENGTH } from "@/lib/validation";

describe("validateSignupInput", () => {
  it("accepts fully valid input", () => {
    const result = validateSignupInput({
      name: "Sample Student",
      email: "student@example.com",
      password: "correcthorse",
      confirmPassword: "correcthorse",
    });
    expect(result.valid).toBe(true);
    expect(result.errors).toEqual({});
  });

  it("requires a name", () => {
    const result = validateSignupInput({
      name: "",
      email: "student@example.com",
      password: "correcthorse",
      confirmPassword: "correcthorse",
    });
    expect(result.valid).toBe(false);
    expect(result.errors.name).toBeDefined();
  });

  it("rejects an invalid email format", () => {
    const result = validateSignupInput({
      name: "Sample Student",
      email: "not-an-email",
      password: "correcthorse",
      confirmPassword: "correcthorse",
    });
    expect(result.valid).toBe(false);
    expect(result.errors.email).toBeDefined();
  });

  it(`rejects a password shorter than ${MIN_PASSWORD_LENGTH} characters`, () => {
    const result = validateSignupInput({
      name: "Sample Student",
      email: "student@example.com",
      password: "short",
      confirmPassword: "short",
    });
    expect(result.valid).toBe(false);
    expect(result.errors.password).toBeDefined();
  });

  it("rejects mismatched password confirmation", () => {
    const result = validateSignupInput({
      name: "Sample Student",
      email: "student@example.com",
      password: "correcthorse",
      confirmPassword: "different-password",
    });
    expect(result.valid).toBe(false);
    expect(result.errors.confirmPassword).toBeDefined();
  });

  it("reports every invalid field at once, not just the first", () => {
    const result = validateSignupInput({ name: "", email: "bad", password: "x", confirmPassword: "" });
    expect(result.errors.name).toBeDefined();
    expect(result.errors.email).toBeDefined();
    expect(result.errors.password).toBeDefined();
    expect(result.errors.confirmPassword).toBeDefined();
  });
});
