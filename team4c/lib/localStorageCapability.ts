import { SignJWT, jwtVerify } from "jose";

/**
 * MVP M6 local-storage retrieval correction (Team 4C only).
 *
 * PROBLEM: Team 4A's Phase 2C-R secure remote-source resolver fetches
 * `file_url` server-to-server, using ONLY the URL itself (confirmed by
 * inspection -- it never attaches a browser cookie, and this project's
 * own architecture explicitly does not add an Authorization header to
 * that outbound request, since the frozen canonical contract supplies
 * only `file_url`). The local development storage mock's GET route
 * (app/api/local-storage/[...path]/route.ts) required a browser Auth.js
 * session -- which Team 4A, a separate server process, never has. This
 * made local-stack ingestion of an uploaded PDF/video fail with 401
 * before Team 4A's resolver could ever read the bytes.
 *
 * FIX: a short-lived, narrowly-scoped CAPABILITY TOKEN embedded directly
 * in the URL's own query string -- the local development equivalent of
 * a presigned object-storage URL (Requirement 8). The token is
 * cryptographically bound to the EXACT `workspaceId`/`publicId` pair it
 * was minted for (Requirement 13) -- it cannot be reused for any other
 * file or workspace, and expires quickly (Requirement 11: not a broad,
 * standing bypass of authentication).
 *
 * WHY jose/HS256, not the existing ES256 service-JWT primitive
 * (lib/serviceJwt.ts): that module signs tokens 4C sends TO Team 4A/4B,
 * verified by THEIR OWN public-key verifiers, for a completely
 * different purpose (authenticating the /v1/ingest and /api/v1/query
 * REQUESTS themselves) -- reusing it here would conflate two unrelated
 * trust boundaries and audiences. This module signs AND verifies within
 * Team 4C's own single trust boundary (mint on upload, verify on GET),
 * so a symmetric secret is both correct and simpler than an asymmetric
 * keypair (Requirement 16: reuses the SAME `jose` library already a
 * project dependency, and reuses `AUTH_SECRET` -- Auth.js's own
 * server-only signing secret, already present, so no new required
 * secret/env var is introduced -- rather than inventing an unrelated
 * primitive from scratch). The distinct `aud`/`iss` values below
 * prevent this token from ever being confused with, or accepted by, any
 * other JWT-consuming code path in this project.
 *
 * SCOPE: this mechanism exists ONLY on the local development storage
 * mock's own read path. It has no effect whatsoever once a real
 * `STORAGE_PROVIDER` is configured (Requirement 15) -- a real provider
 * returns its own, already-presigned or already-public HTTPS URL, and
 * never reaches this module.
 */

const CAPABILITY_AUDIENCE = "local-storage-capability";
const CAPABILITY_ISSUER = "edu-copilot-team-c-local-storage";
const CAPABILITY_TTL_SECONDS = 600; // 10 minutes -- generous enough for a real Phase 1 ingestion run to complete, short-lived enough to never function as a standing bypass.

function getSigningSecret(): Uint8Array {
  const secret = process.env.AUTH_SECRET;
  if (!secret) {
    throw new Error(
      "AUTH_SECRET must be set to mint/verify local-storage capability tokens (local development mock only)."
    );
  }
  return new TextEncoder().encode(secret);
}

/**
 * Mints a capability token scoped to exactly one `(workspaceId, publicId)`
 * pair -- the only two facts this token asserts, and the only two facts
 * the verifier below checks the caller's REQUESTED resource against.
 */
export async function mintLocalStorageCapabilityToken(workspaceId: string, publicId: string): Promise<string> {
  return new SignJWT({ workspaceId, publicId })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setIssuer(CAPABILITY_ISSUER)
    .setAudience(CAPABILITY_AUDIENCE)
    .setExpirationTime(`${CAPABILITY_TTL_SECONDS}s`)
    .sign(getSigningSecret());
}

export interface LocalStorageCapabilityClaims {
  workspaceId: string;
  publicId: string;
}

/**
 * Verifies a capability token AND that it authorizes exactly the
 * `(workspaceId, publicId)` pair being requested -- a validly-signed,
 * unexpired token minted for a DIFFERENT file/workspace is rejected
 * just as firmly as an invalid signature (Requirement 19's negative
 * case). Returns `null` for any failure (expired, wrong signature,
 * wrong audience/issuer, wrong resource) -- never throws, so callers
 * can uniformly fall back to the existing browser-session path.
 */
export async function verifyLocalStorageCapabilityToken(
  token: string,
  expected: LocalStorageCapabilityClaims
): Promise<boolean> {
  try {
    const { payload } = await jwtVerify(token, getSigningSecret(), {
      issuer: CAPABILITY_ISSUER,
      audience: CAPABILITY_AUDIENCE,
    });
    return payload.workspaceId === expected.workspaceId && payload.publicId === expected.publicId;
  } catch {
    return false;
  }
}
