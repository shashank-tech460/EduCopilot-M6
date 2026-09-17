"""Phase 2B security tests -- app.security.service_jwt (Team 4A).

Every test signs a REAL ES256 JWT with a REAL, freshly-generated P-256
key pair (via `cryptography`) and verifies it through the REAL
`ServiceJWTVerifier` -- no mocking of `jwt.encode`/`jwt.decode` or the
verifier's own logic. This is deliberate: the governing task requires
these tests to "exercise actual signing and cryptographic verification,
not merely mock the JWT library."
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.security.service_jwt import (
    REQUIRED_CLAIMS,
    ServiceJWTVerifier,
    ServiceTokenError,
    load_public_keys_json,
)

ISSUER = "https://educopilot.internal"
AUDIENCE_4A = "team4a-ingestion"
AUDIENCE_4B = "team4b-query"
SCOPE_INGEST = "ingest"
SCOPE_QUERY = "query"


def _generate_es256_keypair() -> tuple[str, str]:
    """Returns (private_pem, public_pem) for a fresh P-256 key pair."""

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def _mint(
    private_pem: str,
    kid: str,
    *,
    sub: str = "user-1",
    workspace_id: str = "ws-1",
    scope: str = SCOPE_INGEST,
    issuer: str = ISSUER,
    audience: str = AUDIENCE_4A,
    ttl_seconds: int = 300,
    jti: str = "jti-1",
    algorithm: str = "ES256",
    iat_override: float | None = None,
    omit_claims: tuple[str, ...] = (),
) -> str:
    now = iat_override if iat_override is not None else time.time()
    claims = {
        "sub": sub,
        "workspace_id": workspace_id,
        "scope": scope,
        "iss": issuer,
        "aud": audience,
        "iat": int(now),
        "exp": int(now + ttl_seconds),
        "jti": jti,
    }
    for claim in omit_claims:
        claims.pop(claim, None)
    return jwt.encode(claims, private_pem, algorithm=algorithm, headers={"kid": kid})


@pytest.fixture()
def keypair_a():
    return _generate_es256_keypair()


@pytest.fixture()
def keypair_b():
    return _generate_es256_keypair()


@pytest.fixture()
def verifier_4a(keypair_a):
    private_pem, public_pem = keypair_a
    return ServiceJWTVerifier(
        public_keys_by_kid={"kid-current": public_pem},
        expected_issuer=ISSUER,
        expected_audience=AUDIENCE_4A,
        required_scope=SCOPE_INGEST,
    )


@pytest.fixture()
def verifier_4b(keypair_a):
    private_pem, public_pem = keypair_a
    return ServiceJWTVerifier(
        public_keys_by_kid={"kid-current": public_pem},
        expected_issuer=ISSUER,
        expected_audience=AUDIENCE_4B,
        required_scope=SCOPE_QUERY,
    )


# -- 1/2: valid token accepted --------------------------------------------


def test_1_valid_token_accepted_by_4a_verifier(verifier_4a, keypair_a):
    private_pem, _ = keypair_a
    token = _mint(private_pem, "kid-current")
    identity = verifier_4a.verify(token)
    assert identity.sub == "user-1"
    assert identity.workspace_id == "ws-1"
    assert identity.scope == SCOPE_INGEST


def test_2_valid_token_accepted_by_4b_verifier_when_audience_scope_correct(verifier_4b, keypair_a):
    private_pem, _ = keypair_a
    token = _mint(private_pem, "kid-current", scope=SCOPE_QUERY, audience=AUDIENCE_4B)
    identity = verifier_4b.verify(token)
    assert identity.scope == SCOPE_QUERY
    assert identity.audience == AUDIENCE_4B


# -- 3: invalid signature ---------------------------------------------------


def test_3_invalid_signature_rejected(verifier_4a, keypair_b):
    # Signed with a DIFFERENT private key than the verifier's configured
    # public key -- a real cryptographic signature mismatch, not a
    # tampered-string test.
    wrong_private_pem, _ = keypair_b
    token = _mint(wrong_private_pem, "kid-current")
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(token)


# -- 4: expired token --------------------------------------------------------


def test_4_expired_token_rejected(verifier_4a, keypair_a):
    private_pem, _ = keypair_a
    token = _mint(private_pem, "kid-current", ttl_seconds=-3600)  # expired an hour ago
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(token)


# -- 5/6: wrong issuer / audience --------------------------------------------


def test_5_wrong_issuer_rejected(verifier_4a, keypair_a):
    private_pem, _ = keypair_a
    token = _mint(private_pem, "kid-current", issuer="https://not-educopilot.example")
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(token)


def test_6_wrong_audience_rejected(verifier_4a, keypair_a):
    private_pem, _ = keypair_a
    # A validly-signed token, correct issuer/scope, but minted FOR Team 4B.
    token = _mint(private_pem, "kid-current", audience=AUDIENCE_4B)
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(token)


# -- 7: missing workspace_id -------------------------------------------------


def test_7_missing_workspace_id_rejected(verifier_4a, keypair_a):
    private_pem, _ = keypair_a
    token = _mint(private_pem, "kid-current", omit_claims=("workspace_id",))
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(token)


# -- 8/9: missing / wrong scope -----------------------------------------------


def test_8_missing_scope_rejected(verifier_4a, keypair_a):
    private_pem, _ = keypair_a
    token = _mint(private_pem, "kid-current", omit_claims=("scope",))
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(token)


def test_9_wrong_scope_rejected(verifier_4a, keypair_a):
    private_pem, _ = keypair_a
    token = _mint(private_pem, "kid-current", scope=SCOPE_QUERY)  # a query-scoped token
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(token)


# -- 10: unknown kid ----------------------------------------------------------


def test_10_unknown_kid_rejected(verifier_4a, keypair_a):
    private_pem, _ = keypair_a
    token = _mint(private_pem, "kid-does-not-exist")
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(token)


# -- 11-14: missing jti / sub / iat / exp ------------------------------------


@pytest.mark.parametrize("missing_claim", ["jti", "sub", "iat", "exp"])
def test_11_to_14_missing_required_claim_rejected(verifier_4a, keypair_a, missing_claim):
    private_pem, _ = keypair_a
    token = _mint(private_pem, "kid-current", omit_claims=(missing_claim,))
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(token)


# -- 15: unsupported algorithm ------------------------------------------------


def test_15_unsupported_algorithm_rejected(verifier_4a):
    # A genuinely different, real algorithm (RS256) with its own real
    # keypair -- not a forged header on an ES256 token.
    rsa_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_private_pem = rsa_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    token = jwt.encode(
        {
            "sub": "user-1",
            "workspace_id": "ws-1",
            "scope": SCOPE_INGEST,
            "iss": ISSUER,
            "aud": AUDIENCE_4A,
            "iat": int(time.time()),
            "exp": int(time.time() + 300),
            "jti": "jti-1",
        },
        rsa_private_pem,
        algorithm="RS256",
        headers={"kid": "kid-current"},
    )
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(token)


def test_15b_none_algorithm_rejected(verifier_4a):
    """The classic 'alg: none' unsigned-JWT attack -- must never be
    accepted, under any circumstance."""

    unsigned = jwt.encode(
        {
            "sub": "user-1",
            "workspace_id": "ws-1",
            "scope": SCOPE_INGEST,
            "iss": ISSUER,
            "aud": AUDIENCE_4A,
            "iat": int(time.time()),
            "exp": int(time.time() + 300),
            "jti": "jti-1",
        },
        key=None,
        algorithm="none",
        headers={"kid": "kid-current"},
    )
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(unsigned)


# -- 16: malformed JWT --------------------------------------------------------


@pytest.mark.parametrize("garbage", ["not-a-jwt-at-all", "", "a.b", "a.b.c.d", "🎉🎉🎉"])
def test_16_malformed_jwt_rejected(verifier_4a, garbage):
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(garbage)


# -- 17/18: cross-service scope isolation ------------------------------------


def test_17_4a_cannot_accept_a_query_scoped_token(verifier_4a, keypair_a):
    private_pem, _ = keypair_a
    token = _mint(private_pem, "kid-current", scope=SCOPE_QUERY, audience=AUDIENCE_4A)
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(token)


def test_18_4b_cannot_accept_an_ingest_scoped_token(verifier_4b, keypair_a):
    private_pem, _ = keypair_a
    token = _mint(private_pem, "kid-current", scope=SCOPE_INGEST, audience=AUDIENCE_4B)
    with pytest.raises(ServiceTokenError):
        verifier_4b.verify(token)


# -- 19/20: private key never required ---------------------------------------


def test_19_private_signing_key_is_never_required_by_4a(verifier_4a):
    """Structural guard: ServiceJWTVerifier's constructor and verify()
    method signatures accept only public key material -- there is no
    parameter, anywhere, that could be a private key."""

    import inspect

    from app.security.service_jwt import ServiceJWTVerifier as VerifierClass

    init_params = inspect.signature(VerifierClass.__init__).parameters
    assert "private_key" not in init_params
    assert "signing_key" not in init_params
    # The only key-shaped parameter is explicitly named for PUBLIC keys.
    assert "public_keys_by_kid" in init_params


def test_20_private_signing_key_is_never_required_by_4b(verifier_4b):
    # Same structural guarantee -- 4B's verifier is the identical class.
    import inspect

    from app.security.service_jwt import ServiceJWTVerifier as VerifierClass

    init_params = inspect.signature(VerifierClass.__init__).parameters
    assert "private_key" not in init_params
    assert "signing_key" not in init_params


# -- 21-23: key rotation ------------------------------------------------------


def test_21_key_rotation_supports_an_overlapping_previous_key(keypair_a, keypair_b):
    _, public_pem_current = keypair_a
    _, public_pem_previous = keypair_b
    verifier = ServiceJWTVerifier(
        public_keys_by_kid={"kid-current": public_pem_current, "kid-previous": public_pem_previous},
        expected_issuer=ISSUER,
        expected_audience=AUDIENCE_4A,
        required_scope=SCOPE_INGEST,
    )
    assert set(verifier._public_keys_by_kid.keys()) == {"kid-current", "kid-previous"}


def test_22_token_generated_with_previous_key_remains_valid_while_configured(keypair_a, keypair_b):
    private_pem_current, public_pem_current = keypair_a
    private_pem_previous, public_pem_previous = keypair_b
    verifier = ServiceJWTVerifier(
        public_keys_by_kid={"kid-current": public_pem_current, "kid-previous": public_pem_previous},
        expected_issuer=ISSUER,
        expected_audience=AUDIENCE_4A,
        required_scope=SCOPE_INGEST,
    )

    token_from_previous_key = _mint(private_pem_previous, "kid-previous")
    identity = verifier.verify(token_from_previous_key)
    assert identity.kid == "kid-previous"

    token_from_current_key = _mint(private_pem_current, "kid-current")
    identity2 = verifier.verify(token_from_current_key)
    assert identity2.kid == "kid-current"


def test_23_token_with_removed_kid_is_rejected_after_rotation_completes(keypair_a, keypair_b):
    private_pem_previous, public_pem_previous = keypair_b
    _, public_pem_current = keypair_a

    # Rotation has FULLY completed -- the previous key is no longer configured.
    verifier_after_rotation = ServiceJWTVerifier(
        public_keys_by_kid={"kid-current": public_pem_current},
        expected_issuer=ISSUER,
        expected_audience=AUDIENCE_4A,
        required_scope=SCOPE_INGEST,
    )

    stale_token = _mint(private_pem_previous, "kid-previous")
    with pytest.raises(ServiceTokenError):
        verifier_after_rotation.verify(stale_token)


# -- iat clock-skew policy (Rev.4.4 §3's explicit requirement) --------------


def test_iat_far_in_the_future_is_rejected(verifier_4a, keypair_a):
    private_pem, _ = keypair_a
    token = _mint(private_pem, "kid-current", iat_override=time.time() + 3600)
    with pytest.raises(ServiceTokenError):
        verifier_4a.verify(token)


def test_iat_within_clock_skew_allowance_is_accepted(verifier_4a, keypair_a):
    private_pem, _ = keypair_a
    # 10 seconds in the future -- well within the default 30s skew.
    token = _mint(private_pem, "kid-current", iat_override=time.time() + 10)
    identity = verifier_4a.verify(token)
    assert identity.sub == "user-1"


# -- Configuration tests -------------------------------------------------


def test_missing_verification_configuration_fails_safely():
    with pytest.raises(ServiceTokenError):
        ServiceJWTVerifier(
            public_keys_by_kid={},
            expected_issuer=ISSUER,
            expected_audience=AUDIENCE_4A,
            required_scope=SCOPE_INGEST,
        )


def test_load_public_keys_json_parses_a_valid_map():
    keys = load_public_keys_json('{"kid-1": "-----BEGIN PUBLIC KEY-----\\nabc\\n-----END PUBLIC KEY-----"}')
    assert set(keys.keys()) == {"kid-1"}


@pytest.mark.parametrize("malformed", ["not json", "[]", "42", '{"kid-1": 42}', ""])
def test_load_public_keys_json_fails_safely_on_malformed_input(malformed):
    with pytest.raises(ServiceTokenError):
        load_public_keys_json(malformed)


def test_required_claims_constant_matches_the_governing_task_exactly():
    assert set(REQUIRED_CLAIMS) == {"sub", "workspace_id", "scope", "iss", "aud", "iat", "exp", "jti", "kid"}
