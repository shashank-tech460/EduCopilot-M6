/**
 * Phase 2B interoperability verification -- generates REAL artifacts
 * using the ACTUAL 4C `mintServiceJwt` implementation (lib/serviceJwt.ts),
 * for the actual Python (4A/4B) verifiers to consume in a separate
 * process. Not a test file itself -- a fixture generator, invoked by
 * `tests/unit/serviceJwt-interop.test.ts` and, for the cross-language
 * proof, directly via `npx tsx` from the interop shell script.
 *
 * Writes real JSON to stdout: {publicKeySpkiPem, ingestToken, queryToken,
 * modifiedIngestToken, expiredIngestToken, unknownKidIngestToken}.
 */
import { generateKeyPair, exportPKCS8, exportSPKI } from "jose";
import { mintServiceJwt, type ServiceJwtSigningConfig } from "../lib/serviceJwt";

async function main() {
  const { privateKey, publicKey } = await generateKeyPair("ES256", { extractable: true });
  const privateKeyPkcs8Pem = await exportPKCS8(privateKey);
  const publicKeySpkiPem = await exportSPKI(publicKey);

  const issuer = "https://educopilot.internal";
  const kid = "interop-kid-1";

  const configCurrentKid: ServiceJwtSigningConfig = { privateKeyPkcs8Pem, kid, issuer };

  // The real, actual 4C signing path -- REAL jose ES256 signing, real
  // claims, exactly as services/teamA/client.ts and
  // services/teamB/client.ts would eventually receive from this module.
  const ingestToken = await mintServiceJwt(configCurrentKid, {
    sub: "user-interop-1",
    workspace_id: "ws-interop-1",
    scope: "ingest",
    aud: "team4a-ingestion",
  });

  const queryToken = await mintServiceJwt(configCurrentKid, {
    sub: "user-interop-2",
    workspace_id: "ws-interop-2",
    scope: "query",
    aud: "team4b-query",
  });

  // A modified (tampered) token: real signature, then one character of
  // the signature segment flipped -- a genuine signature-mismatch case,
  // not a hand-built fake JWT.
  const [header, payload, signature] = ingestToken.split(".");
  const tamperedChar = signature[0] === "A" ? "B" : "A";
  const modifiedIngestToken = `${header}.${payload}.${tamperedChar}${signature.slice(1)}`;

  // A real, actually-expired token -- minted with a NEGATIVE relative
  // TTL (already in the past the instant it's signed), using the real
  // signing path, not a claim edited after the fact or a timing race.
  const expiredIngestToken = await mintServiceJwt(
    { ...configCurrentKid, ttlSeconds: -3600 },
    { sub: "user-interop-1", workspace_id: "ws-interop-1", scope: "ingest", aud: "team4a-ingestion" }
  );

  // A real token signed with a DIFFERENT key than the one 4A/4B will be
  // configured to trust -- proves "unknown kid" via a genuinely
  // unrecognized key, not a forged kid header on a token 4A could
  // otherwise verify.
  const { privateKey: otherPrivateKey } = await generateKeyPair("ES256", { extractable: true });
  const otherPrivateKeyPkcs8Pem = await exportPKCS8(otherPrivateKey);
  const unknownKidIngestToken = await mintServiceJwt(
    { privateKeyPkcs8Pem: otherPrivateKeyPkcs8Pem, kid: "interop-kid-UNKNOWN", issuer },
    { sub: "user-interop-1", workspace_id: "ws-interop-1", scope: "ingest", aud: "team4a-ingestion" }
  );

  process.stdout.write(
    JSON.stringify({
      publicKeySpkiPem,
      kid,
      issuer,
      ingestToken,
      queryToken,
      modifiedIngestToken,
      expiredIngestToken,
      unknownKidIngestToken,
    })
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
