"""Phase 2B interoperability verification -- Team 4B.

Proves the REAL cross-language cryptographic boundary: a REAL 4C
`mintServiceJwt` (jose, TypeScript) output, fed into the REAL 4B
`ServiceJWTVerifier` (PyJWT, Python). No mocking of either library, no
hand-built JWT strings.

Invokes 4C's `scripts/interop-generate-tokens.ts` via `npx tsx` as a
subprocess -- the actual, real 4C signing code, executed for real. Skips
(does not fail) if the 4C repository or `npx`/`tsx` are not reachable
from this environment, since this test genuinely depends on a second
repository being present alongside this one -- that is reported
explicitly via a skip reason, never silently treated as a pass.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.security.service_jwt import ServiceJWTVerifier, ServiceTokenError

# Sandboxed-environment-specific path, exactly as in Team 4A's mirrored
# interop test -- flagged, not hidden.
TEAM_4C_REPO = Path("/home/claude/audit/4c/edu-copilot-team-c")
INTEROP_SCRIPT = TEAM_4C_REPO / "scripts" / "interop-generate-tokens.ts"


def _generate_real_4c_tokens() -> dict:
    if not INTEROP_SCRIPT.exists() or shutil.which("npx") is None:
        pytest.skip("Team 4C repository / npx+tsx not available in this environment -- cannot run the real cross-language check.")

    result = subprocess.run(
        ["npx", "tsx", str(INTEROP_SCRIPT)],
        cwd=str(TEAM_4C_REPO),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        pytest.fail(f"Real 4C token-generation script failed: {result.stderr}")
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def real_4c_artifacts():
    return _generate_real_4c_tokens()


def test_real_4c_jose_query_token_is_accepted_by_the_real_4b_verifier(real_4c_artifacts):
    verifier = ServiceJWTVerifier(
        public_keys_by_kid={real_4c_artifacts["kid"]: real_4c_artifacts["publicKeySpkiPem"]},
        expected_issuer=real_4c_artifacts["issuer"],
        expected_audience="team4b-query",
        required_scope="query",
    )

    identity = verifier.verify(real_4c_artifacts["queryToken"])

    assert identity.sub == "user-interop-2"
    assert identity.workspace_id == "ws-interop-2"
    assert identity.scope == "query"
    assert identity.issuer == real_4c_artifacts["issuer"]
    assert identity.audience == "team4b-query"
    assert identity.kid == real_4c_artifacts["kid"]
    assert isinstance(identity.issued_at, int)
    assert isinstance(identity.expires_at, int)
    assert isinstance(identity.jti, str) and len(identity.jti) > 0


def test_a_real_4c_token_minted_for_4a_is_rejected_by_4b(real_4c_artifacts):
    verifier = ServiceJWTVerifier(
        public_keys_by_kid={real_4c_artifacts["kid"]: real_4c_artifacts["publicKeySpkiPem"]},
        expected_issuer=real_4c_artifacts["issuer"],
        expected_audience="team4b-query",
        required_scope="query",
    )
    with pytest.raises(ServiceTokenError):
        verifier.verify(real_4c_artifacts["ingestToken"])


def test_a_real_4c_token_with_an_unrecognized_kid_is_rejected_by_4b(real_4c_artifacts):
    verifier = ServiceJWTVerifier(
        public_keys_by_kid={real_4c_artifacts["kid"]: real_4c_artifacts["publicKeySpkiPem"]},
        expected_issuer=real_4c_artifacts["issuer"],
        expected_audience="team4b-query",
        required_scope="query",
    )
    with pytest.raises(ServiceTokenError):
        verifier.verify(real_4c_artifacts["unknownKidIngestToken"])
