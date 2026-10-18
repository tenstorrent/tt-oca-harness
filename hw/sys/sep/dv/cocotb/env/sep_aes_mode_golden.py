# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Pure-Python AES mode golden: CFB-128 and OFB (NIST SP 800-38A) and GCM (NIST SP 800-38D).

The block cipher is the FIPS-197 cipher of ``env/sep_aes_golden.py``; this module adds the
modes only and is not derived from DUT output. ``python3 sep_aes_mode_golden.py`` checks every
function against the published vectors: SP 800-38A F.3.13-F.3.18 (CFB128-AES128/192/256,
encrypt and decrypt), F.4.1-F.4.6 (OFB-AES128/192/256) and the GCM test cases of the GCM
specification submitted to NIST for SP 800-38D (McGrew and Viega, Appendix B).

Byte strings in, byte strings out. ``words_to_bytes`` and ``bytes_to_words`` apply the
OpenTitan AES register packing (little-endian words, byte 0 in bits [7:0]) that KEY_SHARE,
IV, DATA_IN and DATA_OUT share.

GCM here is the SP 800-38D case with a 96-bit IV and a 128-bit tag: J0 = IV || 0^31 || 1,
the text uses GCTR from inc32(J0), and the tag is GCTR(J0, S) with
S = GHASH_H(A || 0^v || C || 0^u || [len(A)]_64 || [len(C)]_64). Decryption returns the
plaintext and the tag that the receiver computes over the ciphertext; the caller compares.
"""

from __future__ import annotations

try:
    from env.sep_aes_golden import aes_encrypt_block
except ModuleNotFoundError:  # run as a script from env/ (run_golden_selftests.py)
    from sep_aes_golden import aes_encrypt_block

__all__ = [
    "bytes_to_words",
    "cfb_decrypt",
    "cfb_encrypt",
    "gcm_decrypt",
    "gcm_encrypt",
    "gcm_j0",
    "gcm_len_block",
    "ghash",
    "ofb_crypt",
    "words_to_bytes",
]

_BLK = 16
_MASK128 = (1 << 128) - 1
# SP 800-38D 6.3: R = 11100001 || 0^120.
_GCM_R = 0xE1 << 120


def words_to_bytes(words: list[int]) -> bytes:
    """Register words to a byte string, little-endian per 32-bit word."""
    return b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in words)


def bytes_to_words(data: bytes) -> list[int]:
    """Byte string (length a multiple of 4) to register words, little-endian per word."""
    assert len(data) % 4 == 0, "word packing needs a multiple of 4 bytes"
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b, strict=False))


def _check_key_iv(key: bytes, iv: bytes, iv_len: int) -> None:
    assert len(key) in (16, 24, 32), "AES key must be 16, 24 or 32 bytes"
    assert len(iv) == iv_len, f"IV must be {iv_len} bytes"


# --- CFB-128 and OFB (SP 800-38A 6.3, 6.4) ----------------------------------
def cfb_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """CFB with s = 128: C_j = P_j XOR E(C_{j-1}), C_0 = IV. A short last segment is
    XORed with the leading bytes of its keystream block."""
    _check_key_iv(key, iv, _BLK)
    out, prev = b"", iv
    for i in range(0, len(data), _BLK):
        seg = data[i : i + _BLK]
        c = _xor(seg, aes_encrypt_block(key, prev))
        out += c
        prev = c
    return out


def cfb_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """CFB-128 inverse: P_j = C_j XOR E(C_{j-1}), C_0 = IV."""
    _check_key_iv(key, iv, _BLK)
    out, prev = b"", iv
    for i in range(0, len(data), _BLK):
        seg = data[i : i + _BLK]
        out += _xor(seg, aes_encrypt_block(key, prev))
        prev = seg
    return out


def ofb_crypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """OFB: O_j = E(O_{j-1}), O_0 = IV; output = input XOR O_j. Encrypt and decrypt
    are the same function."""
    _check_key_iv(key, iv, _BLK)
    out, o = b"", iv
    for i in range(0, len(data), _BLK):
        o = aes_encrypt_block(key, o)
        out += _xor(data[i : i + _BLK], o)
    return out


# --- GCM (SP 800-38D) --------------------------------------------------------
def _gf_mult(x: int, y: int) -> int:
    """X * Y in GF(2^128), SP 800-38D 6.3 Algorithm 1 (bit 0 is the MSB of the block)."""
    z, v = 0, y
    for i in range(127, -1, -1):
        if (x >> i) & 1:
            z ^= v
        v = (v >> 1) ^ _GCM_R if v & 1 else v >> 1
    return z


def ghash(h: bytes, data: bytes) -> bytes:
    """GHASH_H(X), SP 800-38D 6.4. ``data`` length is a multiple of 16."""
    assert len(h) == _BLK and len(data) % _BLK == 0, "GHASH needs 16-byte blocks"
    hk = int.from_bytes(h, "big")
    y = 0
    for i in range(0, len(data), _BLK):
        y = _gf_mult(y ^ int.from_bytes(data[i : i + _BLK], "big"), hk)
    return y.to_bytes(_BLK, "big")


def _inc32(block: bytes) -> bytes:
    """inc_32: add 1 modulo 2^32 to the rightmost 32 bits, SP 800-38D 6.2."""
    ctr = (int.from_bytes(block[12:], "big") + 1) & 0xFFFF_FFFF
    return block[:12] + ctr.to_bytes(4, "big")


def _gctr(key: bytes, icb: bytes, data: bytes) -> bytes:
    """GCTR_K(ICB, X), SP 800-38D 6.5."""
    out, cb = b"", icb
    for i in range(0, len(data), _BLK):
        seg = data[i : i + _BLK]
        out += _xor(seg, aes_encrypt_block(key, cb))
        cb = _inc32(cb)
    return out


def _pad16(data: bytes) -> bytes:
    return data + bytes(-len(data) % _BLK)


def gcm_j0(iv: bytes) -> bytes:
    """Pre-counter block J0 = IV || 0^31 || 1 for a 96-bit IV, SP 800-38D 7.1 step 2."""
    assert len(iv) == 12, "this golden supports the 96-bit GCM IV only"
    return iv + b"\x00\x00\x00\x01"


def gcm_len_block(aad_len: int, text_len: int) -> bytes:
    """[len(A)]_64 || [len(C)]_64, lengths in bits, big-endian, SP 800-38D 7.1 step 5."""
    return (8 * aad_len).to_bytes(8, "big") + (8 * text_len).to_bytes(8, "big")


def _gcm_tag(key: bytes, j0: bytes, aad: bytes, ct: bytes) -> bytes:
    h = aes_encrypt_block(key, bytes(_BLK))
    s = ghash(h, _pad16(aad) + _pad16(ct) + gcm_len_block(len(aad), len(ct)))
    return _gctr(key, j0, s)


def gcm_encrypt(key: bytes, iv: bytes, aad: bytes, pt: bytes) -> tuple[bytes, bytes]:
    """GCM-AE_K(IV, P, A), SP 800-38D 7.1. Returns (C, T) with a 128-bit T."""
    _check_key_iv(key, iv, 12)
    j0 = gcm_j0(iv)
    ct = _gctr(key, _inc32(j0), pt)
    return ct, _gcm_tag(key, j0, aad, ct)


def gcm_decrypt(key: bytes, iv: bytes, aad: bytes, ct: bytes) -> tuple[bytes, bytes]:
    """GCM-AD_K(IV, C, A), SP 800-38D 7.2, without the tag compare. Returns (P, T'),
    where T' is the tag computed over A and C."""
    _check_key_iv(key, iv, 12)
    j0 = gcm_j0(iv)
    pt = _gctr(key, _inc32(j0), ct)
    return pt, _gcm_tag(key, j0, aad, ct)


# --- Self-test against the published vectors --------------------------------
_SP38A_KEYS = {
    128: "2b7e151628aed2a6abf7158809cf4f3c",
    192: "8e73b0f7da0e6452c810f32b809079e562f8ead2522c6b7b",
    256: "603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4",
}
_SP38A_IV = "000102030405060708090a0b0c0d0e0f"
_SP38A_PT = (
    "6bc1bee22e409f96e93d7e117393172a"
    "ae2d8a571e03ac9c9eb76fac45af8e51"
    "30c81c46a35ce411e5fbc1191a0a52ef"
    "f69f2445df4f9b17ad2b417be66c3710"
)
# SP 800-38A F.3.13/F.3.14 (128), F.3.15/F.3.16 (192), F.3.17/F.3.18 (256).
_SP38A_CFB128 = {
    128: "3b3fd92eb72dad20333449f8e83cfb4a"
    "c8a64537a0b3a93fcde3cdad9f1ce58b"
    "26751f67a3cbb140b1808cf187a4f4df"
    "c04b05357c5d1c0eeac4c66f9ff7f2e6",
    192: "cdc80d6fddf18cab34c25909c99a4174"
    "67ce7f7f81173621961a2b70171d3d7a"
    "2e1e8a1dd59b88b1c8e60fed1efac4c9"
    "c05f9f9ca9834fa042ae8fba584b09ff",
    256: "dc7e84bfda79164b7ecd8486985d3860"
    "39ffed143b28b1c832113c6331e5407b"
    "df10132415e54b92a13ed0a8267ae2f9"
    "75a385741ab9cef82031623d55b1e471",
}
# SP 800-38A F.4.1/F.4.2 (128), F.4.3/F.4.4 (192), F.4.5/F.4.6 (256).
_SP38A_OFB = {
    128: "3b3fd92eb72dad20333449f8e83cfb4a"
    "7789508d16918f03f53c52dac54ed825"
    "9740051e9c5fecf64344f7a82260edcc"
    "304c6528f659c77866a510d9c1d6ae5e",
    192: "cdc80d6fddf18cab34c25909c99a4174"
    "fcc28b8d4c63837c09e81700c1100401"
    "8d9a9aeac0f6596f559c6d4daf59a5f2"
    "6d9f200857ca6c3e9cac524bd9acc92a",
    256: "dc7e84bfda79164b7ecd8486985d3860"
    "4febdc6740d20b3ac88f6ad82a4fb08d"
    "71ab47a086e86eedf39d1c5bba97c408"
    "0126141d67f37be8538f5a8be740e484",
}

# GCM test cases (McGrew and Viega, "The Galois/Counter Mode of Operation",
# Appendix B, the test vectors of the GCM submission for SP 800-38D):
# (case, key, iv, aad, pt, ct, tag). Only the 96-bit-IV cases.
_GCM_K1 = "feffe9928665731c6d6a8f9467308308"
_GCM_IV = "cafebabefacedbaddecaf888"
_GCM_AAD = "feedfacedeadbeeffeedfacedeadbeefabaddad2"
_GCM_PT64 = (
    "d9313225f88406e5a55909c5aff5269a"
    "86a7a9531534f7da2e4c303d8a318a72"
    "1c3c0c95956809532fcf0e2449a6b525"
    "b16aedf5aa0de657ba637b391aafd255"
)
_GCM_PT60 = _GCM_PT64[: 60 * 2]
_GCM_CASES = (
    ("1", "00" * 16, "00" * 12, "", "", "", "58e2fccefa7e3061367f1d57a4e7455a"),
    (
        "2",
        "00" * 16,
        "00" * 12,
        "",
        "00" * 16,
        "0388dace60b6a392f328c2b971b2fe78",
        "ab6e47d42cec13bdf53a67b21257bddf",
    ),
    (
        "3",
        _GCM_K1,
        _GCM_IV,
        "",
        _GCM_PT64,
        "42831ec2217774244b7221b784d0d49c"
        "e3aa212f2c02a4e035c17e2329aca12e"
        "21d514b25466931c7d8f6a5aac84aa05"
        "1ba30b396a0aac973d58e091473f5985",
        "4d5c2af327cd64a62cf35abd2ba6fab4",
    ),
    (
        "4",
        _GCM_K1,
        _GCM_IV,
        _GCM_AAD,
        _GCM_PT60,
        "42831ec2217774244b7221b784d0d49c"
        "e3aa212f2c02a4e035c17e2329aca12e"
        "21d514b25466931c7d8f6a5aac84aa05"
        "1ba30b396a0aac973d58e091",
        "5bc94fbc3221a5db94fae95ae7121a47",
    ),
    ("7", "00" * 24, "00" * 12, "", "", "", "cd33b28ac773f74ba00ed1f312572435"),
    (
        "10",
        _GCM_K1 + "feffe9928665731c",
        _GCM_IV,
        _GCM_AAD,
        _GCM_PT60,
        "3980ca0b3c00e841eb06fac4872a2757"
        "859e1ceaa6efd984628593b40ca1e19c"
        "7d773d00c144c525ac619d18c84a3f47"
        "18e2448b2fe324d9ccda2710",
        "2519498e80f1478f37ba55bd6d27618c",
    ),
    ("13", "00" * 32, "00" * 12, "", "", "", "530f8afbc74536b9a963b4f1c4cb738b"),
    (
        "14",
        "00" * 32,
        "00" * 12,
        "",
        "00" * 16,
        "cea7403d4d606b6e074ec5d3baf39d18",
        "d0d1c8a799996bf0265b98b5d48ab919",
    ),
    (
        "16",
        _GCM_K1 * 2,
        _GCM_IV,
        _GCM_AAD,
        _GCM_PT60,
        "522dc1f099567d07f47f37a32a84427d"
        "643a8cdcbfe5c0c97598a2bd2555d1aa"
        "8cb08e48590dbb3da7b08b1056828838"
        "c5f61e6393ba7a0abcc9f662",
        "76fc6ece0f4e1768cddf8853bb2d551b",
    ),
)


def _selftest() -> list[str]:
    """Check every mode function against the published vectors. Returns one line per row."""
    lines: list[str] = []
    iv = bytes.fromhex(_SP38A_IV)
    pt = bytes.fromhex(_SP38A_PT)
    for bits in (128, 192, 256):
        key = bytes.fromhex(_SP38A_KEYS[bits])
        cfb = bytes.fromhex(_SP38A_CFB128[bits])
        ofb = bytes.fromhex(_SP38A_OFB[bits])
        assert cfb_encrypt(key, iv, pt) == cfb, f"CFB128-AES{bits}.Encrypt mismatch"
        assert cfb_decrypt(key, iv, cfb) == pt, f"CFB128-AES{bits}.Decrypt mismatch"
        assert ofb_crypt(key, iv, pt) == ofb, f"OFB-AES{bits}.Encrypt mismatch"
        assert ofb_crypt(key, iv, ofb) == pt, f"OFB-AES{bits}.Decrypt mismatch"
        lines.append(f"PASS SP800-38A CFB128-AES{bits} encrypt+decrypt (4 blocks)")
        lines.append(f"PASS SP800-38A OFB-AES{bits} encrypt+decrypt (4 blocks)")
    for case, k, v, a, p, c, t in _GCM_CASES:
        key, iv96, aad = bytes.fromhex(k), bytes.fromhex(v), bytes.fromhex(a)
        ptb, ctb, tag = bytes.fromhex(p), bytes.fromhex(c), bytes.fromhex(t)
        got_c, got_t = gcm_encrypt(key, iv96, aad, ptb)
        assert got_c == ctb, f"GCM test case {case} ciphertext mismatch"
        assert got_t == tag, f"GCM test case {case} tag mismatch"
        got_p, got_t2 = gcm_decrypt(key, iv96, aad, ctb)
        assert got_p == ptb, f"GCM test case {case} decrypt plaintext mismatch"
        assert got_t2 == tag, f"GCM test case {case} decrypt tag mismatch"
        lines.append(
            f"PASS GCM test case {case} AES-{8 * len(key)} aad={len(aad)}B text={len(ptb)}B "
            "encrypt+decrypt, tag"
        )
    # Register packing round trip.
    assert bytes_to_words(words_to_bytes([0x0302_0100, 0xFFEE_DDCC])) == [
        0x0302_0100,
        0xFFEE_DDCC,
    ], "register word packing round trip"
    assert words_to_bytes([0x0302_0100]) == b"\x00\x01\x02\x03", "register word byte order"
    return lines


if __name__ == "__main__":
    for line in _selftest():
        print(line)
    print("SEP AES MODE GOLDEN SELFTEST PASS (SP 800-38A CFB128/OFB, SP 800-38D GCM)")
