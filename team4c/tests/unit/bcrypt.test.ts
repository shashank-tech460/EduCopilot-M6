import { describe, expect, it } from "vitest";
import bcrypt from "bcrypt";

/**
 * These exercise bcrypt directly (no DB, no API route) — verifying the
 * primitive Phase 4 relies on before testing anything built on top of it.
 */
describe("bcrypt password hashing", () => {
  it("produces a hash that is not the plaintext password", async () => {
    const hash = await bcrypt.hash("correct horse battery staple", 10);
    expect(hash).not.toBe("correct horse battery staple");
    expect(hash.startsWith("$2")).toBe(true);
  });

  it("produces a different hash each time (unique salt)", async () => {
    const hashA = await bcrypt.hash("same-password", 10);
    const hashB = await bcrypt.hash("same-password", 10);
    expect(hashA).not.toBe(hashB);
  });

  it("compares correctly against its own hash", async () => {
    const hash = await bcrypt.hash("my-password", 10);
    expect(await bcrypt.compare("my-password", hash)).toBe(true);
  });

  it("rejects an incorrect password against a real hash", async () => {
    const hash = await bcrypt.hash("my-password", 10);
    expect(await bcrypt.compare("wrong-password", hash)).toBe(false);
  });
});
