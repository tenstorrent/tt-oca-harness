# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Pure-Python AES golden: ECB/CBC/CTR encrypt and ECB/CBC decrypt at 128/192/256 bits.

Used by ``sep_km_aes_sideload_kat_test`` and ``sep_aes_mode_keysize_rand_test``. Derived from
FIPS-197, not from DUT output; it self-tests at import against FIPS-197 Appendix C and SP800-38A
vectors.

Register packing (OpenTitan AES, little-endian words): KEY_SHARE0_0 holds key bytes [3:0] with
byte 0 as LSB, and DATA_IN/DATA_OUT/IV pack the same way. The ``*_words`` functions apply it.
"""

from __future__ import annotations

# --- AES S-box (FIPS-197 Figure 7) -----------------------------------------
_SBOX = (
    0x63,
    0x7C,
    0x77,
    0x7B,
    0xF2,
    0x6B,
    0x6F,
    0xC5,
    0x30,
    0x01,
    0x67,
    0x2B,
    0xFE,
    0xD7,
    0xAB,
    0x76,
    0xCA,
    0x82,
    0xC9,
    0x7D,
    0xFA,
    0x59,
    0x47,
    0xF0,
    0xAD,
    0xD4,
    0xA2,
    0xAF,
    0x9C,
    0xA4,
    0x72,
    0xC0,
    0xB7,
    0xFD,
    0x93,
    0x26,
    0x36,
    0x3F,
    0xF7,
    0xCC,
    0x34,
    0xA5,
    0xE5,
    0xF1,
    0x71,
    0xD8,
    0x31,
    0x15,
    0x04,
    0xC7,
    0x23,
    0xC3,
    0x18,
    0x96,
    0x05,
    0x9A,
    0x07,
    0x12,
    0x80,
    0xE2,
    0xEB,
    0x27,
    0xB2,
    0x75,
    0x09,
    0x83,
    0x2C,
    0x1A,
    0x1B,
    0x6E,
    0x5A,
    0xA0,
    0x52,
    0x3B,
    0xD6,
    0xB3,
    0x29,
    0xE3,
    0x2F,
    0x84,
    0x53,
    0xD1,
    0x00,
    0xED,
    0x20,
    0xFC,
    0xB1,
    0x5B,
    0x6A,
    0xCB,
    0xBE,
    0x39,
    0x4A,
    0x4C,
    0x58,
    0xCF,
    0xD0,
    0xEF,
    0xAA,
    0xFB,
    0x43,
    0x4D,
    0x33,
    0x85,
    0x45,
    0xF9,
    0x02,
    0x7F,
    0x50,
    0x3C,
    0x9F,
    0xA8,
    0x51,
    0xA3,
    0x40,
    0x8F,
    0x92,
    0x9D,
    0x38,
    0xF5,
    0xBC,
    0xB6,
    0xDA,
    0x21,
    0x10,
    0xFF,
    0xF3,
    0xD2,
    0xCD,
    0x0C,
    0x13,
    0xEC,
    0x5F,
    0x97,
    0x44,
    0x17,
    0xC4,
    0xA7,
    0x7E,
    0x3D,
    0x64,
    0x5D,
    0x19,
    0x73,
    0x60,
    0x81,
    0x4F,
    0xDC,
    0x22,
    0x2A,
    0x90,
    0x88,
    0x46,
    0xEE,
    0xB8,
    0x14,
    0xDE,
    0x5E,
    0x0B,
    0xDB,
    0xE0,
    0x32,
    0x3A,
    0x0A,
    0x49,
    0x06,
    0x24,
    0x5C,
    0xC2,
    0xD3,
    0xAC,
    0x62,
    0x91,
    0x95,
    0xE4,
    0x79,
    0xE7,
    0xC8,
    0x37,
    0x6D,
    0x8D,
    0xD5,
    0x4E,
    0xA9,
    0x6C,
    0x56,
    0xF4,
    0xEA,
    0x65,
    0x7A,
    0xAE,
    0x08,
    0xBA,
    0x78,
    0x25,
    0x2E,
    0x1C,
    0xA6,
    0xB4,
    0xC6,
    0xE8,
    0xDD,
    0x74,
    0x1F,
    0x4B,
    0xBD,
    0x8B,
    0x8A,
    0x70,
    0x3E,
    0xB5,
    0x66,
    0x48,
    0x03,
    0xF6,
    0x0E,
    0x61,
    0x35,
    0x57,
    0xB9,
    0x86,
    0xC1,
    0x1D,
    0x9E,
    0xE1,
    0xF8,
    0x98,
    0x11,
    0x69,
    0xD9,
    0x8E,
    0x94,
    0x9B,
    0x1E,
    0x87,
    0xE9,
    0xCE,
    0x55,
    0x28,
    0xDF,
    0x8C,
    0xA1,
    0x89,
    0x0D,
    0xBF,
    0xE6,
    0x42,
    0x68,
    0x41,
    0x99,
    0x2D,
    0x0F,
    0xB0,
    0x54,
    0xBB,
    0x16,
)
_INV_SBOX = tuple(_SBOX.index(value) for value in range(256))

_NB = 4  # columns in the AES state
_NK = 8  # 32-bit words in an AES-256 key
_NR = 14  # rounds for AES-256


def _xtime(a: int) -> int:
    """Multiply by x (0x02) in GF(2^8) with the AES reduction polynomial."""
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _gmul(a: int, b: int) -> int:
    """GF(2^8) multiply (used for MixColumns)."""
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        b >>= 1
        a = _xtime(a)
    return result & 0xFF


def _key_expansion(key: bytes, nk: int, nr: int) -> list[list[int]]:
    """Expand an AES key into 4*(Nr+1) round-key words (each a 4-byte list).

    ``nk`` = key words (4/6/8 for AES-128/192/256); ``nr`` = rounds (nk+6). The
    extra SubWord at ``i % nk == 4`` applies ONLY for Nk>6 (AES-256), per FIPS-197.
    """
    assert len(key) == 4 * nk, f"AES key must be {4 * nk} bytes for Nk={nk}"
    words: list[list[int]] = [list(key[4 * i : 4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, _NB * (nr + 1)):
        temp = list(words[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]  # RotWord
            temp = [_SBOX[b] for b in temp]  # SubWord
            temp[0] ^= rcon  # Rcon
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            temp = [_SBOX[b] for b in temp]  # extra SubWord (Nk>6 only)
        words.append([words[i - nk][j] ^ temp[j] for j in range(4)])
    return words


def _add_round_key(state: list[list[int]], words: list[list[int]], rnd: int) -> None:
    for col in range(_NB):
        rk = words[rnd * _NB + col]
        for row in range(4):
            state[row][col] ^= rk[row]


def _sub_bytes(state: list[list[int]]) -> None:
    for row in range(4):
        for col in range(_NB):
            state[row][col] = _SBOX[state[row][col]]


def _shift_rows(state: list[list[int]]) -> None:
    for row in range(1, 4):
        state[row] = state[row][row:] + state[row][:row]


def _inv_shift_rows(state: list[list[int]]) -> None:
    for row in range(1, 4):
        state[row] = state[row][-row:] + state[row][:-row]


def _mix_columns(state: list[list[int]]) -> None:
    for col in range(_NB):
        s0, s1, s2, s3 = (state[r][col] for r in range(4))
        state[0][col] = _gmul(s0, 2) ^ _gmul(s1, 3) ^ s2 ^ s3
        state[1][col] = s0 ^ _gmul(s1, 2) ^ _gmul(s2, 3) ^ s3
        state[2][col] = s0 ^ s1 ^ _gmul(s2, 2) ^ _gmul(s3, 3)
        state[3][col] = _gmul(s0, 3) ^ s1 ^ s2 ^ _gmul(s3, 2)


def _inv_mix_columns(state: list[list[int]]) -> None:
    for col in range(_NB):
        s0, s1, s2, s3 = (state[r][col] for r in range(4))
        state[0][col] = _gmul(s0, 14) ^ _gmul(s1, 11) ^ _gmul(s2, 13) ^ _gmul(s3, 9)
        state[1][col] = _gmul(s0, 9) ^ _gmul(s1, 14) ^ _gmul(s2, 11) ^ _gmul(s3, 13)
        state[2][col] = _gmul(s0, 13) ^ _gmul(s1, 9) ^ _gmul(s2, 14) ^ _gmul(s3, 11)
        state[3][col] = _gmul(s0, 11) ^ _gmul(s1, 13) ^ _gmul(s2, 9) ^ _gmul(s3, 14)


def aes_encrypt_block(key: bytes, block: bytes) -> bytes:
    """AES encrypt one 16-byte block (ECB, no padding). FIPS-197 Cipher().

    ``key`` is 16/24/32 bytes for AES-128/192/256; rounds Nr = Nk+6."""
    assert len(block) == 16, "AES block must be 16 bytes"
    assert len(key) in (16, 24, 32), "AES key must be 16/24/32 bytes"
    nk = len(key) // 4
    nr = nk + 6
    words = _key_expansion(key, nk, nr)
    # Column-major state: state[row][col] = block[col*4 + row].
    state = [[block[col * 4 + row] for col in range(_NB)] for row in range(4)]
    _add_round_key(state, words, 0)
    for rnd in range(1, nr):
        _sub_bytes(state)
        _shift_rows(state)
        _mix_columns(state)
        _add_round_key(state, words, rnd)
    _sub_bytes(state)
    _shift_rows(state)
    _add_round_key(state, words, nr)
    return bytes(state[row][col] for col in range(_NB) for row in range(4))


def aes_decrypt_block(key: bytes, block: bytes) -> bytes:
    """AES decrypt one 16-byte block (ECB, no padding). FIPS-197 InvCipher()."""
    assert len(block) == 16, "AES block must be 16 bytes"
    assert len(key) in (16, 24, 32), "AES key must be 16/24/32 bytes"
    nk = len(key) // 4
    nr = nk + 6
    words = _key_expansion(key, nk, nr)
    state = [[block[col * 4 + row] for col in range(_NB)] for row in range(4)]
    _add_round_key(state, words, nr)
    for rnd in range(nr - 1, 0, -1):
        _inv_shift_rows(state)
        for row in range(4):
            for col in range(_NB):
                state[row][col] = _INV_SBOX[state[row][col]]
        _add_round_key(state, words, rnd)
        _inv_mix_columns(state)
    _inv_shift_rows(state)
    for row in range(4):
        for col in range(_NB):
            state[row][col] = _INV_SBOX[state[row][col]]
    _add_round_key(state, words, 0)
    return bytes(state[row][col] for col in range(_NB) for row in range(4))


def aes256_encrypt_block(key: bytes, block: bytes) -> bytes:
    """AES-256 encrypt one block."""
    assert len(key) == 32, "AES-256 key must be 32 bytes"
    return aes_encrypt_block(key, block)


def aes256_ecb_encrypt_words(key_words: list[int], pt_words: list[int]) -> list[int]:
    """Encrypt one block expressed as OpenTitan AES register words.

    ``key_words`` = the effective AES-256 key (8 words; DUT ``SHARE0 ^ SHARE1``).
    ``pt_words``  = DATA_IN_0..3 (4 words). Returns DATA_OUT_0..3 (4 words).
    Word<->byte packing is little-endian, matching the AES register convention.
    """
    assert len(key_words) == 8, "AES-256 needs 8 key words"
    assert len(pt_words) == 4, "AES block needs 4 data words"
    key = b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in key_words)
    block = b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in pt_words)
    ct = aes256_encrypt_block(key, block)
    return [int.from_bytes(ct[i * 4 : i * 4 + 4], "little") for i in range(4)]


# --- Mode wrappers: ECB / CBC / CTR over the block cipher (FIPS-197 + SP800-38A)
# All operate on raw byte strings; the register word<->byte packing is applied by
# the *_words wrappers below. CTR encrypt == decrypt (keystream XOR).
def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def aes_ecb_encrypt(key: bytes, data: bytes) -> bytes:
    """ECB: independent blocks (no chaining). len(data) a multiple of 16."""
    assert len(data) % 16 == 0, "ECB data must be block-aligned"
    return b"".join(aes_encrypt_block(key, data[i : i + 16]) for i in range(0, len(data), 16))


def aes_cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """CBC (SP800-38A 6.2): C_i = E(P_i XOR C_{i-1}), C_0 uses IV."""
    assert len(iv) == 16 and len(data) % 16 == 0, "CBC IV=16B, data block-aligned"
    out, prev = b"", iv
    for i in range(0, len(data), 16):
        prev = aes_encrypt_block(key, _xor(data[i : i + 16], prev))
        out += prev
    return out


def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """CBC inverse (SP800-38A 6.2), without padding removal."""
    assert len(iv) == 16 and len(data) % 16 == 0, "CBC IV=16B, data block-aligned"
    out, prev = b"", iv
    for i in range(0, len(data), 16):
        block = data[i : i + 16]
        out += _xor(aes_decrypt_block(key, block), prev)
        prev = block
    return out


def aes_ctr_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """CTR (SP800-38A 6.5): C_i = P_i XOR E(counter_i); counter increments as a
    128-bit big-endian integer (the SEP AES IV increment convention)."""
    assert len(iv) == 16, "CTR IV/counter must be 16 bytes"
    out, ctr = b"", int.from_bytes(iv, "big")
    for i in range(0, len(data), 16):
        ks = aes_encrypt_block(key, (ctr & ((1 << 128) - 1)).to_bytes(16, "big"))
        blk = data[i : i + 16]
        out += _xor(blk, ks[: len(blk)])
        ctr += 1
    return out


_MODE_FN = {"ecb": aes_ecb_encrypt, "cbc": aes_cbc_encrypt, "ctr": aes_ctr_encrypt}


def _words_to_le_bytes(words: list[int]) -> bytes:
    """Register words -> byte stream, little-endian per 32-bit word (AES reg
    convention: KEY_SHARE/DATA_IN/IV all pack byte0 = LSB)."""
    return b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in words)


def _le_bytes_to_words(data: bytes) -> list[int]:
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


def aes_encrypt_words(
    mode: str, key_words: list[int], pt_words: list[int], iv_words: list[int] | None = None
) -> list[int]:
    """Encrypt in OpenTitan AES register words. ``mode`` in {ecb,cbc,ctr}.

    ``key_words`` = the effective key (4/6/8 words for AES-128/192/256; DUT ``SHARE0 ^ SHARE1``).
    ``pt_words`` = DATA_IN words (a multiple of 4). ``iv_words`` = IV_0..3 for
    CBC/CTR (ignored for ECB). Returns DATA_OUT words. Word<->byte packing is
    little-endian, matching the register convention.
    """
    assert mode in _MODE_FN, f"unknown AES mode {mode}"
    assert len(pt_words) % 4 == 0, "AES plaintext must be whole 128-bit blocks"
    key = _words_to_le_bytes(key_words)
    pt = _words_to_le_bytes(pt_words)
    if mode == "ecb":
        ct = aes_ecb_encrypt(key, pt)
    else:
        assert iv_words is not None and len(iv_words) == 4, f"{mode} needs 4 IV words"
        ct = _MODE_FN[mode](key, _words_to_le_bytes(iv_words), pt)
    return _le_bytes_to_words(ct)


# --- Known-answer self-tests (import-time): FIPS-197 ECB + SP800-38A CBC/CTR ---
# ECB single-block, key = 000102..., PT = 00112233...ff (FIPS-197 App. C.1/2/3).
_FIPS197_PT = bytes.fromhex("00112233445566778899aabbccddeeff")
assert aes_encrypt_block(bytes(range(16)), _FIPS197_PT) == bytes.fromhex(
    "69c4e0d86a7b0430d8cdb78070b4c55a"
), "AES-128 ECB FIPS-197 C.1 self-test failed"
assert aes_encrypt_block(bytes(range(24)), _FIPS197_PT) == bytes.fromhex(
    "dda97ca4864cdfe06eaf70a0ec0d7191"
), "AES-192 ECB FIPS-197 C.2 self-test failed"
assert aes256_encrypt_block(bytes(range(32)), _FIPS197_PT) == bytes.fromhex(
    "8ea2b7ca516745bfeafc49904b496089"
), "AES-256 ECB FIPS-197 C.3 self-test failed"
assert (
    aes_decrypt_block(bytes(range(32)), bytes.fromhex("8ea2b7ca516745bfeafc49904b496089"))
    == _FIPS197_PT
), "AES-256 inverse FIPS-197 C.3 self-test failed"

# SP800-38A AES-128 CBC (F.2.1) and CTR (F.5.1), 2 blocks each.
_SP38A_KEY = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
_SP38A_PT2 = bytes.fromhex("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51")
assert aes_cbc_encrypt(
    _SP38A_KEY, bytes.fromhex("000102030405060708090a0b0c0d0e0f"), _SP38A_PT2
) == bytes.fromhex("7649abac8119b246cee98e9b12e9197d5086cb9b507219ee95db113a917678b2"), (
    "AES-128 CBC SP800-38A F.2.1 self-test failed"
)
assert (
    aes_cbc_decrypt(
        _SP38A_KEY,
        bytes.fromhex("000102030405060708090a0b0c0d0e0f"),
        bytes.fromhex("7649abac8119b246cee98e9b12e9197d5086cb9b507219ee95db113a917678b2"),
    )
    == _SP38A_PT2
), "AES-128 CBC inverse SP800-38A F.2.1 self-test failed"
assert aes_ctr_encrypt(
    _SP38A_KEY, bytes.fromhex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff"), _SP38A_PT2
) == bytes.fromhex("874d6191b620e3261bef6864990db6ce9806f66b7970fdff8617187bb9fffdff"), (
    "AES-128 CTR SP800-38A F.5.1 self-test failed"
)
