# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import re

import pytest
import untrusted_signing_key
from sepvp import paths

pytestmark = pytest.mark.hostonly

_ROM_KEY0 = paths.BOOTCODE_DIR / "tests" / "signing_keys" / "rsa_private_key.rom_key0.pem"


def _key_digest_slot0() -> bytes:
    """ROM key slot 0 digest: 32 `0xNN` bytes in SHA-256 order inside `digest_rom_key0[...]`."""
    if not paths.KEY_DIGESTS_C.is_file():
        pytest.skip(f"{paths.KEY_DIGESTS_C} not built")
    text = paths.KEY_DIGESTS_C.read_text()
    block = re.search(r"digest_rom_key0\[[^\]]*\]\s*=\s*\{([^{}]*)\}", text)
    assert block is not None, "digest_rom_key0 initializer not found in key_digests.c"
    digest = bytes(int(b, 16) for b in re.findall(r"0x([0-9a-fA-F]{2})\b", block.group(1)))
    assert len(digest) == 32
    return digest


def test_modulus_digest_matches_the_rom_key_digest_form():
    assert untrusted_signing_key.modulus_digest(_ROM_KEY0) == _key_digest_slot0()


def test_untrusted_key_is_not_a_rom_key():
    assert untrusted_signing_key.modulus_digest(untrusted_signing_key.ensure()) != (
        _key_digest_slot0()
    )


def test_digest_words_rebuild_the_digest_bytes():
    words = untrusted_signing_key.digest_words()
    rebuilt = b"".join(word.to_bytes(4, "little") for word in words)
    key = untrusted_signing_key.ensure()
    assert rebuilt == untrusted_signing_key.modulus_digest(key)
