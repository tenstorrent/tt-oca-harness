# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""An RSA-3072 signing key whose modulus digest is in no ROM key slot, generated on demand."""

import hashlib
import subprocess
from pathlib import Path

KEY_DIR = Path(__file__).parent / "keys"
KEY_PATH = KEY_DIR / "rsa_private_key.untrusted.pem"
KEY_NAME = "vp_untrusted_key_not_in_rom"
_MODULUS_BITS = 3072


def ensure() -> Path:
    """Return the key path, generating it if this workspace has none yet."""
    if KEY_PATH.is_file():
        return KEY_PATH
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["openssl", "genrsa", "-out", str(KEY_PATH), str(_MODULUS_BITS)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not KEY_PATH.is_file():
        raise RuntimeError(
            f"could not generate {KEY_PATH.name} with openssl genrsa:\n{result.stderr}"
        )
    KEY_PATH.chmod(0o600)
    return KEY_PATH


def modulus_digest(key: Path) -> bytes:
    """SHA-256 of *key*'s RSA modulus (384 bytes big-endian), the form the ROM key slots hold."""
    result = subprocess.run(
        ["openssl", "rsa", "-in", str(key), "-noout", "-modulus"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or "=" not in result.stdout:
        raise RuntimeError(f"could not read the modulus of {key}:\n{result.stderr}")
    modulus = bytes.fromhex(result.stdout.strip().split("=", 1)[1])
    if len(modulus) != _MODULUS_BITS // 8:
        raise RuntimeError(
            f"{key.name} is a {len(modulus) * 8}-bit key; the ROM verifies RSA-{_MODULUS_BITS} only"
        )
    return hashlib.sha256(modulus).digest()


def digest_words(key: Path | None = None) -> list[int]:
    """The modulus digest as eight little-endian 32-bit words, one per fuse register."""
    digest = modulus_digest(ensure() if key is None else key)
    return [
        int.from_bytes(digest[offset : offset + 4], "little") for offset in range(0, len(digest), 4)
    ]
