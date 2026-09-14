# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Self-contained Keccak / SHA-3 / SHAKE / cSHAKE / KMAC golden (FIPS-202 +
SP800-185) for the KMAC mode x strength breadth test.

Pure Python, with no third-party crypto dependency so the environment stays
self-contained. A raw
Keccak-f[1600] sponge implements the whole family; SHA-3 and SHAKE are ALSO
cross-checked against the Python stdlib (`hashlib.sha3_*`/`shake_*`) at import, so
a transcription error in the permutation, padding, or rate fails loudly here
rather than silently agreeing with a broken DUT. cSHAKE and KMAC
(not in hashlib) are validated against the NIST SP800-185 sample vectors.

Register byte/word convention (OpenTitan KMAC little-endian defaults,
msg_endianness=0/state_endianness=0): the MSG_FIFO, KEY_SHARE, and STATE windows
pack byte0 = LSB per 32-bit word. The *_words wrappers apply exactly this
little-endian word<->byte packing so the output is comparable to the STATE
share0^share1 read-back.
"""

from __future__ import annotations

import hashlib

# --- Keccak-f[1600] permutation (FIPS-202) ---------------------------------
_RC = [
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
]
_ROTC = [1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 2, 14, 27, 41, 56, 8, 25, 43, 62, 18, 39, 61, 20, 44]
_PILN = [10, 7, 11, 17, 18, 3, 5, 16, 8, 21, 24, 4, 15, 23, 19, 13, 12, 2, 20, 14, 22, 9, 6, 1]
_MASK = (1 << 64) - 1


def _rol(x: int, n: int) -> int:
    return ((x << n) | (x >> (64 - n))) & _MASK


def _keccak_f(st: list[int]) -> None:
    for rnd in range(24):
        # theta
        bc = [st[i] ^ st[i + 5] ^ st[i + 10] ^ st[i + 15] ^ st[i + 20] for i in range(5)]
        for i in range(5):
            t = bc[(i + 4) % 5] ^ _rol(bc[(i + 1) % 5], 1)
            for j in range(0, 25, 5):
                st[j + i] ^= t
        # rho + pi
        t = st[1]
        for i in range(24):
            j = _PILN[i]
            bc0 = st[j]
            st[j] = _rol(t, _ROTC[i])
            t = bc0
        # chi
        for j in range(0, 25, 5):
            row = [st[j + i] for i in range(5)]
            for i in range(5):
                st[j + i] ^= (~row[(i + 1) % 5]) & row[(i + 2) % 5]
        # iota
        st[0] ^= _RC[rnd]


def _keccak(rate_bytes: int, msg: bytes, dsbyte: int, outlen: int) -> bytes:
    """Keccak sponge: absorb ``msg`` at ``rate_bytes`` with pad10*1 + domain
    ``dsbyte``, squeeze ``outlen`` bytes."""
    st = [0] * 25
    data = bytearray(msg)
    data.append(dsbyte)
    while len(data) % rate_bytes != 0:
        data.append(0x00)
    data[-1] ^= 0x80
    for off in range(0, len(data), rate_bytes):
        for i in range(rate_bytes // 8):
            st[i] ^= int.from_bytes(data[off + i * 8 : off + i * 8 + 8], "little")
        _keccak_f(st)
    out = bytearray()
    while len(out) < outlen:
        for i in range(rate_bytes // 8):
            out += st[i].to_bytes(8, "little")
        if len(out) < outlen:
            _keccak_f(st)
    return bytes(out[:outlen])


# --- SP800-185 encoding helpers --------------------------------------------
def _left_encode(x: int) -> bytes:
    n = max(1, (x.bit_length() + 7) // 8)
    return bytes([n]) + x.to_bytes(n, "big")


def _right_encode(x: int) -> bytes:
    n = max(1, (x.bit_length() + 7) // 8)
    return x.to_bytes(n, "big") + bytes([n])


def _encode_string(s: bytes) -> bytes:
    return _left_encode(len(s) * 8) + s


def _bytepad(x: bytes, w: int) -> bytes:
    out = bytearray(_left_encode(w) + x)
    while len(out) % w != 0:
        out.append(0x00)
    return bytes(out)


# Public SP800-185 encoders, shared with the KMAC stimulus sequence so the DUT
# PREFIX (encode_string(N)||encode_string(S)) and the KMAC message-tail
# right_encode(L) bytes match this golden exactly.
left_encode = _left_encode
right_encode = _right_encode
encode_string = _encode_string


# Rate (bytes) per keccak_strength_e for the KMAC/SHA3 family: rate = 200 - 2*sec.
_RATE = {128: 168, 224: 144, 256: 136, 384: 104, 512: 72}


# --- FIPS-202: SHA-3 / SHAKE ------------------------------------------------
def sha3(msg: bytes, sec: int) -> bytes:
    """SHA3-224/256/384/512 (fixed digest = sec bits)."""
    return _keccak(_RATE[sec], msg, 0x06, sec // 8)


def shake(msg: bytes, sec: int, outlen_bytes: int) -> bytes:
    """SHAKE128/256 XOF (sec = 128 or 256), squeezing ``outlen_bytes``."""
    return _keccak(_RATE[sec], msg, 0x1F, outlen_bytes)


# --- SP800-185: cSHAKE / KMAC ----------------------------------------------
def cshake(msg: bytes, sec: int, outlen_bytes: int, *, n: bytes = b"", s: bytes = b"") -> bytes:
    """cSHAKE128/256. With N=S="" this is plain SHAKE (domain 0x1F); otherwise the
    cSHAKE domain 0x04 with the bytepad(encode_string(N)||encode_string(S)) prefix."""
    if not n and not s:
        return shake(msg, sec, outlen_bytes)
    rate = _RATE[sec]
    prefix = _bytepad(_encode_string(n) + _encode_string(s), rate)
    return _keccak(rate, prefix + msg, 0x04, outlen_bytes)


def kmac(key: bytes, msg: bytes, sec: int, outlen_bytes: int, *, s: bytes = b"") -> bytes:
    """KMAC128/256 (SP800-185 §4): cSHAKE with N="KMAC", newX =
    bytepad(encode_string(K)) || X || right_encode(L)."""
    rate = _RATE[sec]
    new_x = _bytepad(_encode_string(key), rate) + msg + _right_encode(outlen_bytes * 8)
    return cshake(new_x, sec, outlen_bytes, n=b"KMAC", s=s)


# --- Register word <-> byte packing (little-endian per 32-bit word) --------
def _words_to_le_bytes(words: list[int]) -> bytes:
    return b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in words)


def _le_bytes_to_words(data: bytes) -> list[int]:
    pad = (-len(data)) % 4
    data = data + bytes(pad)
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


def kmac_family_words(
    mode: str,
    sec: int,
    msg_words: list[int],
    outlen_bytes: int,
    *,
    key_words: list[int] | None = None,
    n: bytes = b"",
    s: bytes = b"",
) -> list[int]:
    """Digest words for a KMAC-engine cell, comparable to the STATE share0^share1
    read-back. ``mode`` in {sha3, shake, cshake, kmac}. Word<->byte packing is
    little-endian (register default)."""
    msg = _words_to_le_bytes(msg_words)
    if mode == "sha3":
        out = sha3(msg, sec)
    elif mode == "shake":
        out = shake(msg, sec, outlen_bytes)
    elif mode == "cshake":
        out = cshake(msg, sec, outlen_bytes, n=n, s=s)
    elif mode == "kmac":
        assert key_words is not None, "kmac needs key_words"
        out = kmac(_words_to_le_bytes(key_words), msg, sec, outlen_bytes, s=s)
    else:
        raise ValueError(f"unknown KMAC-family mode {mode}")
    return _le_bytes_to_words(out)


# --- Self-tests (import-time) ----------------------------------------------
# Cross-check the raw Keccak against the Python stdlib for SHA-3 and SHAKE.
_T = b"The quick brown fox jumps over the lazy dog"
assert sha3(b"", 256) == hashlib.sha3_256(b"").digest(), "SHA3-256 empty self-test failed"
assert sha3(_T, 256) == hashlib.sha3_256(_T).digest(), "SHA3-256 self-test failed"
assert sha3(_T, 512) == hashlib.sha3_512(_T).digest(), "SHA3-512 self-test failed"
assert sha3(_T, 384) == hashlib.sha3_384(_T).digest(), "SHA3-384 self-test failed"
assert shake(_T, 128, 32) == hashlib.shake_128(_T).digest(32), "SHAKE128 self-test failed"
assert shake(_T, 256, 64) == hashlib.shake_256(_T).digest(64), "SHAKE256 self-test failed"

# NIST SP800-185 cSHAKE samples (X = 00010203, S = "Email Signature", N="").
_CS_X = bytes.fromhex("00010203")
_CS_S = b"Email Signature"
assert cshake(_CS_X, 128, 32, s=_CS_S) == bytes.fromhex(
    "c1c36925b6409a04f1b504fcbca9d82b4017277cb5ed2b2065fc1d3814d5aaf5"
), "cSHAKE128 SP800-185 Sample 1 self-test failed"
assert cshake(_CS_X, 256, 64, s=_CS_S) == bytes.fromhex(
    "d008828e2b80ac9d2218ffee1d070c48b8e4c87bff32c9699d5b6896eee0edd1"
    "64020e2be0560858d9c00c037e34a96937c561a74c412bb4c746469527281c8c"
), "cSHAKE256 SP800-185 Sample 3 self-test failed"

# NIST SP800-185 KMAC samples. K = 40..5f (32 bytes).
_KM_K = bytes(range(0x40, 0x60))
assert kmac(_KM_K, _CS_X, 128, 32) == bytes.fromhex(
    "e5780b0d3ea6f7d3a429c5706aa43a00fadbd7d49628839e3187243f456ee14e"
), "KMAC128 SP800-185 Sample 1 self-test failed"
assert kmac(_KM_K, _CS_X, 128, 32, s=b"My Tagged Application") == bytes.fromhex(
    "3b1fba963cd8b0b59e8c1a6d71888b7143651af8ba0a7070c0979e2811324aa5"
), "KMAC128 SP800-185 Sample 2 self-test failed"
assert kmac(_KM_K, _CS_X, 256, 64, s=b"My Tagged Application") == bytes.fromhex(
    "20c570c31346f703c9ac36c61c03cb64c3970d0cfc787e9b79599d273a68d2f7"
    "f69d4cc3de9d104a351689f27cf6f5951f0103f33f4f24871024d9c27773a8dd"
), "KMAC256 SP800-185 Sample 4 self-test failed"
