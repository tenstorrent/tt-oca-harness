# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""HMAC-SHA256 golden for ``sep_km_hmac_sideload_kat_test``.

Independent reference for the keyed-MAC the OpenTitan HMAC engine produces from a
KM-sideloaded key. Uses the Python standard library (`hmac` + `hashlib`), so the
env has no third-party crypto dependency. The construction is validated at import
against RFC 4231 Test Case 1, so a transcription error fails loudly rather than
silently agreeing with a broken DUT.

Register byte/word/endian convention (defaults key_word_rev=1, key_be=1,
msg_be=0):
  * KEY: KEY_SHARE0[7] is the most-significant 32-bit word of the 256-bit
    sideload key and KEY_SHARE0[0] is the least-significant; each word is
    big-endian on the byte lane.
  * MSG: pushed to MSG_FIFO as 32-bit words, consumed little-endian per word
    (msg_be=0).
  * DIGEST: CFG.digest_swap=0 -> {DIGEST_0..DIGEST_7} with DIGEST_0 as the most-
    significant word equals the standard big-endian SHA-256 digest; so digest
    word i == big-endian word i of the HMAC-SHA256 output.
"""

from __future__ import annotations

import hashlib
import hmac


def hmac_sha256_bytes(key: bytes, msg: bytes) -> bytes:
    """Standard HMAC-SHA256 over raw byte strings (big-endian 32-byte digest)."""
    return hmac.new(key, msg, hashlib.sha256).digest()


def _words_to_bytes(words: list[int], *, word_rev: bool, big_endian: bool) -> bytes:
    order = reversed(range(len(words))) if word_rev else range(len(words))
    return b"".join(
        (words[i] & 0xFFFF_FFFF).to_bytes(4, "big" if big_endian else "little") for i in order
    )


def hmac_sha256_words(
    key_words: list[int],
    msg_words: list[int],
    *,
    key_word_rev: bool = True,
    key_be: bool = True,
    msg_be: bool = False,
) -> list[int]:
    """HMAC-SHA256 expressed in OpenTitan HMAC register words.

    ``key_words`` = the 8 KM-delivered 256-bit key words (KEY_SHARE order).
    ``msg_words`` = the message as MSG_FIFO 32-bit words. Returns the 8 DIGEST
    words (DIGEST_0 = most-significant), directly comparable to the engine's
    DIGEST_0..7 read-back. Defaults: key_word_rev=1, key_be=1, msg_be=0.
    """
    assert len(key_words) == 8, "256-bit key = 8 words"
    key = _words_to_bytes(key_words, word_rev=key_word_rev, big_endian=key_be)
    msg = _words_to_bytes(msg_words, word_rev=False, big_endian=msg_be)
    mac = hmac_sha256_bytes(key, msg)
    return [int.from_bytes(mac[i * 4 : i * 4 + 4], "big") for i in range(8)]


# --- Generic SHA-2 variant layer (SHA-256/384/512, keyed HMAC or plain SHA) ---
# ``sep_hmac_sha_variant_rand_test`` covers all three SHA-2 variants in both
# keyed-HMAC and plain-SHA modes. Map the CFG.digest_size selection (by SHA
# output bit-width) to the stdlib hash constructor and the count of valid 32-bit
# DIGEST_* words the engine exposes: SHA-2 digest length / 32 (FIPS 180-4).
# SHA-256 -> 8, SHA-384 -> 12, SHA-512 -> 16.
_SHA2 = {
    256: (hashlib.sha256, 8),
    384: (hashlib.sha384, 12),
    512: (hashlib.sha512, 16),
}


def digest_word_count(sha_bits: int) -> int:
    """Number of valid 32-bit DIGEST_* words for the given SHA-2 variant."""
    return _SHA2[sha_bits][1]


def sha2_bytes(msg: bytes, sha_bits: int) -> bytes:
    """Plain SHA-2 (no key) over a raw byte string."""
    return _SHA2[sha_bits][0](msg).digest()


def hmac_sha2_bytes(key: bytes, msg: bytes, sha_bits: int) -> bytes:
    """Keyed HMAC-SHA-2 over raw byte strings."""
    return hmac.new(key, msg, _SHA2[sha_bits][0]).digest()


def hmac_or_sha_words(
    *,
    hmac_en: bool,
    sha_bits: int,
    msg_words: list[int],
    key_words: list[int] | None = None,
    key_word_rev: bool = True,
    key_be: bool = True,
    msg_be: bool = False,
    digest_swap: bool = False,
) -> list[int]:
    """OpenTitan HMAC DIGEST words for keyed HMAC or plain SHA, any SHA-2 variant.

    Returns the N valid DIGEST words (N = 8/12/16 for SHA-256/384/512). With
    ``digest_swap=0`` (RTL default) DIGEST_0 is the most-significant word and each
    word is big-endian, matching the engine read-back; ``digest_swap=1`` byte-
    swaps within each word. ``key_words`` is required when ``hmac_en`` and ignored
    for plain SHA. The key/msg byte conventions stay parameters: the SW-key path
    pins them from the DUT rather than from this golden.
    """
    msg = _words_to_bytes(msg_words, word_rev=False, big_endian=msg_be)
    if hmac_en:
        assert key_words is not None, "keyed HMAC needs key_words"
        key = _words_to_bytes(key_words, word_rev=key_word_rev, big_endian=key_be)
        out = hmac_sha2_bytes(key, msg, sha_bits)
    else:
        out = sha2_bytes(msg, sha_bits)
    endian = "little" if digest_swap else "big"
    return [
        int.from_bytes(out[i * 4 : i * 4 + 4], endian) for i in range(digest_word_count(sha_bits))
    ]


# --- RFC 4231 Test Case 1 HMAC self-tests (import-time) --------------------
# key = 0x0b*20, data = "Hi There" (RFC 4231 sec 4.2), for SHA-256/384/512.
_RFC4231_TC1_KEY = b"\x0b" * 20
_RFC4231_TC1_MSG = b"Hi There"
_RFC4231_TC1_MAC = bytes.fromhex("b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7")
_RFC4231_TC1_MAC_384 = bytes.fromhex(
    "afd03944d84895626b0825f4ab46907f15f9dadbe4101ec682aa034c7cebc59c"
    "faea9ea9076ede7f4af152e8b2fa9cb6"
)
_RFC4231_TC1_MAC_512 = bytes.fromhex(
    "87aa7cdea5ef619d4ff0b4241a1d6cb02379f4e2ce4ec2787ad0b30545e17cde"
    "daa833b7d6b8a702038b274eaea3f4e4be9d914eeb61f1702e696c203a126854"
)
assert hmac_sha256_bytes(_RFC4231_TC1_KEY, _RFC4231_TC1_MSG) == _RFC4231_TC1_MAC, (
    "HMAC-SHA256 golden failed the RFC 4231 TC1 self-test"
)
assert hmac_sha2_bytes(_RFC4231_TC1_KEY, _RFC4231_TC1_MSG, 384) == _RFC4231_TC1_MAC_384, (
    "HMAC-SHA384 golden failed the RFC 4231 TC1 self-test"
)
assert hmac_sha2_bytes(_RFC4231_TC1_KEY, _RFC4231_TC1_MSG, 512) == _RFC4231_TC1_MAC_512, (
    "HMAC-SHA512 golden failed the RFC 4231 TC1 self-test"
)

# Plain SHA-2 FIPS 180-4 "abc" known-answer self-tests.
_FIPS180_ABC = b"abc"
assert sha2_bytes(_FIPS180_ABC, 256) == bytes.fromhex(
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
), "SHA-256 golden failed the FIPS-180 'abc' self-test"
assert sha2_bytes(_FIPS180_ABC, 384) == bytes.fromhex(
    "cb00753f45a35e8bb5a03d699ac65007272c32ab0eded1631a8b605a43ff5bed"
    "8086072ba1e7cc2358baeca134c825a7"
), "SHA-384 golden failed the FIPS-180 'abc' self-test"
assert sha2_bytes(_FIPS180_ABC, 512) == bytes.fromhex(
    "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
    "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f"
), "SHA-512 golden failed the FIPS-180 'abc' self-test"
