"""Phase 2B interoperability verification -- Team 4A.

Proves the REAL cross-language cryptographic boundary: a REAL 4C
`mintServiceJwt` (jose, TypeScript) output, fed into the REAL 4A
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

# This path is specific to the sandboxed environment these two
# repositories happen to be co-located in for this verification task --
# in a real multi-repo deployment, these artifacts would be produced by
# a dedicated interop CI job with an explicit, documented path
# convention, not a relative filesystem assumption. Flagged here, not
# hidden, exactly per this project's own established convention for
# calling out environment-specific test scaffolding.
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


def test_real_4c_jose_ingest_token_is_accepted_by_the_real_4a_verifier(real_4c_artifacts):
    verifier = ServiceJWTVerifier(
        public_keys_by_kid={real_4c_artifacts["kid"]: real_4c_artifacts["publicKeySpkiPem"]},
        expected_issuer=real_4c_artifacts["issuer"],
        expected_audience="team4a-ingestion",
        required_scope="ingest",
    )

    identity = verifier.verify(real_4c_artifacts["ingestToken"])

    assert identity.sub == "user-interop-1"
    assert identity.workspace_id == "ws-interop-1"
    assert identity.scope == "ingest"
    assert identity.issuer == real_4c_artifacts["issuer"]
    assert identity.audience == "team4a-ingestion"
    assert identity.kid == real_4c_artifacts["kid"]
    assert isinstance(identity.issued_at, int)
    assert isinstance(identity.expires_at, int)
    assert isinstance(identity.jti, str) and len(identity.jti) > 0


def test_a_real_4c_token_minted_for_4b_is_rejected_by_4a(real_4c_artifacts):
    verifier = ServiceJWTVerifier(
        public_keys_by_kid={real_4c_artifacts["kid"]: real_4c_artifacts["publicKeySpkiPem"]},
        expected_issuer=real_4c_artifacts["issuer"],
        expected_audience="team4a-ingestion",
        required_scope="ingest",
    )
    with pytest.raises(ServiceTokenError):
        verifier.verify(real_4c_artifacts["queryToken"])


def test_a_tampered_real_4c_token_is_rejected(real_4c_artifacts):
    verifier = ServiceJWTVerifier(
        public_keys_by_kid={real_4c_artifacts["kid"]: real_4c_artifacts["publicKeySpkiPem"]},
        expected_issuer=real_4c_artifacts["issuer"],
        expected_audience="team4a-ingestion",
        required_scope="ingest",
    )
    with pytest.raises(ServiceTokenError):
        verifier.verify(real_4c_artifacts["modifiedIngestToken"])


def test_a_real_expired_4c_token_is_rejected(real_4c_artifacts):
    verifier = ServiceJWTVerifier(
        public_keys_by_kid={real_4c_artifacts["kid"]: real_4c_artifacts["publicKeySpkiPem"]},
        expected_issuer=real_4c_artifacts["issuer"],
        expected_audience="team4a-ingestion",
        required_scope="ingest",
    )
    with pytest.raises(ServiceTokenError):
        verifier.verify(real_4c_artifacts["expiredIngestToken"])


def test_a_real_4c_token_with_an_unrecognized_kid_is_rejected(real_4c_artifacts):
    verifier = ServiceJWTVerifier(
        public_keys_by_kid={real_4c_artifacts["kid"]: real_4c_artifacts["publicKeySpkiPem"]},
        expected_issuer=real_4c_artifacts["issuer"],
        expected_audience="team4a-ingestion",
        required_scope="ingest",
    )
    with pytest.raises(ServiceTokenError):
        verifier.verify(real_4c_artifacts["unknownKidIngestToken"])
