#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sign a dummy blob with the ML-DSA-87 test key and write the firmware test's vectors.

Writes a C header for abr_mldsa87_verify_test holding the test public key, a second
"wrong" public key, a 5903-byte dummy blob and the signatures the test verifies:

  genuine          ML-DSA.Sign(test key, blob), pure, empty context
  genuine_5900     the same over the first 5900 bytes (a whole-word message)
  ctx_oca          over the blob with context "OCA" (must fail with an empty context)
  prehash          over SHA-512(blob) instead of the blob (must fail)
  ctilde_bad_z     genuine c~, one z coefficient re-encoded at gamma1 - beta
  ctilde_bad_hint  genuine c~, two hint indices made non-increasing
  forged_c0_bad_z  ctilde_bad_z with c~ = 0

Signing is hedged, so the signatures change on every build; the test checks verdicts,
never signature bytes. The z bit the test flips at run time is chosen here, so that
z stays in range and the accelerator computes a non-matching c~'.

Every signature is checked with the signer's own verify, and the malformed ones with
an independent decode of the encoding, before anything is written. The key must be
the committed test key: any other key, or BUILD_TYPE=release, is refused.

Usage: gen_mldsa87_vectors.py --key PEM --out HEADER
"""

import argparse
import hashlib
import os
import sys
import tempfile

# The committed test key's raw public key, and the only directory a key may come from.
TEST_PK_SHA256 = "ee5e14032a8472629fcb875396a9a82b1f86380f088b8cadfcef8405816defff"
KEY_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "..",
        "bootrom",
        "prod",
        "tests",
        "signing_keys",
    )
)

WRONG_KEY_SEED = bytes(range(0xA0, 0xC0))
BLOB_LEN = 5903
BLOB_HEADER = b"OCAH ABR ML-DSA-87 TEST BLOB v1\x00"

# ML-DSA-87 (FIPS 204 Table 1) and the signature layout c~ || z || h.
N, K, L = 256, 8, 7
GAMMA1, BETA, OMEGA = 1 << 19, 120, 75
CTILDE_BYTES, POLYZ_PACKED = 64, 640
Z_OFF = CTILDE_BYTES
H_OFF = CTILDE_BYTES + L * POLYZ_PACKED
SIG_BYTES = H_OFF + OMEGA + K
PK_BYTES = 2592


def fail(msg):
    sys.exit(f"gen_mldsa87_vectors: {msg}")


def load_mldsa():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import mldsa
    except ImportError:
        fail(
            "Python 'cryptography' with ML-DSA (48 or later) is required; "
            "run through the repository's uv 'vp' group"
        )
    return serialization, mldsa


def z_coeffs(sig):
    """Yield every z coefficient (FIPS 204 BitUnpack, gamma1 = 2^19)."""
    body = sig[Z_OFF:H_OFF]
    for i in range(L * N // 2):
        b = body[5 * i : 5 * i + 5]
        yield GAMMA1 - (b[0] | (b[1] << 8) | ((b[2] & 0x0F) << 16))
        yield GAMMA1 - ((b[2] >> 4) | (b[3] << 4) | (b[4] << 12))


def z_out_of_range(sig):
    return any(abs(c) >= GAMMA1 - BETA for c in z_coeffs(sig))


def hint_malformed(sig):
    """FIPS 204 HintBitUnpack (Algorithm 21) failure."""
    h = sig[H_OFF:]
    k = 0
    for i in range(K):
        end = h[OMEGA + i]
        if end < k or end > OMEGA:
            return True
        for j in range(k, end):
            if j > k and h[j] <= h[j - 1]:
                return True
        k = end
    return any(h[j] for j in range(k, OMEGA))


def with_z0(sig, value):
    s = bytearray(sig)
    t = (GAMMA1 - value) & 0xFFFFF
    s[Z_OFF] = t & 0xFF
    s[Z_OFF + 1] = (t >> 8) & 0xFF
    s[Z_OFF + 2] = (s[Z_OFF + 2] & 0xF0) | ((t >> 16) & 0x0F)
    return bytes(s)


def with_bad_hint(sig):
    s = bytearray(sig)
    h = H_OFF
    k = 0
    for i in range(K):
        end = s[h + OMEGA + i]
        if end >= k + 2:
            s[h + k + 1] = s[h + k]
            return bytes(s)
        k = end
    fail("the genuine signature has no polynomial with two hints to reorder")


def choose_z_flip(sig):
    """The first single-bit z flip, in a fixed scan order, that keeps every z in range.

    Such a flip leaves a well-formed signature that the accelerator verifies to a
    non-matching c~'; an out-of-range z is the genuine_ctilde_bad_z case's job.
    """
    for offset in range(Z_OFF + 3 * POLYZ_PACKED + 101, H_OFF):
        for bit in range(8):
            flipped = bytearray(sig)
            flipped[offset] ^= 1 << bit
            if not z_out_of_range(bytes(flipped)):
                return offset, 1 << bit
    fail("no single-bit z flip keeps z in range")


def c_array(name, data):
    lines = [f"static const uint8_t {name}[{len(data)}] = {{"]
    for i in range(0, len(data), 16):
        lines.append("    " + " ".join(f"0x{b:02x}," for b in data[i : i + 16]))
    lines.append("};")
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--key", required=True, help="ML-DSA-87 test private key (PKCS#8 PEM)")
    ap.add_argument("--out", required=True, help="header to write")
    args = ap.parse_args()

    if os.environ.get("BUILD_TYPE", "") == "release":
        fail("refusing to sign with a test key in a release build")
    key_path = os.path.realpath(args.key)
    if os.path.dirname(key_path) != os.path.realpath(KEY_DIR):
        fail(f"{args.key} is not in the test key directory {KEY_DIR}")

    serialization, mldsa = load_mldsa()
    with open(key_path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    if not isinstance(key, mldsa.MLDSA87PrivateKey):
        fail(f"{args.key} is not an ML-DSA-87 key")
    raw = serialization.Encoding.Raw
    raw_pub = serialization.PublicFormat.Raw
    pk = key.public_key().public_bytes(raw, raw_pub)
    if hashlib.sha256(pk).hexdigest() != TEST_PK_SHA256:
        fail(f"{args.key} is not the committed test key (public key SHA-256 differs)")
    pub = key.public_key()

    wrong = mldsa.MLDSA87PrivateKey.from_seed_bytes(WRONG_KEY_SEED)
    wrong_pk = wrong.public_key().public_bytes(raw, raw_pub)

    blob = bytearray(BLOB_LEN)
    blob[: len(BLOB_HEADER)] = BLOB_HEADER
    for i in range(len(BLOB_HEADER), BLOB_LEN):
        blob[i] = (i * 31 + 7) & 0xFF
    blob = bytes(blob)

    genuine = key.sign(blob)
    genuine_5900 = key.sign(blob[:5900])
    ctx_oca = key.sign(blob, b"OCA")
    prehash = key.sign(hashlib.sha512(blob).digest())
    ctilde_bad_z = with_z0(genuine, GAMMA1 - BETA)
    ctilde_bad_hint = with_bad_hint(genuine)
    forged_c0_bad_z = bytes(CTILDE_BYTES) + ctilde_bad_z[CTILDE_BYTES:]

    from cryptography.exceptions import InvalidSignature

    def verifies(sig, msg, ctx=None):
        try:
            pub.verify(sig, msg, ctx)
            return True
        except InvalidSignature:
            return False

    if not verifies(genuine, blob) or not verifies(genuine_5900, blob[:5900]):
        fail("a genuine signature does not verify")
    for name, sig in (
        ("ctx_oca", ctx_oca),
        ("prehash", prehash),
        ("ctilde_bad_z", ctilde_bad_z),
        ("ctilde_bad_hint", ctilde_bad_hint),
        ("forged_c0_bad_z", forged_c0_bad_z),
    ):
        if verifies(sig, blob):
            fail(f"{name} verifies over the blob with an empty context")
    if not verifies(ctx_oca, blob, b"OCA"):
        fail("ctx_oca does not verify with its own context")
    if not (z_out_of_range(ctilde_bad_z) and z_out_of_range(forged_c0_bad_z)):
        fail("the bad-z signatures do not decode as out of range")
    if z_out_of_range(ctilde_bad_hint) or not hint_malformed(ctilde_bad_hint):
        fail("ctilde_bad_hint does not decode as a malformed hint")
    if z_out_of_range(genuine) or hint_malformed(genuine):
        fail("the genuine signature does not decode cleanly")
    for sig in (genuine, genuine_5900, ctx_oca, prehash):
        if len(sig) != SIG_BYTES:
            fail(f"signature is {len(sig)} bytes, expected {SIG_BYTES}")
    if len(pk) != PK_BYTES or len(wrong_pk) != PK_BYTES:
        fail("public key length is not 2592 bytes")

    z_offset, z_mask = choose_z_flip(genuine)

    lines = [
        "/* SPDX-License-Identifier: Apache-2.0 */",
        "/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */",
        "",
        "// Generated by gen_mldsa87_vectors.py at build time. Do not edit.",
        "// TEST-ONLY: signed with the committed ML-DSA-87 test key. Nothing here may",
        "// anchor or appear in a release image.",
        "",
        "#ifndef MLDSA87_VECTORS_H",
        "#define MLDSA87_VECTORS_H",
        "",
        "#include <stdint.h>",
        "",
        f"#define MLDSA87_BLOB_LEN {BLOB_LEN}u",
        "#define MLDSA87_BLOB_LEN_WHOLE_WORDS 5900u",
        f"#define MLDSA87_TAMPERED_Z_OFFSET {z_offset}u",
        f"#define MLDSA87_TAMPERED_Z_MASK 0x{z_mask:02x}u",
        "",
    ]
    for name, data in (
        ("mldsa87_test_pk", pk),
        ("mldsa87_wrong_pk", wrong_pk),
        ("mldsa87_blob", blob),
        ("mldsa87_sig_genuine", genuine),
        ("mldsa87_sig_genuine_5900", genuine_5900),
        ("mldsa87_sig_ctx_oca", ctx_oca),
        ("mldsa87_sig_prehash", prehash),
        ("mldsa87_sig_ctilde_bad_z", ctilde_bad_z),
        ("mldsa87_sig_ctilde_bad_hint", ctilde_bad_hint),
        ("mldsa87_sig_forged_c0_bad_z", forged_c0_bad_z),
    ):
        lines += c_array(name, data)
        lines.append("")
    lines += ["#endif  // MLDSA87_VECTORS_H", ""]

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=".mldsa87_vectors.")
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write("\n".join(lines))
        os.replace(tmp, args.out)
    except BaseException:
        os.unlink(tmp)
        raise


if __name__ == "__main__":
    main()
