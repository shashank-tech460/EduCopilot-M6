import { SignJWT, importPKCS8 } from "jose";
import { randomUUID } from "crypto";

/**
 * Phase 2B -- internal service JWT minting foundation (Team 4C).
 *
 * Mints short-lived, ES256-signed internal service JWTs for 4C's own
 * trusted, server-side hand-off calls to Team 4A (ingestion) and Team 4B
 * (query). This is server-only code (imports Node's `crypto`, uses a
 * private key) -- it must NEVER be imported from any client component,
 * and the resulting token must NEVER be sent to, or read by, the
 * browser. `services/teamA/client.ts`/`services/teamB/client.ts` (the
 * actual outbound HTTP calls) are the only intended callers, and even
 * they do not yet call this module -- per this task's own scope, this is
 * a standalone, independently-testable minting foundation, not wired
 * into the real clients' request flow yet (that wiring is the
 * cross-service round-trip work Phase 2B explicitly defers).
 *
 * `next-auth`'s Auth.js browser-facing authentication (lib/auth.ts) is
 * completely separate from, and unaffected by, this module -- Auth.js
 * answers "which human is using the browser"; this module answers "is
 * this server-to-server call from the real 4C backend, authorized for
 * this one narrow purpose". Neither replaces the other.
 *
 * 4C holds the ONLY private signing key in this whole system -- 4A/4B
 * hold exclusively the corresponding PUBLIC verification key(s) (see
 * their own `app/security/service_jwt.py`). This module has no
 * "verify" function at all -- signing and verification are
 * deliberately kept in separate services' codebases, matching the
 * asymmetric-key architecture itself.
 */

export type ServiceJwtAudience = "team4a-ingestion" | "team4b-query";
export type ServiceJwtScope = "ingest" | "query";

export interface ServiceJwtClaims {
  sub: string;
  workspace_id: string;
  scope: ServiceJwtScope;
  aud: ServiceJwtAudience;
}

export interface ServiceJwtSigningConfig {
  /** PKCS8 PEM-encoded ES256 (P-256) private key. NEVER logged, NEVER
   * sent to the browser, NEVER present in any file 4A/4B receive. */
  privateKeyPkcs8Pem: string;
  /** The `kid` identifying which key this is, for 4A/4B's key-rotation
   * lookup. Must correspond to a public key 4A/4B already have
   * configured before a token minted with it can ever verify. */
  kid: string;
  /** The fixed internal issuer identifier every 4A/4B verifier expects. */
  issuer: string;
  /** Token lifetime, in seconds -- configuration, not a hard-coded
   * constant scattered through the codebase. Rev.4.4's own ingestion
   * example uses ~5 minutes; that is this module's default (see
   * `DEFAULT_SERVICE_JWT_TTL_SECONDS`), not a value baked into the
   * signing function itself. */
  ttlSeconds?: number;
}

/** Rev.4.4's own documented default -- "approximately 5 minutes" --
 * used whenever a caller doesn't override `ttlSeconds` explicitly. */
export const DEFAULT_SERVICE_JWT_TTL_SECONDS = 5 * 60;

export class ServiceJwtSigningConfigError extends Error {}

/**
 * Reads the signing configuration from environment variables.
 *
 * Fails closed (throws `ServiceJwtSigningConfigError`) if the private
 * key, kid, or issuer are missing -- never falls back to an unsigned or
 * weakly-signed token, and never silently proceeds with a
 * partially-configured signer.
 */
export function loadServiceJwtSigningConfigFromEnv(): ServiceJwtSigningConfig {
  const privateKeyPkcs8Pem = process.env.SERVICE_JWT_PRIVATE_KEY;
  const kid = process.env.SERVICE_JWT_KID;
  const issuer = process.env.SERVICE_JWT_ISSUER;
  const ttlSecondsRaw = process.env.SERVICE_JWT_TTL_SECONDS;

  const missing: string[] = [];
  if (!privateKeyPkcs8Pem) missing.push("SERVICE_JWT_PRIVATE_KEY");
  if (!kid) missing.push("SERVICE_JWT_KID");
  if (!issuer) missing.push("SERVICE_JWT_ISSUER");

  if (missing.length > 0) {
    throw new ServiceJwtSigningConfigError(
      `Missing required internal service JWT signing configuration: ${missing.join(", ")}. ` +
        "Refusing to construct a signer with partial configuration."
    );
  }

  const ttlSeconds = ttlSecondsRaw ? Number(ttlSecondsRaw) : undefined;
  if (ttlSecondsRaw && (!Number.isFinite(ttlSeconds) || (ttlSeconds as number) <= 0)) {
    throw new ServiceJwtSigningConfigError(
      `SERVICE_JWT_TTL_SECONDS must be a positive number if set; got ${JSON.stringify(ttlSecondsRaw)}`
    );
  }

  return { privateKeyPkcs8Pem: privateKeyPkcs8Pem!, kid: kid!, issuer: issuer!, ttlSeconds };
}

/**
 * Mints one short-lived, ES256-signed internal service JWT.
 *
 * Sets exactly the nine Rev.4.4-required claims (`sub`, `workspace_id`,
 * `scope`, `iss`, `aud`, `iat`, `exp`, `jti`, plus `kid` in the header) --
 * no additional claims, and no client-suppliable field ever becomes
 * `workspace_id` here: callers must pass an already-authoritative,
 * server-derived `workspace_id` (e.g. the one `assertOwnership()` has
 * already verified), never a raw value taken directly from a browser
 * request body.
 */
export async function mintServiceJwt(config: ServiceJwtSigningConfig, claims: ServiceJwtClaims): Promise<string> {
  const privateKey = await importPKCS8(config.privateKeyPkcs8Pem, "ES256");
  const ttlSeconds = config.ttlSeconds ?? DEFAULT_SERVICE_JWT_TTL_SECONDS;

  return new SignJWT({
    workspace_id: claims.workspace_id,
    scope: claims.scope,
  })
    .setProtectedHeader({ alg: "ES256", kid: config.kid })
    .setSubject(claims.sub)
    .setIssuer(config.issuer)
    .setAudience(claims.aud)
    .setIssuedAt()
    .setExpirationTime(`${ttlSeconds}s`)
    .setJti(randomUUID())
    .sign(privateKey);
}
