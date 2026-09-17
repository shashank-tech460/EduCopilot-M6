#!/usr/bin/env python3
"""MVP M6 environment/configuration fix -- NOT part of the application
itself, never imported by any app code, and does not touch
`app/security/service_jwt.py` or JWT verification behavior in any way.

DIAGNOSED ROOT CAUSE
=====================
`Settings.service_jwt_public_keys_json` must be a JSON object of
`{kid: PEM_public_key_string}` (confirmed directly against
`app/security/service_jwt.py::load_public_keys_json`, the one place
this project ever parses it). The M6 local-stack `SERVICE_JWT_PUBLIC_KEYS_JSON`
value instead contained a JSON *object* (a JWK -- JSON Web Key) as the
map's value:

    {"m6-es256-2026-01": {"kty": "EC", "crv": "P-256", "x": "...",
                           "y": "...", "alg": "ES256", "use": "sig",
                           "kid": "m6-es256-2026-01"}}

-- exactly matching the diagnostic evidence (`value_type = 'dict'`,
`value_length = 7`, the standard field count for an EC-P256 JWK with
`alg`/`use`/`kid` present). This is consistent with the key having been
exported via a JWK-producing function (e.g. `jose`'s `exportJWK()`) on
the Team 4C side instead of a PEM-producing one (`exportSPKI()`, which
`scripts/interop-generate-tokens.ts` on the Team 4C side already uses
correctly for its own, separate interop-test purpose -- confirmed by
inspection; that script was not the source of this particular M6
environment value).

WHAT THIS SCRIPT DOES
=====================
Converts a JWK-shaped public key value back into the SAME underlying
EC public key's SPKI PEM representation. This is safe and lossless: a
JWK's `x`/`y` coordinates fully and exactly determine one specific EC
public key, regardless of which serialization format (JWK vs. PEM) is
used to represent it -- converting between them does NOT create, alter,
weaken, or replace the key in any way. This script never generates a
new key, never touches a private key, and never writes anything by
itself -- it only prints the corrected value for the operator to paste
into their own local environment configuration.

USAGE
=====
    # Directly against a real Team 4B .env file (recommended -- see the
    # "OPERATOR PROCEDURE NOTE" below for why --from-env alone is NOT
    # reliable for a value that only exists in .env):
    python scripts/fix_service_jwt_public_keys_json.py --env-file .env

    # Same, but also rewrite ONLY that one line in .env in place
    # (a .bak backup of the original file is written first; every other
    # line/variable in .env is left byte-for-byte untouched):
    python scripts/fix_service_jwt_public_keys_json.py --env-file .env --write

    # From a file containing just the current (broken) value:
    python scripts/fix_service_jwt_public_keys_json.py --input current_value.json

    # From stdin:
    echo '{"kid-1": {"kty": "EC", ...}}' | python scripts/fix_service_jwt_public_keys_json.py

    # From the current PROCESS environment (NOT the same as .env -- see below):
    python scripts/fix_service_jwt_public_keys_json.py --from-env

OPERATOR PROCEDURE NOTE -- why `--from-env` alone is often NOT what you want
=============================================================================
Team 4B's Pydantic Settings loads `.env` itself, on the application's
own startup -- but plain Python `os.environ` (which `--from-env` reads)
does NOT automatically contain `.env`'s contents unless something else
separately exported those variables into the actual process environment
(e.g. a shell that sourced `.env` first). Running `--from-env` in an
ordinary terminal that never did that will see nothing, or a stale/
unrelated value, even though `.env` on disk has the real one. Use
`--env-file <path>` to read directly from the actual `.env` file Team 4B
will load, instead.

Prints the corrected `{kid: PEM_string}` JSON to stdout on success. A
value that is ALREADY a correct PEM string is left completely
unchanged (idempotent -- safe to run even if only some KIDs need
correcting, or none do).

Exits non-zero, with a message on stderr, for anything it cannot safely
convert (an unsupported key type/curve, a malformed JWK, or a value
that is neither a string nor an EC JWK object) -- it never guesses or
silently drops a KID.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _jwk_to_spki_pem(jwk: dict) -> str:
    """Converts one EC public-key JWK to an SPKI PEM string -- the exact
    format `load_public_keys_json`/`ServiceJWTVerifier` require. Only
    ever reads `crv`/`x`/`y` (the coordinates that define the public
    key itself); `alg`/`use`/`kid`/any other JWK metadata field is
    intentionally ignored here, since none of it changes what key this
    is -- carrying it over would be redundant with (and could drift
    from) the KID already used as this map's own key.
    """

    if jwk.get("kty") != "EC":
        raise ValueError(f"Unsupported JWK kty {jwk.get('kty')!r} -- only EC (ES256) keys are supported here")

    curve_name = jwk.get("crv")
    if curve_name != "P-256":
        raise ValueError(f"Unsupported JWK crv {curve_name!r} -- ES256 requires P-256")

    if "x" not in jwk or "y" not in jwk:
        raise ValueError("JWK is missing required 'x'/'y' coordinate fields")

    x = int.from_bytes(_b64url_decode(jwk["x"]), "big")
    y = int.from_bytes(_b64url_decode(jwk["y"]), "big")

    public_numbers = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1())
    public_key = public_numbers.public_key()

    pem_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pem_bytes.decode("ascii")


def _is_already_a_valid_pem(value: str) -> bool:
    try:
        serialization.load_pem_public_key(value.encode("ascii"))
        return True
    except Exception:  # noqa: BLE001 -- any failure just means "not already a valid PEM"
        return False


def fix_public_keys_json(raw: str) -> str:
    """Takes the CURRENT (possibly broken) `SERVICE_JWT_PUBLIC_KEYS_JSON`
    string and returns a corrected version: every KID's value is a real
    SPKI PEM string. A KID whose value is already a valid PEM string is
    passed through byte-for-byte, unchanged.
    """

    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Top-level value must be a JSON object of {kid: value}")

    corrected: dict[str, str] = {}
    for kid, value in parsed.items():
        if isinstance(value, str):
            if not _is_already_a_valid_pem(value):
                raise ValueError(f"KID {kid!r}'s string value is not a valid PEM public key")
            corrected[kid] = value
        elif isinstance(value, dict):
            corrected[kid] = _jwk_to_spki_pem(value)
        else:
            raise ValueError(f"KID {kid!r}'s value is neither a string nor a JWK object ({type(value).__name__})")

    return json.dumps(corrected)


def _extract_env_var_line(env_file_contents: str, var_name: str) -> tuple[int, str]:
    """Finds the SINGLE line in a `.env` file's contents that assigns
    `var_name`, and returns `(line_index, raw_value)`. `raw_value` has
    a single layer of surrounding double or single quotes stripped, if
    present (a common `.env` convention for values containing special
    characters, as this JSON value's braces/quotes typically require) --
    never more than one layer, and never attempting to interpret
    backslash escapes or any other shell/dotenv quoting nuance beyond
    that single strip, since accidentally over-processing the value
    would risk corrupting the JSON itself.

    Raises `ValueError` if the variable is not found, or is defined more
    than once (ambiguous -- this tool refuses to guess which one is
    authoritative rather than silently picking one).
    """

    lines = env_file_contents.splitlines()
    prefix = f"{var_name}="
    matches = [i for i, line in enumerate(lines) if line.startswith(prefix)]

    if not matches:
        raise ValueError(f"{var_name} was not found in the given .env file")
    if len(matches) > 1:
        raise ValueError(f"{var_name} is defined more than once in the given .env file (lines {matches}) -- ambiguous")

    line_index = matches[0]
    value = lines[line_index][len(prefix):]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return line_index, value


def _replace_env_var_line(env_file_contents: str, line_index: int, var_name: str, new_value: str) -> str:
    """Rewrites ONLY `line_index` (as identified by `_extract_env_var_line`)
    to assign `new_value` to `var_name` -- every other line, in its
    original order, spacing, and content (including comments and blank
    lines), is preserved byte-for-byte. The new value is wrapped in
    double quotes (safe and necessary here, since a JSON object value
    contains `{`, `}`, and `"` characters that are not otherwise safe as
    a bare, unquoted `.env` value on most parsers, including
    pydantic-settings' own `.env` loader).
    """

    lines = env_file_contents.splitlines()
    lines[line_index] = f'{var_name}="{new_value}"'
    trailing_newline = "\n" if env_file_contents.endswith("\n") else ""
    return "\n".join(lines) + trailing_newline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", help="Path to a file containing the current env var value")
    parser.add_argument(
        "--from-env", action="store_true", help="Read the current SERVICE_JWT_PUBLIC_KEYS_JSON environment variable"
    )
    parser.add_argument(
        "--env-file",
        help=(
            "Path to a real .env file -- reads the SERVICE_JWT_PUBLIC_KEYS_JSON=... line directly out of it "
            "(Team 4B's Pydantic Settings loads .env, but plain os.environ does NOT -- --from-env alone will "
            "not see a value that only exists in .env unless it was separately exported into the process)."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Combine with --env-file: rewrite ONLY the SERVICE_JWT_PUBLIC_KEYS_JSON line in that file in place "
            "(a .bak backup of the original file is written alongside it first). Every other line/variable in "
            "the file is left completely untouched. Without this flag, --env-file only PRINTS the corrected "
            "value and never modifies any file."
        ),
    )
    args = parser.parse_args()

    var_name = "SERVICE_JWT_PUBLIC_KEYS_JSON"

    if args.env_file:
        with open(args.env_file, encoding="utf-8") as f:
            env_file_contents = f.read()
        try:
            line_index, raw = _extract_env_var_line(env_file_contents, var_name)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    elif args.from_env:
        raw = os.environ.get(var_name, "")
        if not raw:
            print(f"{var_name} is not set in the current process environment.", file=sys.stderr)
            return 1
    elif args.input:
        with open(args.input, encoding="utf-8") as f:
            raw = f.read().strip()
    else:
        raw = sys.stdin.read().strip()

    if not raw:
        print("No input provided (empty value).", file=sys.stderr)
        return 1

    try:
        corrected = fix_public_keys_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Could not safely convert the given value: {exc}", file=sys.stderr)
        return 1

    if args.env_file and args.write:
        backup_path = f"{args.env_file}.bak"
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(env_file_contents)
        updated_contents = _replace_env_var_line(env_file_contents, line_index, var_name, corrected)
        with open(args.env_file, "w", encoding="utf-8") as f:
            f.write(updated_contents)
        print(f"Backed up original file to: {backup_path}", file=sys.stderr)
        print(f"Updated {var_name} in place in: {args.env_file}", file=sys.stderr)

    print(corrected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
