#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate the ABR known-answer headers from NIST ACVP-Server vectors.

  python3 gen_abr_nist_vectors.py           -> abr_nist_vectors.h      (ML-DSA-87)
  python3 gen_abr_nist_vectors.py --mlkem   -> abr_nist_kem_vectors.h  (ML-KEM-1024)

Each algorithm writes its own header and neither mode touches the other's file.
That separation is deliberate: the upstream ACVP-Server periodically re-rolls its
projection files, so a plain re-run does NOT reproduce a header byte-for-byte.
The vectors committed here are a snapshot the DUT has been graded against, and
regenerating one algorithm must not silently swap the other's expected values
underneath a passing test.

The golden inputs/outputs are the official NIST ACVP "internalProjection" files
(they contain both inputs and expected outputs). Download them first:

  base=https://raw.githubusercontent.com/usnistgov/ACVP-Server/master/gen-val/json-files
  curl -sSL -o $TMPDIR/mldsa_keygen.json $base/ML-DSA-keyGen-FIPS204/internalProjection.json
  curl -sSL -o $TMPDIR/mldsa_siggen.json $base/ML-DSA-sigGen-FIPS204/internalProjection.json
  curl -sSL -o $TMPDIR/mldsa_sigver.json $base/ML-DSA-sigVer-FIPS204/internalProjection.json
  curl -sSL -o $TMPDIR/mlkem_keygen.json $base/ML-KEM-keyGen-FIPS203/internalProjection.json
  curl -sSL -o $TMPDIR/mlkem_encdec.json $base/ML-KEM-encapDecap-FIPS203/internalProjection.json

Word packing, from the register description -- abr_reg.rdl, which is the
specification for this block, not a view of the implementation.

Width: every ABR key, signature and ciphertext window is declared memwidth = 32
("648 32-bit registers storing the public key", and likewise for
MLDSA_SIGNATURE, MLDSA_PRIVKEY_IN/OUT and the MLKEM_* windows), so byte b of an
ACVP string lands in word b/4.

Byte order within a word: MLDSA_MSG_STROBE is described as a "Byte enable strobe
for each 32 bits of message" whose valid values are 4'b0000, 4'b0001, 4'b0011,
4'b0111 and 4'b1111, set "for each valid byte in the last msg data, starting
from LSB". A trailing partial word is therefore strobed from the low byte up,
which places earlier message bytes in the lower byte lanes -- little-endian
packing. The block-level lsb0 = true pins the bit numbering those lanes are
counted in. Note the scope: the description states this for the message window,
and the same packing is applied to the key, signature and ciphertext windows,
which is an inference from one block-wide convention rather than a separate
statement about each window.

Corroborated, not merely asserted: a byte-order error could not survive the
compares these vectors feed -- 1157 signature words against a deterministic ACVP
value, and the full ek/dk/ciphertext windows on the ML-KEM side.

Outputs are FIPS-204 layout (PUBKEY=rho||t1, SIGNATURE=c~||z||h). Default
signing computes mu internally from the raw message with an empty context, so
the ACVP "message" maps straight to MLDSA_MSG.

The ML-KEM decaps set carries both a "valid decapsulation" case and a "modified
ciphertext" one: FIPS-203 implicit rejection means a bad ciphertext yields a
DIFFERENT shared key rather than an error, so the rejecting case has its own
expected K and is graded by value, not by an absence of error.
"""

import json
import os
import sys

# The vectors are read from $TMPDIR, which is where the curl lines above put
# them; /tmp is not assumed to be writable or shared.
_TMP = os.environ.get("TMPDIR", "/tmp")

PARAM = "ML-DSA-87"
KG = os.path.join(_TMP, "mldsa_keygen.json")
SG = os.path.join(_TMP, "mldsa_siggen.json")
SV = os.path.join(_TMP, "mldsa_sigver.json")
OUT = os.path.join(os.path.dirname(__file__), "abr_nist_vectors.h")

KEM_PARAM = "ML-KEM-1024"
KEM_KG = os.path.join(_TMP, "mlkem_keygen.json")
KEM_ED = os.path.join(_TMP, "mlkem_encdec.json")
KEM_OUT = os.path.join(os.path.dirname(__file__), "abr_nist_kem_vectors.h")


def hex_to_words(h):
    """ACVP hex byte string -> (list[uint32] LE, byte_len)."""
    raw = bytes.fromhex(h)
    n = len(raw)
    pad = raw + b"\x00" * ((-n) % 4)
    words = [int.from_bytes(pad[i : i + 4], "little") for i in range(0, len(pad), 4)]
    return words, n


def find_group(path, tgid=None):
    d = json.load(open(path))
    for g in d["testGroups"]:
        if g.get("parameterSet") == PARAM and (tgid is None or g.get("tgId") == tgid):
            return g
    sys.exit(f"no {PARAM} group (tgId={tgid}) in {path}")


def find_kem_group(path, function=None):
    """ML-KEM groups key on function as well as parameter set."""
    d = json.load(open(path))
    for g in d["testGroups"]:
        if g.get("parameterSet") != KEM_PARAM:
            continue
        if function is not None and g.get("function") != function:
            continue
        return g
    sys.exit(f"no {KEM_PARAM} group (function={function}) in {path}")


def emit(f, name, words, nbytes, comment):
    # Eight words a line overruns the 100-column clang-format limit, so the
    # emitted file is NOT final: run
    #   make ocah-format-c FORMAT_C_PATH=hw/sys/sep/dv/fw/tests/common
    # after regenerating, and commit the reflowed result. Both committed
    # headers are 7-a-line because they went through that step; a raw
    # regeneration that skips it fails the format-c CI job.
    f.write(f"/* {comment} ({nbytes} bytes, {len(words)} words) */\n")
    f.write(f"static const uint32_t {name}[{len(words)}] = {{\n")
    for i in range(0, len(words), 8):
        f.write("    " + " ".join(f"0x{w:08x}u," for w in words[i : i + 8]) + "\n")
    f.write("};\n\n")


def main():
    f = open(OUT, "w")
    f.write("/* AUTO-GENERATED by gen_abr_nist_vectors.py from NIST ACVP-Server\n")
    f.write(" * ML-DSA-87 FIPS-204 vectors. DO NOT EDIT (regenerate via the script).\n")
    f.write(" * ABR I/O: little-endian 32-bit words; byte b -> word[b/4] bits (b%4)*8. */\n")
    f.write("#ifndef SEP_ABR_NIST_VECTORS_H\n#define SEP_ABR_NIST_VECTORS_H\n\n")
    f.write("#include <stdint.h>\n\n")

    # --- keyGen: seed (xi) -> expected pk ---
    g = find_group(KG)
    t = next(x for x in g["tests"] if "seed" in x and "pk" in x)
    sw, sn = hex_to_words(t["seed"])
    pw, pn = hex_to_words(t["pk"])
    f.write(f"/* keyGen  ACVP tcId {t['tcId']} */\n")
    emit(f, "nist_kg_seed", sw, sn, "keyGen seed xi")
    emit(f, "nist_kg_pk", pw, pn, "keyGen expected public key")
    f.write(f"#define NIST_KG_SEED_WORDS {len(sw)}\n")
    f.write(f"#define NIST_KG_PK_WORDS   {len(pw)}\n")
    f.write(f"#define NIST_KG_PK_BYTES   {pn}\n\n")

    # --- sigGen: deterministic external-mu (tgId 11): sk + mu -> expected sig ---
    g = find_group(SG, tgid=11)  # det=True, externalMu=True, internal iface
    t = g["tests"][0]
    skw, skn = hex_to_words(t["sk"])
    muw, mun = hex_to_words(t["mu"])
    sgw, sgn = hex_to_words(t["signature"])
    f.write(f"/* sigGen  ACVP tcId {t['tcId']} (deterministic, external-mu) */\n")
    emit(f, "nist_sg_sk", skw, skn, "sigGen private key (sk in)")
    emit(f, "nist_sg_mu", muw, mun, "sigGen precomputed mu")
    emit(f, "nist_sg_sig", sgw, sgn, "sigGen expected signature")
    f.write(f"#define NIST_SG_SK_WORDS  {len(skw)}\n")
    f.write(f"#define NIST_SG_MU_WORDS  {len(muw)}\n")
    f.write(f"#define NIST_SG_SIG_WORDS {len(sgw)}\n")
    f.write(f"#define NIST_SG_SIG_BYTES {sgn}\n\n")

    # --- sigVer: external-mu (tgId 11): pk + mu + sig -> expected verdict ---
    g = find_group(SV, tgid=11)
    good = next(x for x in g["tests"] if x.get("testPassed") is True)
    bad = next(x for x in g["tests"] if x.get("testPassed") is False)
    for tag, t in (("ok", good), ("bad", bad)):
        pkw, pkn = hex_to_words(t["pk"])
        muw, mun = hex_to_words(t["mu"])
        sgw, sgn = hex_to_words(t["signature"])
        verdict = 1 if t["testPassed"] else 0
        f.write(f"/* sigVer  ACVP tcId {t['tcId']} testPassed={t['testPassed']} */\n")
        emit(f, f"nist_sv_{tag}_pk", pkw, pkn, f"sigVer {tag} public key")
        emit(f, f"nist_sv_{tag}_mu", muw, mun, f"sigVer {tag} mu")
        emit(f, f"nist_sv_{tag}_sig", sgw, sgn, f"sigVer {tag} signature")
        f.write(f"#define NIST_SV_{tag.upper()}_VERDICT {verdict}\n\n")
    f.write("#define NIST_SV_PK_WORDS  648\n")
    f.write("#define NIST_SV_MU_WORDS  16\n")
    f.write("#define NIST_SV_SIG_WORDS 1157\n\n")

    f.write("#endif /* SEP_ABR_NIST_VECTORS_H */\n")
    f.close()
    print(f"wrote {OUT}")


def main_mlkem():
    f = open(KEM_OUT, "w")
    f.write("/* SPDX-License-Identifier: Apache-2.0 */\n")
    f.write("/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */\n\n")
    f.write("/* AUTO-GENERATED by gen_abr_nist_vectors.py --mlkem from NIST ACVP-Server\n")
    f.write(" * ML-KEM-1024 FIPS-203 vectors. DO NOT EDIT (regenerate via the script).\n")
    f.write(" * ABR I/O: little-endian 32-bit words; byte b -> word[b/4] bits (b%4)*8. */\n")
    f.write("#ifndef SEP_ABR_NIST_KEM_VECTORS_H\n#define SEP_ABR_NIST_KEM_VECTORS_H\n\n")
    f.write("#include <stdint.h>\n\n")

    # --- keyGen: d + z -> expected ek, dk ---
    g = find_kem_group(KEM_KG)
    t = g["tests"][0]
    dw, dn = hex_to_words(t["d"])
    zw, zn = hex_to_words(t["z"])
    ekw, ekn = hex_to_words(t["ek"])
    dkw, dkn = hex_to_words(t["dk"])
    f.write(f"/* ML-KEM keyGen  ACVP tcId {t['tcId']} */\n")
    emit(f, "nist_kem_kg_d", dw, dn, "keyGen seed d")
    emit(f, "nist_kem_kg_z", zw, zn, "keyGen seed z")
    emit(f, "nist_kem_kg_ek", ekw, ekn, "keyGen expected encapsulation key")
    emit(f, "nist_kem_kg_dk", dkw, dkn, "keyGen expected decapsulation key")

    # --- encaps: ek + m -> expected c, k ---
    g = find_kem_group(KEM_ED, function="encapsulation")
    t = g["tests"][0]
    eekw, eekn = hex_to_words(t["ek"])
    mw, mn = hex_to_words(t["m"])
    cw, cn = hex_to_words(t["c"])
    kw, kn = hex_to_words(t["k"])
    f.write(f"/* ML-KEM encaps  ACVP tcId {t['tcId']} */\n")
    emit(f, "nist_kem_enc_ek", eekw, eekn, "encaps encapsulation key")
    emit(f, "nist_kem_enc_m", mw, mn, "encaps message randomness m")
    emit(f, "nist_kem_enc_c", cw, cn, "encaps expected ciphertext")
    emit(f, "nist_kem_enc_k", kw, kn, "encaps expected shared key")

    # --- decaps: a valid case and an implicit-rejection case ---
    # Each ACVP case carries its own dk, so these are not one key walked twice:
    # the rejecting case is graded on its own expected K.
    g = find_kem_group(KEM_ED, function="decapsulation")
    good = next(x for x in g["tests"] if x.get("reason") == "valid decapsulation")
    bad = next(x for x in g["tests"] if x.get("reason") == "modified ciphertext")
    for tag, t in (("ok", good), ("bad", bad)):
        ddkw, ddkn = hex_to_words(t["dk"])
        dcw, dcn = hex_to_words(t["c"])
        dkkw, dkkn = hex_to_words(t["k"])
        f.write(f"/* ML-KEM decaps  ACVP tcId {t['tcId']} ({t['reason']}) */\n")
        emit(f, f"nist_kem_dec_{tag}_dk", ddkw, ddkn, f"decaps {tag} decapsulation key")
        emit(f, f"nist_kem_dec_{tag}_c", dcw, dcn, f"decaps {tag} ciphertext")
        emit(f, f"nist_kem_dec_{tag}_k", dkkw, dkkn, f"decaps {tag} expected shared key")

    f.write(f"#define NIST_KEM_SEED_WORDS {len(dw)}\n")
    f.write(f"#define NIST_KEM_MSG_WORDS  {len(mw)}\n")
    f.write(f"#define NIST_KEM_EK_WORDS   {len(ekw)}\n")
    f.write(f"#define NIST_KEM_DK_WORDS   {len(dkw)}\n")
    f.write(f"#define NIST_KEM_CT_WORDS   {len(cw)}\n")
    f.write(f"#define NIST_KEM_K_WORDS    {len(kw)}\n\n")

    f.write("#endif /* SEP_ABR_NIST_KEM_VECTORS_H */\n")
    f.close()
    print(f"wrote {KEM_OUT}")


if __name__ == "__main__":
    if "--mlkem" in sys.argv[1:]:
        main_mlkem()
    else:
        main()
