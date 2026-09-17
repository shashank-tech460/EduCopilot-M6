// @vitest-environment node
//
// This file exercises real Node.js Web Crypto / `node:crypto` operations
// (ES256 key generation, PKCS8 import/export, signing) via `jose` and
// `lib/serviceJwt.ts` (explicitly server-only code). The project's global
// Vitest environment is `jsdom` (vitest.config.mts) -- appropriate for
// the many browser/React-facing tests elsewhere in this suite, but
// jsdom's Web Crypto shim is not a faithful enough implementation for
// jose's ES256 signing path (confirmed directly: the exact same signing
// code that fails under jsdom succeeds unmodified in plain Node). This
// per-file override switches ONLY this test file to Vitest's real `node`
// environment, matching what `lib/serviceJwt.ts` actually runs under in
// production (a Next.js server-side module) -- the global config is
// deliberately left untouched, since changing it wholesale would affect
// every other, unrelated jsdom-dependent test in this repository.
import { describe, expect, it, afterEach, beforeEach } from "vitest";
import { exportSPKI, generateKeyPair, jwtVerify } from "jose";

import {
  DEFAULT_SERVICE_JWT_TTL_SECONDS,
  ServiceJwtSigningConfigError,
  loadServiceJwtSigningConfigFromEnv,
  mintServiceJwt,
  type ServiceJwtSigningConfig,
} from "@/lib/serviceJwt";

/**
 * Every test signs a REAL ES256 JWT with a REAL, freshly-generated P-256
 * key pair (via `jose`'s own `generateKeyPair`) and verifies it with
 * `jose`'s own `jwtVerify` against the exported PUBLIC key -- a genuine
 * cryptographic round trip, not a mocked signing call.
 */

const ORIGINAL_ENV = { ...process.env };

async function generateTestKeyPair() {
  const { privateKey, publicKey } = await generateKeyPair("ES256", { extractable: true });
  const { exportPKCS8 } = await import("jose");
  const privateKeyPkcs8Pem = await exportPKCS8(privateKey);
  const publicKeySpkiPem = await exportSPKI(publicKey);
  return { privateKeyPkcs8Pem, publicKeySpkiPem };
}

describe("mintServiceJwt", () => {
  it("mints a token that a real ES256 verifier accepts, with exactly the required claims", async () => {
    const { privateKeyPkcs8Pem, publicKeySpkiPem } = await generateTestKeyPair();
    const config: ServiceJwtSigningConfig = {
      privateKeyPkcs8Pem,
      kid: "kid-test-1",
      issuer: "https://educopilot.internal",
    };

    const token = await mintServiceJwt(config, {
      sub: "user-123",
      workspace_id: "ws-456",
      scope: "ingest",
      aud: "team4a-ingestion",
    });

    const { importSPKI } = await import("jose");
    const publicKey = await importSPKI(publicKeySpkiPem, "ES256");
    const { payload, protectedHeader } = await jwtVerify(token, publicKey, {
      issuer: "https://educopilot.internal",
      audience: "team4a-ingestion",
    });

    expect(protectedHeader.alg).toBe("ES256");
    expect(protectedHeader.kid).toBe("kid-test-1");
    expect(payload.sub).toBe("user-123");
    expect(payload.workspace_id).toBe("ws-456");
    expect(payload.scope).toBe("ingest");
    expect(payload.iss).toBe("https://educopilot.internal");
    expect(payload.aud).toBe("team4a-ingestion");
    expect(typeof payload.iat).toBe("number");
    expect(typeof payload.exp).toBe("number");
    expect(typeof payload.jti).toBe("string");
    expect((payload.jti as string).length).toBeGreaterThan(0);
  });

  it("produces a different jti on every call, even with identical claims", async () => {
    const { privateKeyPkcs8Pem, publicKeySpkiPem } = await generateTestKeyPair();
    const config: ServiceJwtSigningConfig = {
      privateKeyPkcs8Pem,
      kid: "kid-test-1",
      issuer: "https://educopilot.internal",
    };
    const claims = { sub: "user-1", workspace_id: "ws-1", scope: "query" as const, aud: "team4b-query" as const };

    const tokenA = await mintServiceJwt(config, claims);
    const tokenB = await mintServiceJwt(config, claims);

    const { importSPKI } = await import("jose");
    const publicKey = await importSPKI(publicKeySpkiPem, "ES256");
    const resultA = await jwtVerify(tokenA, publicKey, { issuer: "https://educopilot.internal", audience: "team4b-query" });
    const resultB = await jwtVerify(tokenB, publicKey, { issuer: "https://educopilot.internal", audience: "team4b-query" });

    expect(resultA.payload.jti).not.toBe(resultB.payload.jti);
  });

  it("uses the Rev.4.4 default 5-minute lifetime when ttlSeconds is not overridden", async () => {
    const { privateKeyPkcs8Pem, publicKeySpkiPem } = await generateTestKeyPair();
    const config: ServiceJwtSigningConfig = {
      privateKeyPkcs8Pem,
      kid: "kid-test-1",
      issuer: "https://educopilot.internal",
    };

    const token = await mintServiceJwt(config, {
      sub: "user-1",
      workspace_id: "ws-1",
      scope: "ingest",
      aud: "team4a-ingestion",
    });

    const { importSPKI } = await import("jose");
    const publicKey = await importSPKI(publicKeySpkiPem, "ES256");
    const { payload } = await jwtVerify(token, publicKey, {
      issuer: "https://educopilot.internal",
      audience: "team4a-ingestion",
    });

    expect(DEFAULT_SERVICE_JWT_TTL_SECONDS).toBe(300);
    expect((payload.exp as number) - (payload.iat as number)).toBe(300);
  });

  it("honors an explicit ttlSeconds override", async () => {
    const { privateKeyPkcs8Pem, publicKeySpkiPem } = await generateTestKeyPair();
    const config: ServiceJwtSigningConfig = {
      privateKeyPkcs8Pem,
      kid: "kid-test-1",
      issuer: "https://educopilot.internal",
      ttlSeconds: 60,
    };

    const token = await mintServiceJwt(config, {
      sub: "user-1",
      workspace_id: "ws-1",
      scope: "query",
      aud: "team4b-query",
    });

    const { importSPKI } = await import("jose");
    const publicKey = await importSPKI(publicKeySpkiPem, "ES256");
    const { payload } = await jwtVerify(token, publicKey, {
      issuer: "https://educopilot.internal",
      audience: "team4b-query",
    });

    expect((payload.exp as number) - (payload.iat as number)).toBe(60);
  });

  it("a token signed with one key does NOT verify against a different key's public counterpart", async () => {
    const { privateKeyPkcs8Pem } = await generateTestKeyPair();
    const { publicKeySpkiPem: differentPublicKey } = await generateTestKeyPair();

    const config: ServiceJwtSigningConfig = {
      privateKeyPkcs8Pem,
      kid: "kid-test-1",
      issuer: "https://educopilot.internal",
    };
    const token = await mintServiceJwt(config, {
      sub: "user-1",
      workspace_id: "ws-1",
      scope: "ingest",
      aud: "team4a-ingestion",
    });

    const { importSPKI } = await import("jose");
    const wrongPublicKey = await importSPKI(differentPublicKey, "ES256");
    await expect(
      jwtVerify(token, wrongPublicKey, { issuer: "https://educopilot.internal", audience: "team4a-ingestion" })
    ).rejects.toThrow();
  });
});

describe("loadServiceJwtSigningConfigFromEnv", () => {
  beforeEach(() => {
    delete process.env.SERVICE_JWT_PRIVATE_KEY;
    delete process.env.SERVICE_JWT_KID;
    delete process.env.SERVICE_JWT_ISSUER;
    delete process.env.SERVICE_JWT_TTL_SECONDS;
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it("fails closed when the private key is missing", () => {
    process.env.SERVICE_JWT_KID = "kid-1";
    process.env.SERVICE_JWT_ISSUER = "https://educopilot.internal";
    expect(() => loadServiceJwtSigningConfigFromEnv()).toThrow(ServiceJwtSigningConfigError);
  });

  it("fails closed when kid is missing", () => {
    process.env.SERVICE_JWT_PRIVATE_KEY = "dummy";
    process.env.SERVICE_JWT_ISSUER = "https://educopilot.internal";
    expect(() => loadServiceJwtSigningConfigFromEnv()).toThrow(ServiceJwtSigningConfigError);
  });

  it("fails closed when issuer is missing", () => {
    process.env.SERVICE_JWT_PRIVATE_KEY = "dummy";
    process.env.SERVICE_JWT_KID = "kid-1";
    expect(() => loadServiceJwtSigningConfigFromEnv()).toThrow(ServiceJwtSigningConfigError);
  });

  it("fails closed on a non-numeric or non-positive TTL override", () => {
    process.env.SERVICE_JWT_PRIVATE_KEY = "dummy";
    process.env.SERVICE_JWT_KID = "kid-1";
    process.env.SERVICE_JWT_ISSUER = "https://educopilot.internal";
    process.env.SERVICE_JWT_TTL_SECONDS = "not-a-number";
    expect(() => loadServiceJwtSigningConfigFromEnv()).toThrow(ServiceJwtSigningConfigError);
  });

  it("succeeds when all required variables are present", () => {
    process.env.SERVICE_JWT_PRIVATE_KEY = "dummy-pem";
    process.env.SERVICE_JWT_KID = "kid-1";
    process.env.SERVICE_JWT_ISSUER = "https://educopilot.internal";
    const config = loadServiceJwtSigningConfigFromEnv();
    expect(config.kid).toBe("kid-1");
    expect(config.issuer).toBe("https://educopilot.internal");
  });
});
