#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write or check the committed ML-DSA-87 vectors of abr_mldsa87_verify_test.

mldsa87_vectors.h holds the test public key, a second "wrong" public key, a
5903-byte dummy blob, the signatures the test verifies, and the bytes and bits the
firmware flips at run time:

  genuine          ML-DSA.Sign(test key, blob), pure, empty context
  genuine_5900     the same over the first 5900 bytes (a whole-word message)
  ctx_oca          over the blob with context "OCA" (must fail with an empty context)
  prehash          over SHA-512(blob), empty context (must fail over the blob)
  ctilde_bad_z     genuine c~, one z coefficient re-encoded at gamma1 - beta
  ctilde_bad_hint  genuine c~, two hint indices made non-increasing
  forged_c0_bad_z  ctilde_bad_z with c~ = 0

The header is committed. Signing uses the 'cryptography' package (hedged), so a
new --out run writes different signature bytes; the test checks verdicts only.

  --out HEADER    sign and write the header (run by hand, then commit it), and
                  print its SHA-256 for ABR_MLDSA87_VECTORS_SHA256 in fw.mk
  --check HEADER  parse the committed header and check it with 'cryptography'
                  verify only, and print its SHA-256

Run --check by hand after any change to the header or to this script. The
firmware build does not run this script: it checks only the header's SHA-256
against ABR_MLDSA87_VECTORS_SHA256 in fw.mk, with the standard library.

The check holds every fact the firmware relies on: the header is exactly what this
script renders from its own parsed content; the keys and blob are the committed
ones; the genuine signatures verify; ctx_oca verifies with context "OCA" only;
prehash verifies over SHA-512(blob) only; the malformed signatures decode as
malformed; each exact mutated input of the tampered, wrong-key, context and prehash
cases does not verify; and each offset and mask is in range and non-zero.

The key must be the committed test key: any other key, or BUILD_TYPE=release, is
refused.

Usage: gen_mldsa87_vectors.py --key PEM (--out HEADER | --check HEADER)
"""

import argparse
import hashlib
import os
import re
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
WHOLE_WORDS_LEN = 5900
BLOB_HEADER = b"OCAH ABR ML-DSA-87 TEST BLOB v1\x00"
CTX_OCA = b"OCA"
# The bits the firmware flips in the blob and in c~ for its tampered cases.
TAMPERED_BLOB_OFFSET, TAMPERED_BLOB_MASK = BLOB_LEN // 2, 0x01
TAMPERED_CTILDE_OFFSET, TAMPERED_CTILDE_MASK = 0, 0x01

# ML-DSA-87 (FIPS 204 Table 1) and the signature layout c~ || z || h.
N, K, L = 256, 8, 7
GAMMA1, BETA, OMEGA = 1 << 19, 120, 75
CTILDE_BYTES, POLYZ_PACKED = 64, 640
Z_OFF = CTILDE_BYTES
H_OFF = CTILDE_BYTES + L * POLYZ_PACKED
SIG_BYTES = H_OFF + OMEGA + K
PK_BYTES = 2592

DEFINES = (
    "TAMPERED_Z_OFFSET",
    "TAMPERED_Z_MASK",
    "TAMPERED_BLOB_OFFSET",
    "TAMPERED_BLOB_MASK",
    "TAMPERED_CTILDE_OFFSET",
    "TAMPERED_CTILDE_MASK",
)
ARRAYS = (
    ("mldsa87_test_pk", PK_BYTES),
    ("mldsa87_wrong_pk", PK_BYTES),
    ("mldsa87_blob", BLOB_LEN),
    ("mldsa87_sig_genuine", SIG_BYTES),
    ("mldsa87_sig_genuine_5900", SIG_BYTES),
    ("mldsa87_sig_ctx_oca", SIG_BYTES),
    ("mldsa87_sig_prehash", SIG_BYTES),
    ("mldsa87_sig_ctilde_bad_z", SIG_BYTES),
    ("mldsa87_sig_ctilde_bad_hint", SIG_BYTES),
    ("mldsa87_sig_forged_c0_bad_z", SIG_BYTES),
)


def fail(msg):
    sys.exit(f"gen_mldsa87_vectors: {msg}")


def load_mldsa():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import mldsa
    except ImportError:
        fail(
            "Python 'cryptography' with ML-DSA (48 or later) is required; "
            "run through the repository's uv 'vp' group"
        )
    return serialization, mldsa, InvalidSignature


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


def make_blob():
    blob = bytearray(BLOB_LEN)
    blob[: len(BLOB_HEADER)] = BLOB_HEADER
    for i in range(len(BLOB_HEADER), BLOB_LEN):
        blob[i] = (i * 31 + 7) & 0xFF
    return bytes(blob)


def c_array(name, data):
    lines = [f"static const uint8_t {name}[{len(data)}] = {{"]
    for i in range(0, len(data), 16):
        lines.append("    " + " ".join(f"0x{b:02x}," for b in data[i : i + 16]))
    lines.append("};")
    return lines


def render(defines, arrays):
    """The header text for the given defines and arrays (name -> bytes)."""
    lines = [
        "/* SPDX-License-Identifier: Apache-2.0 */",
        "/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */",
        "",
        "// Written by gen_mldsa87_vectors.py --out and checked by its --check. The",
        "// firmware build checks its SHA-256 against fw.mk. Do not edit by hand.",
        "// TEST-ONLY: signed with the committed ML-DSA-87 test key. Nothing here may",
        "// anchor or appear in a release image.",
        "//",
        "// mldsa87_sig_genuine and mldsa87_sig_genuine_5900 verify over the blob and",
        "// its first 5900 bytes; mldsa87_sig_ctx_oca verifies over the blob with",
        '// context "OCA" only; mldsa87_sig_prehash verifies over SHA-512(blob) only.',
        "// The TAMPERED_* offsets and masks name the byte and bits the firmware flips.",
        "",
        "#ifndef MLDSA87_VECTORS_H",
        "#define MLDSA87_VECTORS_H",
        "",
        "#include <stdint.h>",
        "",
        f"#define MLDSA87_BLOB_LEN {BLOB_LEN}u",
        f"#define MLDSA87_BLOB_LEN_WHOLE_WORDS {WHOLE_WORDS_LEN}u",
    ]
    for name in DEFINES:
        value = defines[name]
        text = f"0x{value:02x}u" if name.endswith("_MASK") else f"{value}u"
        lines.append(f"#define MLDSA87_{name} {text}")
    lines.append("")
    for name, _ in ARRAYS:
        lines += c_array(name, arrays[name])
        lines.append("")
    lines += ["#endif // MLDSA87_VECTORS_H", ""]
    return "\n".join(lines)


def parse(text):
    """(defines, arrays) from a header in the form render() writes."""
    defines = {}
    for name in DEFINES:
        m = re.search(rf"^#define MLDSA87_{name} (0x[0-9a-f]+|[0-9]+)u$", text, re.M)
        if not m:
            fail(f"check: the header has no define MLDSA87_{name}")
        defines[name] = int(m.group(1), 0)
    arrays = {}
    for name, size in ARRAYS:
        m = re.search(
            rf"^static const uint8_t {name}\[([0-9]+)\] = \{{\n(.*?)^\}};$", text, re.M | re.S
        )
        if not m:
            fail(f"check: the header has no array {name}")
        data = bytes(int(b, 16) for b in re.findall(r"0x([0-9a-f]{2}),", m.group(2)))
        if int(m.group(1)) != size or len(data) != size:
            fail(f"check: {name} holds {len(data)} bytes, expected {size}")
        arrays[name] = data
    return defines, arrays


def load_test_key(path, serialization, mldsa):
    if os.environ.get("BUILD_TYPE", "") == "release":
        fail("refusing to use a test key in a release build")
    key_path = os.path.realpath(path)
    if os.path.dirname(key_path) != os.path.realpath(KEY_DIR):
        fail(f"{path} is not in the test key directory {KEY_DIR}")
    with open(key_path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    if not isinstance(key, mldsa.MLDSA87PrivateKey):
        fail(f"{path} is not an ML-DSA-87 key")
    pk = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if hashlib.sha256(pk).hexdigest() != TEST_PK_SHA256:
        fail(f"{path} is not the committed test key (public key SHA-256 differs)")
    return key


def check(text, key, serialization, mldsa, InvalidSignature):
    """Fail on any fact of the header that does not hold. Verify only; no signing."""

    def bad(msg):
        fail(f"check: {msg}")

    defines, arrays = parse(text)
    if render(defines, arrays) != text:
        bad("the header is not exactly what --out renders from its own content")

    raw = serialization.Encoding.Raw
    raw_pub = serialization.PublicFormat.Raw
    pub = key.public_key()
    wrong_pub = mldsa.MLDSA87PrivateKey.from_seed_bytes(WRONG_KEY_SEED).public_key()
    blob = make_blob()
    if arrays["mldsa87_test_pk"] != pub.public_bytes(raw, raw_pub):
        bad("mldsa87_test_pk is not the committed test key's public key")
    if arrays["mldsa87_wrong_pk"] != wrong_pub.public_bytes(raw, raw_pub):
        bad("mldsa87_wrong_pk is not the wrong key's public key")
    if arrays["mldsa87_blob"] != blob:
        bad("mldsa87_blob is not the test blob")

    def verifies(sig, msg, ctx=None, key_pub=pub):
        try:
            key_pub.verify(sig, msg, ctx)
            return True
        except InvalidSignature:
            return False

    genuine = arrays["mldsa87_sig_genuine"]
    genuine_5900 = arrays["mldsa87_sig_genuine_5900"]
    ctx_oca = arrays["mldsa87_sig_ctx_oca"]
    prehash = arrays["mldsa87_sig_prehash"]
    ctilde_bad_z = arrays["mldsa87_sig_ctilde_bad_z"]
    ctilde_bad_hint = arrays["mldsa87_sig_ctilde_bad_hint"]
    forged_c0_bad_z = arrays["mldsa87_sig_forged_c0_bad_z"]
    sha512_blob = hashlib.sha512(blob).digest()

    if not verifies(genuine, blob):
        bad("mldsa87_sig_genuine does not verify over the blob")
    if not verifies(genuine_5900, blob[:WHOLE_WORDS_LEN]):
        bad("mldsa87_sig_genuine_5900 does not verify over the first 5900 bytes")
    if not verifies(ctx_oca, blob, CTX_OCA):
        bad('mldsa87_sig_ctx_oca does not verify over the blob with context "OCA"')
    if not verifies(prehash, sha512_blob):
        bad("mldsa87_sig_prehash does not verify over SHA-512(blob)")
    if z_out_of_range(genuine) or hint_malformed(genuine):
        bad("mldsa87_sig_genuine does not decode cleanly")

    if ctilde_bad_z != with_z0(genuine, GAMMA1 - BETA) or not z_out_of_range(ctilde_bad_z):
        bad("mldsa87_sig_ctilde_bad_z is not the genuine signature with z[0] = gamma1 - beta")
    if ctilde_bad_hint != with_bad_hint(genuine) or not hint_malformed(ctilde_bad_hint):
        bad("mldsa87_sig_ctilde_bad_hint is not the genuine signature with a malformed hint")
    if z_out_of_range(ctilde_bad_hint):
        bad("mldsa87_sig_ctilde_bad_hint has z out of range")
    if forged_c0_bad_z != bytes(CTILDE_BYTES) + ctilde_bad_z[CTILDE_BYTES:]:
        bad("mldsa87_sig_forged_c0_bad_z is not ctilde_bad_z with c~ = 0")

    for name, lo, hi in (
        ("TAMPERED_BLOB", 0, BLOB_LEN),
        ("TAMPERED_Z", Z_OFF, H_OFF),
        ("TAMPERED_CTILDE", 0, CTILDE_BYTES),
    ):
        offset, mask = defines[f"{name}_OFFSET"], defines[f"{name}_MASK"]
        if not lo <= offset < hi:
            bad(f"MLDSA87_{name}_OFFSET {offset} is outside [{lo}, {hi})")
        if not 0 < mask <= 0xFF:
            bad(f"MLDSA87_{name}_MASK 0x{mask:x} is not a non-zero byte mask")

    tampered_blob = bytearray(blob)
    tampered_blob[defines["TAMPERED_BLOB_OFFSET"]] ^= defines["TAMPERED_BLOB_MASK"]
    tampered_z = bytearray(genuine)
    tampered_z[defines["TAMPERED_Z_OFFSET"]] ^= defines["TAMPERED_Z_MASK"]
    tampered_ctilde = bytearray(genuine)
    tampered_ctilde[defines["TAMPERED_CTILDE_OFFSET"]] ^= defines["TAMPERED_CTILDE_MASK"]
    if z_out_of_range(bytes(tampered_z)):
        bad("the tampered_z case flip puts z out of range")

    # The exact inputs of the firmware's reject cases, each verified over its
    # message with an empty context.
    for name, key_pub, sig, msg in (
        ("tampered_blob", pub, genuine, bytes(tampered_blob)),
        ("tampered_z", pub, bytes(tampered_z), blob),
        ("tampered_ctilde", pub, bytes(tampered_ctilde), blob),
        ("wrong_key", wrong_pub, genuine, blob),
        ("context_oca", pub, ctx_oca, blob),
        ("prehash", pub, prehash, blob),
        ("genuine_ctilde_bad_z", pub, ctilde_bad_z, blob),
        ("genuine_ctilde_bad_hint", pub, ctilde_bad_hint, blob),
        ("forged_c0_bad_z", pub, forged_c0_bad_z, blob),
    ):
        if verifies(sig, msg, key_pub=key_pub):
            bad(f"the {name} case input verifies")


def write(path, text):
    out_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=".mldsa87_vectors.")
    try:
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--key", required=True, help="ML-DSA-87 test private key (PKCS#8 PEM)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--out", help="sign and write this header")
    mode.add_argument("--check", help="check this committed header")
    args = ap.parse_args()

    serialization, mldsa, InvalidSignature = load_mldsa()
    key = load_test_key(args.key, serialization, mldsa)
    raw = serialization.Encoding.Raw
    raw_pub = serialization.PublicFormat.Raw

    if args.check:
        with open(args.check, encoding="ascii") as f:
            text = f.read()
        check(text, key, serialization, mldsa, InvalidSignature)
        digest = hashlib.sha256(text.encode("ascii")).hexdigest()
        print(f"gen_mldsa87_vectors: {args.check} checks out, sha256 {digest}")
        return

    blob = make_blob()
    genuine = key.sign(blob)
    ctilde_bad_z = with_z0(genuine, GAMMA1 - BETA)
    z_offset, z_mask = choose_z_flip(genuine)
    wrong = mldsa.MLDSA87PrivateKey.from_seed_bytes(WRONG_KEY_SEED)
    arrays = {
        "mldsa87_test_pk": key.public_key().public_bytes(raw, raw_pub),
        "mldsa87_wrong_pk": wrong.public_key().public_bytes(raw, raw_pub),
        "mldsa87_blob": blob,
        "mldsa87_sig_genuine": genuine,
        "mldsa87_sig_genuine_5900": key.sign(blob[:WHOLE_WORDS_LEN]),
        "mldsa87_sig_ctx_oca": key.sign(blob, CTX_OCA),
        "mldsa87_sig_prehash": key.sign(hashlib.sha512(blob).digest()),
        "mldsa87_sig_ctilde_bad_z": ctilde_bad_z,
        "mldsa87_sig_ctilde_bad_hint": with_bad_hint(genuine),
        "mldsa87_sig_forged_c0_bad_z": bytes(CTILDE_BYTES) + ctilde_bad_z[CTILDE_BYTES:],
    }
    defines = {
        "TAMPERED_Z_OFFSET": z_offset,
        "TAMPERED_Z_MASK": z_mask,
        "TAMPERED_BLOB_OFFSET": TAMPERED_BLOB_OFFSET,
        "TAMPERED_BLOB_MASK": TAMPERED_BLOB_MASK,
        "TAMPERED_CTILDE_OFFSET": TAMPERED_CTILDE_OFFSET,
        "TAMPERED_CTILDE_MASK": TAMPERED_CTILDE_MASK,
    }
    text = render(defines, arrays)
    check(text, key, serialization, mldsa, InvalidSignature)
    write(args.out, text)
    digest = hashlib.sha256(text.encode("ascii")).hexdigest()
    print(f"gen_mldsa87_vectors: wrote {args.out}, sha256 {digest}")


if __name__ == "__main__":
    main()
