"""Tests for scripts/fix_service_jwt_public_keys_json.py -- the MVP M6
environment-configuration fix. Every key used here is generated fresh,
purely for this test file -- never any real project key material.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fix_service_jwt_public_keys_json import fix_public_keys_json, _jwk_to_spki_pem  # noqa: E402


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_test_keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


def _public_key_to_jwk(public_key, kid: str) -> dict:
    numbers = public_key.public_numbers()
    x = numbers.x.to_bytes(32, "big")
    y = numbers.y.to_bytes(32, "big")
    return {"kty": "EC", "crv": "P-256", "x": _b64url(x), "y": _b64url(y), "alg": "ES256", "use": "sig", "kid": kid}


def _public_key_to_pem(public_key) -> str:
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")


class TestJwkToSpkiPemConversion:
    def test_converts_a_jwk_to_the_exact_same_underlying_key(self):
        _private_key, public_key = _generate_test_keypair()
        jwk = _public_key_to_jwk(public_key, "test-kid")

        pem = _jwk_to_spki_pem(jwk)
        recovered_key = serialization.load_pem_public_key(pem.encode("ascii"))

        assert recovered_key.public_numbers() == public_key.public_numbers()

    def test_rejects_a_non_ec_kty(self):
        with pytest.raises(ValueError, match="kty"):
            _jwk_to_spki_pem({"kty": "RSA", "crv": "P-256", "x": "x", "y": "y"})

    def test_rejects_a_non_p256_curve(self):
        with pytest.raises(ValueError, match="crv"):
            _jwk_to_spki_pem({"kty": "EC", "crv": "P-384", "x": "x", "y": "y"})

    def test_rejects_a_jwk_missing_coordinates(self):
        with pytest.raises(ValueError, match="x.*y|coordinate"):
            _jwk_to_spki_pem({"kty": "EC", "crv": "P-256"})


class TestFixPublicKeysJson:
    def test_converts_a_jwk_shaped_value_to_a_working_pem(self):
        _private_key, public_key = _generate_test_keypair()
        jwk = _public_key_to_jwk(public_key, "m6-es256-2026-01")
        broken = json.dumps({"m6-es256-2026-01": jwk})

        corrected = fix_public_keys_json(broken)
        parsed = json.loads(corrected)

        assert set(parsed.keys()) == {"m6-es256-2026-01"}
        assert isinstance(parsed["m6-es256-2026-01"], str)
        recovered_key = serialization.load_pem_public_key(parsed["m6-es256-2026-01"].encode("ascii"))
        assert recovered_key.public_numbers() == public_key.public_numbers()

    def test_preserves_the_exact_kid(self):
        _private_key, public_key = _generate_test_keypair()
        jwk = _public_key_to_jwk(public_key, "m6-es256-2026-01")
        broken = json.dumps({"m6-es256-2026-01": jwk})

        corrected = fix_public_keys_json(broken)

        assert list(json.loads(corrected).keys()) == ["m6-es256-2026-01"]

    def test_an_already_correct_pem_value_is_passed_through_unchanged(self):
        _private_key, public_key = _generate_test_keypair()
        pem = _public_key_to_pem(public_key)
        already_correct = json.dumps({"kid-1": pem})

        corrected = fix_public_keys_json(already_correct)

        assert json.loads(corrected) == {"kid-1": pem}

    def test_mixed_map_with_one_already_correct_and_one_broken_kid(self):
        _priv1, pub1 = _generate_test_keypair()
        _priv2, pub2 = _generate_test_keypair()
        pem1 = _public_key_to_pem(pub1)
        jwk2 = _public_key_to_jwk(pub2, "kid-2")
        mixed = json.dumps({"kid-1": pem1, "kid-2": jwk2})

        corrected = fix_public_keys_json(mixed)
        parsed = json.loads(corrected)

        assert parsed["kid-1"] == pem1
        recovered_key2 = serialization.load_pem_public_key(parsed["kid-2"].encode("ascii"))
        assert recovered_key2.public_numbers() == pub2.public_numbers()

    def test_output_is_accepted_by_the_real_load_public_keys_json(self):
        """End-to-end: the corrected output must satisfy the REAL,
        unmodified `load_public_keys_json` from app/security/service_jwt.py."""

        from app.security.service_jwt import load_public_keys_json

        _private_key, public_key = _generate_test_keypair()
        jwk = _public_key_to_jwk(public_key, "m6-es256-2026-01")
        broken = json.dumps({"m6-es256-2026-01": jwk})

        corrected = fix_public_keys_json(broken)
        loaded = load_public_keys_json(corrected)

        assert list(loaded.keys()) == ["m6-es256-2026-01"]
        assert isinstance(loaded["m6-es256-2026-01"], str)

    def test_rejects_non_object_top_level_value(self):
        with pytest.raises(ValueError, match="JSON object"):
            fix_public_keys_json(json.dumps(["not", "an", "object"]))

    def test_rejects_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            fix_public_keys_json("not json at all")

    def test_rejects_a_string_value_that_is_not_actually_a_valid_pem(self):
        with pytest.raises(ValueError, match="not a valid PEM"):
            fix_public_keys_json(json.dumps({"kid-1": "not a real pem"}))

    def test_never_generates_a_new_key_output_key_matches_input_key_exactly(self):
        """The single most important safety property: the OUTPUT key
        must be cryptographically identical to the INPUT key, every
        time -- proven across many fresh keypairs, not just one."""

        for _ in range(20):
            _private_key, public_key = _generate_test_keypair()
            jwk = _public_key_to_jwk(public_key, "k")
            corrected = fix_public_keys_json(json.dumps({"k": jwk}))
            recovered = serialization.load_pem_public_key(json.loads(corrected)["k"].encode("ascii"))
            assert recovered.public_numbers() == public_key.public_numbers()


class TestEnvFileHandling:
    """The .env-file-specific procedure this MVP M6 follow-up requires:
    extract exactly one variable's value from a real .env file, and (in
    --write mode) rewrite ONLY that one line, leaving every other
    variable/comment/blank line untouched."""

    def test_extracts_the_value_from_a_realistic_env_file(self):
        from fix_service_jwt_public_keys_json import _extract_env_var_line

        env_contents = (
            "MONGODB_URI=mongodb://localhost:27017/db\n"
            'SERVICE_JWT_PUBLIC_KEYS_JSON={"m6-es256-2026-01": {"kty": "EC"}}\n'
            "REDIS_URL=redis://localhost:6380\n"
        )

        line_index, value = _extract_env_var_line(env_contents, "SERVICE_JWT_PUBLIC_KEYS_JSON")

        assert line_index == 1
        assert value == '{"m6-es256-2026-01": {"kty": "EC"}}'

    def test_strips_a_single_layer_of_surrounding_double_quotes(self):
        from fix_service_jwt_public_keys_json import _extract_env_var_line

        env_contents = 'SERVICE_JWT_PUBLIC_KEYS_JSON="{\\"k\\": \\"v\\"}"\n'
        _line_index, value = _extract_env_var_line(env_contents, "SERVICE_JWT_PUBLIC_KEYS_JSON")

        assert value == '{\\"k\\": \\"v\\"}'

    def test_raises_if_variable_is_missing(self):
        from fix_service_jwt_public_keys_json import _extract_env_var_line

        with pytest.raises(ValueError, match="not found"):
            _extract_env_var_line("OTHER_VAR=1\n", "SERVICE_JWT_PUBLIC_KEYS_JSON")

    def test_raises_if_variable_is_defined_more_than_once(self):
        from fix_service_jwt_public_keys_json import _extract_env_var_line

        env_contents = "SERVICE_JWT_PUBLIC_KEYS_JSON={}\nSERVICE_JWT_PUBLIC_KEYS_JSON={}\n"
        with pytest.raises(ValueError, match="more than once"):
            _extract_env_var_line(env_contents, "SERVICE_JWT_PUBLIC_KEYS_JSON")

    def test_replace_env_var_line_touches_only_the_target_line(self):
        from fix_service_jwt_public_keys_json import _extract_env_var_line, _replace_env_var_line

        env_contents = (
            "# a comment\n"
            "MONGODB_URI=mongodb://localhost:27017/db\n"
            'SERVICE_JWT_PUBLIC_KEYS_JSON={"old": "value"}\n'
            "REDIS_URL=redis://localhost:6380\n"
            "\n"
        )
        line_index, _value = _extract_env_var_line(env_contents, "SERVICE_JWT_PUBLIC_KEYS_JSON")

        updated = _replace_env_var_line(env_contents, line_index, "SERVICE_JWT_PUBLIC_KEYS_JSON", '{"new": "value"}')

        expected = (
            "# a comment\n"
            "MONGODB_URI=mongodb://localhost:27017/db\n"
            'SERVICE_JWT_PUBLIC_KEYS_JSON="{"new": "value"}"\n'
            "REDIS_URL=redis://localhost:6380\n"
            "\n"
        )
        assert updated == expected

    def test_end_to_end_env_file_extraction_and_conversion(self, tmp_path):
        from fix_service_jwt_public_keys_json import _extract_env_var_line, fix_public_keys_json

        _private_key, public_key = _generate_test_keypair()
        jwk = _public_key_to_jwk(public_key, "m6-es256-2026-01")
        env_file = tmp_path / ".env"
        env_file.write_text(
            "MONGODB_URI=mongodb://localhost:27017/db\n"
            f"SERVICE_JWT_PUBLIC_KEYS_JSON={json.dumps({'m6-es256-2026-01': jwk})}\n"
        )

        _line_index, raw = _extract_env_var_line(env_file.read_text(), "SERVICE_JWT_PUBLIC_KEYS_JSON")
        corrected = fix_public_keys_json(raw)
        parsed = json.loads(corrected)

        assert list(parsed.keys()) == ["m6-es256-2026-01"]
        recovered = serialization.load_pem_public_key(parsed["m6-es256-2026-01"].encode("ascii"))
        assert recovered.public_numbers() == public_key.public_numbers()

    def test_write_mode_creates_a_backup_and_touches_only_the_target_line(self, tmp_path):
        import subprocess
        import sys as _sys

        from fix_service_jwt_public_keys_json import _extract_env_var_line

        _private_key, public_key = _generate_test_keypair()
        jwk = _public_key_to_jwk(public_key, "m6-es256-2026-01")
        env_file = tmp_path / ".env"
        original_contents = (
            "MONGODB_URI=mongodb://localhost:27017/db\n"
            f"SERVICE_JWT_PUBLIC_KEYS_JSON={json.dumps({'m6-es256-2026-01': jwk})}\n"
            "REDIS_URL=redis://localhost:6380\n"
        )
        env_file.write_text(original_contents)

        script_path = Path(__file__).resolve().parents[1] / "scripts" / "fix_service_jwt_public_keys_json.py"
        result = subprocess.run(
            [_sys.executable, str(script_path), "--env-file", str(env_file), "--write"],
            capture_output=True,
            text=True,
            check=True,
        )

        backup_path = tmp_path / ".env.bak"
        assert backup_path.exists()
        assert backup_path.read_text() == original_contents

        updated_contents = env_file.read_text()
        assert "MONGODB_URI=mongodb://localhost:27017/db" in updated_contents
        assert "REDIS_URL=redis://localhost:6380" in updated_contents
        assert '"kty": "EC"' not in updated_contents  # the JWK shape is gone

        _line_index, corrected_value = _extract_env_var_line(updated_contents, "SERVICE_JWT_PUBLIC_KEYS_JSON")
        recovered = serialization.load_pem_public_key(json.loads(corrected_value)["m6-es256-2026-01"].encode("ascii"))
        assert recovered.public_numbers() == public_key.public_numbers()
        assert result.stdout.strip() == corrected_value
