"""Phase 2E -- the FastAPI authentication dependency for `POST
/api/v1/query`, wiring the existing, unmodified Phase 2B
`ServiceJWTVerifier` into the route boundary.

This module adds ONLY authentication -- it has no awareness of
retrieval, workspace filtering, or generation visibility, and does not
change what `RAGService`/`HybridRetriever`/`LLMGenerator` do in any way.
Per this phase's explicit scope, the verified identity produced here is
NOT yet used to filter retrieval results -- that is a separate, later,
audited task. This module exists purely so an unauthenticated caller can
no longer reach the query pipeline at all, mirroring exactly the pattern
already established and tested for Team 4A's canonical `/v1/ingest`
route (app/api/canonical_ingest.py in that repository) -- no new security
logic is introduced, only route-level wiring of the existing verifier.
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings
from app.security.service_jwt import (
    ServiceIdentity,
    ServiceJWTVerifier,
    ServiceTokenError,
    load_public_keys_json,
)

logger = logging.getLogger(__name__)

_BEARER_PREFIX = "Bearer "

#: A single, uniform, safe message for EVERY authentication failure mode
#: -- see app/api/canonical_ingest.py (Team 4A) for the identical
#: reasoning: distinguishing failure categories to the client would hand
#: an attacker a verification oracle.
_AUTH_FAILURE_DETAIL = "Invalid or missing authentication."


def get_service_jwt_verifier(settings: Settings = Depends(get_settings)) -> ServiceJWTVerifier:
    """Constructs the Phase 2B verifier from Settings -- audience
    `team4b-query`, scope `query` (Settings' own existing defaults).
    Overridable in tests via `app.dependency_overrides`.
    """

    public_keys = load_public_keys_json(settings.service_jwt_public_keys_json)
    return ServiceJWTVerifier(
        public_keys_by_kid=public_keys,
        expected_issuer=settings.service_jwt_expected_issuer,
        expected_audience=settings.service_jwt_expected_audience,
        required_scope=settings.service_jwt_required_scope,
        clock_skew_seconds=settings.service_jwt_clock_skew_seconds,
    )


def require_query_identity(
    request: Request,
    verifier: ServiceJWTVerifier = Depends(get_service_jwt_verifier),
) -> ServiceIdentity:
    """Verifies the internal service JWT on `POST /api/v1/query`.

    Fails closed for every failure mode. Two distinct HTTP statuses are
    produced, per this phase's explicit requirement (401 for
    authentication failure, 403 for authorization/scope failure):

    - 401: missing/malformed header, invalid signature, malformed JWT,
      expired, wrong issuer, wrong audience, missing a required claim,
      unknown kid, unsupported algorithm -- the token is not a valid,
      trustworthy credential at all.
    - 403: the token IS validly signed, issued, and otherwise well-formed,
      but carries the wrong `scope` (e.g. an `ingest`-scoped token minted
      for Team 4A) -- the caller is authenticated, just not authorized
      for this endpoint.

    `ServiceJWTVerifier.verify()` itself (Phase 2B, unmodified, not
    duplicated here) raises a single `ServiceTokenError` for every
    failure case, by design (avoiding a verification oracle at the
    cryptographic layer). The 401/403 split below is therefore made by
    inspecting the ALREADY-RAISED exception's own message for the one,
    specific, textually-stable "Invalid scope" case the verifier already
    produces -- this adds no new claim-checking, timing-checking, or
    signature logic of its own; it only recategorizes an existing
    verifier failure into the HTTP status this phase's routing contract
    requires. (Team 4A's Phase 2C route made the different, equally
    valid choice of mapping every case to 401 uniformly, since that
    phase did not require a 401/403 split -- this divergence is
    intentional and specific to this phase's own stated requirements,
    not an inconsistency.)
    """

    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith(_BEARER_PREFIX):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_FAILURE_DETAIL)

    token = auth_header[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_FAILURE_DETAIL)

    try:
        return verifier.verify(token)
    except ServiceTokenError as exc:
        if "Invalid scope" in str(exc):
            logger.warning(
                "Internal service JWT lacked the required scope for /api/v1/query",
                extra={"failure_category": "service_jwt_wrong_scope"},
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient scope.") from None
        logger.warning(
            "Internal service JWT verification failed for /api/v1/query",
            extra={"failure_category": "service_jwt_verification"},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_FAILURE_DETAIL) from None
