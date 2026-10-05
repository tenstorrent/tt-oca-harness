# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""An RSA-3072 signing key whose modulus digest is in no ROM key slot, generated on demand."""

import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_DIR = Path(__file__).parent / "keys"
KEY_PATH = KEY_DIR / "rsa_private_key.untrusted.pem"
KEY_NAME = "vp_untrusted_key_not_in_rom"
_MODULUS_BITS = 3072


def ensure() -> Path:
    """Return the key path, generating it if this workspace has none yet."""
    if KEY_PATH.is_file():
        return KEY_PATH
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=_MODULUS_BITS)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    KEY_PATH.touch(mode=0o600)
    KEY_PATH.write_bytes(pem)
    return KEY_PATH


def modulus_digest(key: Path) -> bytes:
    """SHA-256 of *key*'s RSA modulus (384 bytes big-endian), the form the ROM key slots hold."""
    private = serialization.load_pem_private_key(key.read_bytes(), password=None)
    if not isinstance(private, rsa.RSAPrivateKey):
        raise RuntimeError(f"{key.name} is not an RSA private key")
    if private.key_size != _MODULUS_BITS:
        raise RuntimeError(
            f"{key.name} is a {private.key_size}-bit key; the ROM verifies RSA-{_MODULUS_BITS} only"
        )
    modulus = private.public_key().public_numbers().n.to_bytes(_MODULUS_BITS // 8, "big")
    return hashlib.sha256(modulus).digest()


def digest_words(key: Path | None = None) -> list[int]:
    """The modulus digest as eight little-endian 32-bit words, one per fuse register."""
    digest = modulus_digest(ensure() if key is None else key)
    return [
        int.from_bytes(digest[offset : offset + 4], "little") for offset in range(0, len(digest), 4)
    ]
