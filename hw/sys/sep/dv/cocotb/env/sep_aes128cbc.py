# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AES-128-CBC with PKCS#7, standard library only.

WHY THIS EXISTS RATHER THAN AN IMPORT. The packer encrypts payloads with
``cryptography`` (``bootrom/prod/tools/tt-boot-manifest/src/aes128cbc.py``), and the
DV virtualenv does not carry that module. A testcase whose defect lives in an
ENCRYPTED payload's TOC has to decrypt the shipped ciphertext, edit the plaintext
and re-encrypt it, so the cipher has to be available here. This is the same
situation ``sep_payload_mutate`` already resolved for RSA signing, and it is
resolved the same way: implement the primitive, then ANCHOR it.

TWO ANCHORS, because an unverified cipher is worse than no cipher -- a wrong
implementation produces ciphertext the ROM decrypts to garbage, and the run then
dies at ``MANIFEST_ERR_BAD_TOC_ID`` instead of at the check under test, which
looks like a plausible negative result.

  * :func:`self_test` runs the FIPS-197 Appendix C.1 known-answer vector in both
    directions. It runs at import, so a broken table or a broken key schedule
    cannot reach a testcase at all.
  * :func:`verify_roundtrip` is the image-side anchor, called by every caller in
    ``sep_payload_mutate``: decrypting a slot's SHIPPED ciphertext and
    re-encrypting the result must reproduce those bytes exactly. That covers the
    key, the IV, the padding convention and the block order together, so a
    re-encrypted payload is correct by construction rather than by assertion.

THIS IS NOT A DV SHORTCUT. Nothing here touches the DUT. The ROM's own AES engine
still performs the decryption under test, with the key it derives from the
CLASS_KEY fuse; this code only prepares the flash artefact, exactly as the packer
would have, so that the planted TOC defect is the only thing wrong with it.
"""

from __future__ import annotations

BLOCK_BYTES = 16
KEY_BYTES = 16


def _gen_tables() -> tuple[list[int], list[int]]:
    """S-box and its inverse, derived rather than transcribed.

    Generating from the GF(2^8) definition removes the one failure mode a
    hand-copied 256-entry table has: a single wrong nibble that survives review and
    corrupts one byte in sixteen.
    """
    sbox = [0] * 256
    p = q = 1
    while True:
        p = (p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)) & 0xFF
        q ^= (q << 1) & 0xFF
        q ^= (q << 2) & 0xFF
        q ^= (q << 4) & 0xFF
        if q & 0x80:
            q ^= 0x09
        q &= 0xFF
        x = (q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6))
             ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))) & 0xFF
        sbox[p] = x ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i
    return sbox, inv


_SBOX, _INV_SBOX = _gen_tables()
_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _mul(a: int, b: int) -> int:
    """Multiply in GF(2^8) modulo the AES polynomial."""
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        b >>= 1
        a = _xtime(a)
    return r


def _expand_key(key: bytes) -> list[list[int]]:
    """11 round keys of 16 bytes each."""
    if len(key) != KEY_BYTES:
        raise ValueError(f"AES-128 needs a {KEY_BYTES}-byte key, got {len(key)}")
    words = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(words[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // 4 - 1]
        words.append([words[i - 4][j] ^ t[j] for j in range(4)])
    return [[b for w in words[r * 4:r * 4 + 4] for b in w] for r in range(11)]


def _add_round_key(s: list[int], rk: list[int]) -> None:
    for i in range(16):
        s[i] ^= rk[i]


# State bytes are column-major, so row r of the state is s[r], s[r+4], s[r+8],
# s[r+12]. ShiftRows rotates row r left by r, and the inverse rotates right.
def _shift_rows(s: list[int]) -> None:
    for r in range(1, 4):
        row = [s[r], s[r + 4], s[r + 8], s[r + 12]]
        row = row[r:] + row[:r]
        s[r], s[r + 4], s[r + 8], s[r + 12] = row


def _inv_shift_rows(s: list[int]) -> None:
    for r in range(1, 4):
        row = [s[r], s[r + 4], s[r + 8], s[r + 12]]
        row = row[-r:] + row[:-r]
        s[r], s[r + 4], s[r + 8], s[r + 12] = row


def _mix_columns(s: list[int]) -> None:
    for c in range(4):
        col = s[c * 4:c * 4 + 4]
        s[c * 4 + 0] = _mul(col[0], 2) ^ _mul(col[1], 3) ^ col[2] ^ col[3]
        s[c * 4 + 1] = col[0] ^ _mul(col[1], 2) ^ _mul(col[2], 3) ^ col[3]
        s[c * 4 + 2] = col[0] ^ col[1] ^ _mul(col[2], 2) ^ _mul(col[3], 3)
        s[c * 4 + 3] = _mul(col[0], 3) ^ col[1] ^ col[2] ^ _mul(col[3], 2)


def _inv_mix_columns(s: list[int]) -> None:
    for c in range(4):
        col = s[c * 4:c * 4 + 4]
        s[c * 4 + 0] = (_mul(col[0], 14) ^ _mul(col[1], 11)
                        ^ _mul(col[2], 13) ^ _mul(col[3], 9))
        s[c * 4 + 1] = (_mul(col[0], 9) ^ _mul(col[1], 14)
                        ^ _mul(col[2], 11) ^ _mul(col[3], 13))
        s[c * 4 + 2] = (_mul(col[0], 13) ^ _mul(col[1], 9)
                        ^ _mul(col[2], 14) ^ _mul(col[3], 11))
        s[c * 4 + 3] = (_mul(col[0], 11) ^ _mul(col[1], 13)
                        ^ _mul(col[2], 9) ^ _mul(col[3], 14))


def encrypt_block(block: bytes, round_keys: list[list[int]]) -> bytes:
    s = list(block)
    _add_round_key(s, round_keys[0])
    for r in range(1, 10):
        s = [_SBOX[b] for b in s]
        _shift_rows(s)
        _mix_columns(s)
        _add_round_key(s, round_keys[r])
    s = [_SBOX[b] for b in s]
    _shift_rows(s)
    _add_round_key(s, round_keys[10])
    return bytes(s)


def decrypt_block(block: bytes, round_keys: list[list[int]]) -> bytes:
    s = list(block)
    _add_round_key(s, round_keys[10])
    for r in range(9, 0, -1):
        _inv_shift_rows(s)
        s = [_INV_SBOX[b] for b in s]
        _add_round_key(s, round_keys[r])
        _inv_mix_columns(s)
    _inv_shift_rows(s)
    s = [_INV_SBOX[b] for b in s]
    _add_round_key(s, round_keys[0])
    return bytes(s)


def _pad(data: bytes) -> bytes:
    """PKCS#7, which always appends -- a whole block when the input is aligned."""
    n = BLOCK_BYTES - (len(data) % BLOCK_BYTES)
    return data + bytes([n]) * n


def _unpad(data: bytes) -> bytes:
    if not data or len(data) % BLOCK_BYTES:
        raise ValueError(f"ciphertext length {len(data)} is not a block multiple")
    n = data[-1]
    if not 1 <= n <= BLOCK_BYTES or data[-n:] != bytes([n]) * n:
        raise ValueError(
            f"PKCS#7 padding is malformed (trailing byte 0x{data[-1]:02x}); the "
            f"key or the IV is wrong, or these bytes are not this payload's "
            f"ciphertext"
        )
    return data[:-n]


def encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    """AES-128-CBC encrypt with PKCS#7, matching the packer's ``aes128cbc.py``."""
    if len(iv) != BLOCK_BYTES:
        raise ValueError(f"IV must be {BLOCK_BYTES} bytes, got {len(iv)}")
    rk = _expand_key(key)
    prev = iv
    out = bytearray()
    data = _pad(plaintext)
    for i in range(0, len(data), BLOCK_BYTES):
        blk = bytes(a ^ b for a, b in zip(data[i:i + BLOCK_BYTES], prev))
        prev = encrypt_block(blk, rk)
        out += prev
    return bytes(out)


def decrypt_raw(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    """AES-128-CBC decrypt with no PKCS#7 removal, as the ROM's engine does it.

    The ROM decrypts ``payload_length`` bytes in place and never unpads
    (``aes_driver.c``), so this is the plaintext a boot actually parses. It is also
    the only way to inspect a decryption whose key or IV is WRONG: the recovered
    bytes then carry no valid padding, and :func:`decrypt` would raise instead of
    returning the garbage the ROM would go on to reject.
    """
    if len(iv) != BLOCK_BYTES:
        raise ValueError(f"IV must be {BLOCK_BYTES} bytes, got {len(iv)}")
    if len(ciphertext) % BLOCK_BYTES:
        raise ValueError(f"ciphertext length {len(ciphertext)} is not a block multiple")
    rk = _expand_key(key)
    prev = iv
    out = bytearray()
    for i in range(0, len(ciphertext), BLOCK_BYTES):
        ct = ciphertext[i:i + BLOCK_BYTES]
        out += bytes(a ^ b for a, b in zip(decrypt_block(ct, rk), prev))
        prev = ct
    return bytes(out)


def decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    """AES-128-CBC decrypt with PKCS#7 removal."""
    if len(iv) != BLOCK_BYTES:
        raise ValueError(f"IV must be {BLOCK_BYTES} bytes, got {len(iv)}")
    rk = _expand_key(key)
    prev = iv
    out = bytearray()
    for i in range(0, len(ciphertext), BLOCK_BYTES):
        ct = ciphertext[i:i + BLOCK_BYTES]
        out += bytes(a ^ b for a, b in zip(decrypt_block(ct, rk), prev))
        prev = ct
    return _unpad(bytes(out))


# FIPS-197 Appendix C.1.
_KAT_KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
_KAT_PT = bytes.fromhex("00112233445566778899aabbccddeeff")
_KAT_CT = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")


def self_test() -> None:
    """Known-answer check, both directions. Raises rather than returning a verdict."""
    rk = _expand_key(_KAT_KEY)
    got = encrypt_block(_KAT_PT, rk)
    if got != _KAT_CT:
        raise AssertionError(
            f"AES-128 encrypt fails the FIPS-197 C.1 vector: produced {got.hex()}, "
            f"expected {_KAT_CT.hex()}. Any payload re-encrypted with this module "
            f"would decrypt to garbage in the ROM"
        )
    back = decrypt_block(_KAT_CT, rk)
    if back != _KAT_PT:
        raise AssertionError(
            f"AES-128 decrypt fails the FIPS-197 C.1 vector: produced {back.hex()}, "
            f"expected {_KAT_PT.hex()}"
        )


self_test()


def verify_roundtrip(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    """Decrypt ``ciphertext``, re-encrypt, and require the shipped bytes back.

    The image-side anchor. It establishes the key, the IV, the padding convention
    and the block order at once: if re-encrypting the recovered plaintext does not
    reproduce the packer's own bytes, then the plaintext this module is about to
    edit is not the plaintext the ROM will see, and every conclusion drawn from a
    run of that image would be wrong.

    Returns the recovered plaintext, so the caller does not decrypt twice.
    """
    plain = decrypt(key, iv, ciphertext)
    again = encrypt(key, iv, plain)
    if again != ciphertext:
        raise AssertionError(
            f"re-encrypting the decrypted payload does not reproduce the shipped "
            f"ciphertext (got {again[:16].hex()}..., shipped {ciphertext[:16].hex()}"
            f"...); the key, the IV or the padding convention here no longer matches "
            f"the packer, so a re-encrypted payload would decrypt to garbage in the ROM"
        )
    return plain
