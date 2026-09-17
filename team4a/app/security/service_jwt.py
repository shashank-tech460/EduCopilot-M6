"""Phase 2B -- internal service JWT verification foundation (Team 4A).

Verifies short-lived, ES256-signed internal service JWTs minted by Team
4C's trusted server-side code. Team 4A holds ONLY public verification
key(s) -- there is no code path anywhere in this module, or anywhere else
in this repository, that reads or requires a private signing key.

Scope of this task (Rev.4.4 Phase 2B -- a "foundation", not full wiring):
this module is a standalone, independently-testable verification
abstraction. It is NOT wired into any FastAPI route/dependency in this
pass, and does not yet gate `/ingest/*`/`/jobs/*` behavior -- per the
governing task's own instruction not to change endpoint behavior beyond
what's strictly required to expose the verifier, and since a standalone
unit-level test suite (see tests/test_service_jwt.py) can and does fully
exercise this abstraction without any route wiring at all.

Fails closed, always: every failure mode below raises `ServiceTokenError`
-- there is no code path that returns a "probably fine" identity, and no
fallback that decodes a token without verifying its signature.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import jwt

#: The one and only algorithm this verifier accepts. Rev.4.4 mandates
#: ES256 specifically (asymmetric, elliptic-curve) -- never HS256/384/512
#: (symmetric -- would require sharing the signing secret with 4A, which
#: Rev.4.4 explicitly forbids), never RS256 (a different, larger-key
#: asymmetric scheme Rev.4.4 did not choose), and never "none"/unsigned.
SUPPORTED_ALGORITHM = "ES256"

#: Every claim Rev.4.4 requires be present on an internal service JWT.
#: Passed to PyJWT's own `options.require` so a token missing ANY one of
#: these fails verification before this module's own code ever inspects
#: the claim values -- "missing claim" and "invalid claim value" are
#: therefore two structurally distinct failure points, both fail-closed.
#:
#: NOTE: `kid` is a JWT HEADER field, not a payload claim (per the JWT
#: spec) -- PyJWT's `options.require` only inspects the payload, so `kid`
#: is deliberately excluded from `_PAYLOAD_REQUIRED_CLAIMS` below and is
#: instead checked directly from the parsed header, before `jwt.decode`
#: is ever called (see `verify()`). `REQUIRED_CLAIMS` itself still lists
#: `kid` because it genuinely is a claim the governing task requires be
#: present on the token as a whole -- this constant documents that
#: requirement; `_PAYLOAD_REQUIRED_CLAIMS` is the payload-only subset
#: PyJWT's API actually accepts.
REQUIRED_CLAIMS = ("sub", "workspace_id", "scope", "iss", "aud", "iat", "exp", "jti", "kid")
_PAYLOAD_REQUIRED_CLAIMS = tuple(claim for claim in REQUIRED_CLAIMS if claim != "kid")


class ServiceTokenError(RuntimeError):
    """Raised for EVERY internal-JWT verification failure, of any kind.

    A single exception type is deliberate: callers must treat every
    failure identically (reject the request) rather than being tempted to
    special-case "well THIS failure is probably fine". The specific
    reason is still in the exception message for logging (as safe,
    non-credential metadata only -- see the module docstring's logging
    guidance), but no caller should ever branch on it to partially trust
    a token.
    """


@dataclass(frozen=True)
class ServiceIdentity:
    """The verified, typed identity context produced by a successful
    `ServiceJWTVerifier.verify()` call -- never a raw claims dict.

    This is intentionally the ONLY way calling code can obtain trusted
    identity information from a token: there is no function in this
    module that returns claims without having fully verified the token
    they came from first.

    Per Rev.4.4 Phase 2B's explicit scope: this identity context is not
    yet wired into Qdrant filtering, ingestion, or query route behavior
    anywhere in this codebase -- it exists as the verified foundation
    those future, separately-audited tasks will consume.
    """

    sub: str
    workspace_id: str
    scope: str
    issuer: str
    audience: str
    issued_at: int
    expires_at: int
    jti: str
    kid: str


class ServiceJWTVerifier:
    """Verifies internal service JWTs against a fixed issuer, audience,
    required scope, and a set of known public keys (keyed by `kid`, to
    support overlapping key rotation -- see the module-level docstring
    and `tests/test_service_jwt.py`'s rotation tests).

    Holds ONLY public key material. Constructing one never requires, and
    this class has no method that could accept, a private signing key.
    """

    def __init__(
        self,
        public_keys_by_kid: dict[str, str],
        expected_issuer: str,
        expected_audience: str,
        required_scope: str,
        clock_skew_seconds: int = 30,
    ) -> None:
        if not public_keys_by_kid:
            # Fails closed at construction time, not on the first
            # verify() call -- a verifier with no keys configured at all
            # is a configuration error, not something that should let a
            # request through some default-allow path.
            raise ServiceTokenError("No verification public keys configured -- refusing to construct a verifier.")
        self._public_keys_by_kid = dict(public_keys_by_kid)
        self._expected_issuer = expected_issuer
        self._expected_audience = expected_audience
        self._required_scope = required_scope
        self._clock_skew_seconds = clock_skew_seconds

    def verify(self, token: str) -> ServiceIdentity:
        """Verify `token` and return its typed identity context.

        Raises `ServiceTokenError` for every failure mode named in the
        governing task (§8): invalid signature, malformed JWT, expired
        token, token used before its issued-at time allows (per this
        verifier's clock-skew policy), wrong issuer, wrong audience,
        missing required claim, invalid/wrong scope, missing
        workspace_id, invalid subject, unknown kid, unsupported
        algorithm. Never falls back to decoding without verifying the
        signature; never returns a partially-trusted result.
        """

        try:
            header = jwt.get_unverified_header(token)
        except Exception as exc:  # noqa: BLE001 -- any parse failure is "malformed JWT"
            raise ServiceTokenError("Malformed JWT: could not parse header") from exc

        algorithm = header.get("alg")
        if algorithm != SUPPORTED_ALGORITHM:
            raise ServiceTokenError(f"Unsupported algorithm: {algorithm!r} (only {SUPPORTED_ALGORITHM} is accepted)")

        kid = header.get("kid")
        if not kid or not isinstance(kid, str):
            raise ServiceTokenError("Malformed JWT: missing kid header")
        public_key = self._public_keys_by_kid.get(kid)
        if public_key is None:
            raise ServiceTokenError(f"Unknown kid: {kid!r} (not among currently-configured verification keys)")

        try:
            claims = jwt.decode(
                token,
                key=public_key,
                algorithms=[SUPPORTED_ALGORITHM],
                issuer=self._expected_issuer,
                audience=self._expected_audience,
                leeway=self._clock_skew_seconds,
                options={"require": list(_PAYLOAD_REQUIRED_CLAIMS)},
            )
        except jwt.PyJWTError as exc:
            # Covers: invalid signature, expired (exp), wrong iss, wrong
            # aud, missing required claim (any of REQUIRED_CLAIMS) -- all
            # of PyJWT's own, already-cryptographically-sound checks.
            raise ServiceTokenError(f"Token verification failed: {exc}") from exc

        # -- Claims PyJWT confirms are PRESENT (via `require`) but does not
        # itself semantically validate -- checked explicitly, below. --

        workspace_id = claims.get("workspace_id")
        if not isinstance(workspace_id, str) or not workspace_id:
            raise ServiceTokenError("Missing or invalid workspace_id")

        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise ServiceTokenError("Missing or invalid sub")

        jti = claims.get("jti")
        if not isinstance(jti, str) or not jti:
            raise ServiceTokenError("Missing or invalid jti")

        scope = claims.get("scope")
        if scope != self._required_scope:
            raise ServiceTokenError(f"Invalid scope: required {self._required_scope!r}, got {scope!r}")

        # -- Documented clock-skew policy for `iat` (Rev.4.4 §3): PyJWT's
        # own `leeway` already governs `exp` (and `nbf`, if present); it
        # does NOT reject a future-dated `iat` on its own. A token
        # claiming to have been issued more than `clock_skew_seconds` in
        # the future is rejected explicitly here -- the same leeway
        # value is reused for both directions (exp lateness, iat
        # earliness) rather than introducing a second, separately-tuned
        # constant for one policy concept. --
        issued_at = claims.get("iat")
        now = time.time()
        if isinstance(issued_at, (int, float)) and issued_at > now + self._clock_skew_seconds:
            raise ServiceTokenError("Token iat is in the future beyond the configured clock-skew allowance")

        return ServiceIdentity(
            sub=sub,
            workspace_id=workspace_id,
            scope=scope,
            issuer=claims["iss"],
            audience=self._expected_audience,
            issued_at=int(issued_at),
            expires_at=int(claims["exp"]),
            jti=jti,
            kid=kid,
        )


def load_public_keys_json(raw: str) -> dict[str, str]:
    """Parse the `{kid: PEM_public_key}` JSON map read from
    `Settings.service_jwt_public_keys_json` (or an equivalent
    environment-sourced string for Team 4B's own settings).

    The one and only place this project ever parses that configuration
    value -- fails closed (raises `ServiceTokenError`, not a bare
    exception a caller might not expect) on malformed JSON or a
    non-object shape, rather than silently constructing a verifier with
    zero usable keys.
    """

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ServiceTokenError("service_jwt_public_keys_json is not valid JSON") from exc

    if not isinstance(parsed, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()):
        raise ServiceTokenError("service_jwt_public_keys_json must be a JSON object of {kid: PEM string}")

    return parsed

