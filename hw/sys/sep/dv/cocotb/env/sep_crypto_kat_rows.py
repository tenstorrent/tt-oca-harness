# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Published known-answer constants that the crypto leaves draw rows from.

Each constant is copied from the publication named in its comment. A leaf seed
picks a row, never the bytes. The goldens that grade a result stay in
``env/sep_aes_golden.py``, ``env/sep_hmac_golden.py`` and
``env/sep_kmac_golden.py``; this module holds input rows only.

Publications:
  * FIPS 197, Advanced Encryption Standard, Appendix C (example vectors).
  * NIST SP 800-38A, Recommendation for Block Cipher Modes of Operation,
    Appendix F (example vectors).
  * NIST SP 800-185 KMAC example values (the KMAC sample key).
  * RFC 4231, Identifiers and Test Vectors for HMAC-SHA-224/256/384/512,
    section 4.
  * RFC 8032, Edwards-Curve Digital Signature Algorithm, section 7.1.
  * RFC 7748, Elliptic Curves for Security, section 6.1.
"""

from __future__ import annotations

# FIPS 197 Appendix C.1, C.2 and C.3: the cipher keys 00 01 02 ... of 16, 24, 32 bytes.
FIPS197_C1_KEY = bytes(range(16))
FIPS197_C2_KEY = bytes(range(24))
FIPS197_C3_KEY = bytes(range(32))

# SP 800-38A F.1.1, F.1.3 and F.1.5: the AES-128, AES-192 and AES-256 keys.
SP800_38A_AES128_KEY = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
SP800_38A_AES192_KEY = bytes.fromhex("8e73b0f7da0e6452c810f32b809079e562f8ead2522c6b7b")
SP800_38A_AES256_KEY = bytes.fromhex(
    "603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4"
)
# SP 800-38A F.1.1: plaintext block #1.
SP800_38A_PT_BLOCK1 = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
# SP 800-38A F.2.1: the CBC initialization vector.
SP800_38A_CBC_IV = bytes(range(16))
# SP 800-38A F.5.1: the CTR initial counter block.
SP800_38A_CTR_COUNTER = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff")

# NIST SP 800-185 KMAC example values: the key 40 41 42 ... 5F (32 bytes).
SP800_185_KMAC_SAMPLE_KEY = bytes(range(0x40, 0x60))

# RFC 8032 section 7.1, TEST 1 and TEST 2: the Ed25519 secret keys.
RFC8032_TEST1_SK = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
RFC8032_TEST2_SK = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
# RFC 7748 section 6.1: the X25519 private key of Alice.
RFC7748_ALICE_SK = bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")

# RFC 4231 sections 4.2 to 4.7: the HMAC keys of test cases 1 to 6, in that order.
RFC4231_KEYS: tuple[bytes, ...] = (
    b"\x0b" * 20,  # 4.2, test case 1
    b"Jefe",  # 4.3, test case 2
    b"\xaa" * 20,  # 4.4, test case 3
    bytes(range(0x01, 0x1A)),  # 4.5, test case 4
    b"\x0c" * 20,  # 4.6, test case 5
    b"\xaa" * 131,  # 4.7, test case 6
)

# Named AES key rows per key length, in the order FIPS 197 then SP 800-38A.
AES_KEY_ROWS: dict[int, tuple[tuple[str, bytes], ...]] = {
    128: (("fips197_c1", FIPS197_C1_KEY), ("sp800_38a_aes128", SP800_38A_AES128_KEY)),
    192: (("fips197_c2", FIPS197_C2_KEY), ("sp800_38a_aes192", SP800_38A_AES192_KEY)),
    256: (("fips197_c3", FIPS197_C3_KEY), ("sp800_38a_aes256", SP800_38A_AES256_KEY)),
}
# The named SP 800-185 KMAC sample key row (32 bytes, usable as a 256-bit key).
KMAC_SAMPLE_KEY_ROW: tuple[str, bytes] = ("sp800_185_sample", SP800_185_KMAC_SAMPLE_KEY)
# The named 32-byte RFC 8032 and RFC 7748 secret key rows.
RFC_SK_ROWS: tuple[tuple[str, bytes], ...] = (
    ("rfc8032_test1_sk", RFC8032_TEST1_SK),
    ("rfc8032_test2_sk", RFC8032_TEST2_SK),
    ("rfc7748_alice_sk", RFC7748_ALICE_SK),
)
# AES IV rows per chaining mode.
AES_IV_ROWS: dict[str, bytes] = {"cbc": SP800_38A_CBC_IV, "ctr": SP800_38A_CTR_COUNTER}
