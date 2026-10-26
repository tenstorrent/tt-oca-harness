#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate the ABR known-answer headers from NIST ACVP-Server vectors.

  python3 gen_abr_nist_vectors.py           -> abr_nist_vectors.h      (ML-DSA-87)
  python3 gen_abr_nist_vectors.py --mlkem   -> abr_nist_kem_vectors.h  (ML-KEM-1024)
  python3 gen_abr_nist_vectors.py --hint    -> abr_nist_hint_vectors.h (ML-DSA-87 sigVer)

Each algorithm writes its own header and neither mode touches the other's file.

Pinned snapshot. The upstream ACVP-Server re-rolls its projection files from
release to release, so each algorithm reads its files at one fixed commit:

  ML-DSA  ACVP_DSA_SHA (RELEASE/v1.1.0.42)
  ML-KEM  ACVP_KEM_SHA

No single upstream commit holds both sets: the ML-DSA cases below are removed by
the v1.1.0.43 re-roll, and the ML-KEM encapsulation/decapsulation cases appear
only after it. The generator checks the SHA-256 of every input file against
ACVP_FILE_SHA256 and stops on a mismatch, so a file from another commit cannot
be used by mistake.

Unchanged-array check. Before it writes a header, the generator parses every
array of the header that is already on disk and stops if any word of it differs
from the regenerated array. A regeneration therefore only adds arrays and
defines; it never changes the expected values of a test that already reads the
header. Delete the header first to regenerate it from nothing.

The golden inputs/outputs are the official NIST ACVP "internalProjection" files
(they contain both inputs and expected outputs). Download them first:

  url=https://raw.githubusercontent.com/usnistgov/ACVP-Server
  dsa=$url/15c0f3deeefbfa8cb6cd32a99e1ca3b738c66bf0/gen-val/json-files
  kem=$url/ad33b3d9504491767f1aa76382464f3b3fa2359e/gen-val/json-files
  curl -sSL -o $TMPDIR/mldsa_keygen.json $dsa/ML-DSA-keyGen-FIPS204/internalProjection.json
  curl -sSL -o $TMPDIR/mldsa_siggen.json $dsa/ML-DSA-sigGen-FIPS204/internalProjection.json
  curl -sSL -o $TMPDIR/mldsa_sigver.json $dsa/ML-DSA-sigVer-FIPS204/internalProjection.json
  curl -sSL -o $TMPDIR/mlkem_keygen.json $kem/ML-KEM-keyGen-FIPS203/internalProjection.json
  curl -sSL -o $TMPDIR/mlkem_encdec.json $kem/ML-KEM-encapDecap-FIPS203/internalProjection.json

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

Outputs are FIPS-204 layout (PUBKEY=rho||t1, SIGNATURE=c~||z||h). Default
signing computes mu internally from the raw message with an empty context, so
the ACVP "message" maps straight to MLDSA_MSG.

ML-DSA sigVer reject table: every external-mu (tgId 11) ML-DSA-87 case with
testPassed false, in tcId order, as nist_sv_rej_<k>_{pk,mu,sig} with
NIST_SV_REJ_<k>_{TCID,VERDICT,REASON} and NIST_SV_REJ_COUNT. REASON is the ACVP
"reason" string.

The ML-KEM decaps set carries both a "valid decapsulation" case and a "modified
ciphertext" one: FIPS-203 implicit rejection means a bad ciphertext yields a
DIFFERENT shared key rather than an error, so the rejecting case has its own
expected K and is graded by value, not by an absence of error. The
modified-ciphertext table holds every such ML-KEM-1024 case, in tcId order, as
nist_kem_dec_mod_<k>_{dk,c,k} with NIST_KEM_DEC_MOD_<k>_{TCID,REASON} and
NIST_KEM_DEC_MOD_COUNT.

--hint reads the same ML-DSA sigVer file. It writes one pure-with-context case
that must verify (tgId 5), then every case NIST marks "modified signature - hint"
on the pure-with-context and external-mu interfaces (tgIds 5 and 11). It checks
each case independently of the ACVP verdict before writing, and for that needs
Python cryptography with ML-DSA (the uv vp group).

Eight words per line exceed the 100-column limit. After regeneration, run:
  make ocah-format-c FORMAT_C_PATH=hw/sys/sep/dv/fw/tests/common
An unformatted generated header fails format-c.
"""

import hashlib
import json
import os
import re
import sys

# The vectors are read from $TMPDIR, which is where the curl lines above put
# them; /tmp is not assumed to be writable or shared.
_TMP = os.environ.get("TMPDIR", "/tmp")

ACVP_DSA_SHA = "15c0f3deeefbfa8cb6cd32a99e1ca3b738c66bf0"
ACVP_KEM_SHA = "ad33b3d9504491767f1aa76382464f3b3fa2359e"

# SHA-256 of each internalProjection.json at its pinned commit.
ACVP_FILE_SHA256 = {
    "mldsa_keygen.json": "6027a0ad263de2fa4a96a6bc086b17daa494dcadeb4a51e31b1258225c1d382f",
    "mldsa_siggen.json": "9217e65242588b63fb8169cd64d1d92f6611cf41380802d7e043fffc07b0562a",
    "mldsa_sigver.json": "85827fd9f058d617b956301d342f2792d66ff188987ccce87f014f0bdb282457",
    "mlkem_keygen.json": "d7a62a2c3476957f56dd8d24f9004ea6776ccfe995ffe71a65bb9506dc9c7b1b",
    "mlkem_encdec.json": "a556952ce869bb89c3a3196a701dad89647c193a34c86eafb61a9d710d5b810f",
}

PARAM = "ML-DSA-87"
KG = os.path.join(_TMP, "mldsa_keygen.json")
SG = os.path.join(_TMP, "mldsa_siggen.json")
SV = os.path.join(_TMP, "mldsa_sigver.json")
OUT = os.path.join(os.path.dirname(__file__), "abr_nist_vectors.h")

KEM_PARAM = "ML-KEM-1024"
KEM_KG = os.path.join(_TMP, "mlkem_keygen.json")
KEM_ED = os.path.join(_TMP, "mlkem_encdec.json")
KEM_OUT = os.path.join(os.path.dirname(__file__), "abr_nist_kem_vectors.h")

HINT_OUT = os.path.join(os.path.dirname(__file__), "abr_nist_hint_vectors.h")
# The pure-with-context case that must verify, run first so a broken context or
# message stream fails on a case with a known answer.
HINT_ACCEPT_TCID = 63

# ML-DSA-87 (FIPS 204 Table 1) and the signature layout c~ || z || h.
MLDSA_N, MLDSA_K, MLDSA_L = 256, 8, 7
GAMMA1, BETA, OMEGA = 1 << 19, 120, 75
Z_OFF = 64
H_OFF = Z_OFF + MLDSA_L * 640

SPDX = (
    "/* SPDX-License-Identifier: Apache-2.0 */\n"
    "/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */\n\n"
)

_ARRAY_RE = re.compile(r"static const uint32_t (\w+)\[(\d+)\] = \{(.*?)\};", re.S)


def load_json(path):
    """Read one ACVP file and stop unless it is the pinned snapshot."""
    with open(path, "rb") as fh:
        raw = fh.read()
    want = ACVP_FILE_SHA256[os.path.basename(path)]
    got = hashlib.sha256(raw).hexdigest()
    if got != want:
        sys.exit(f"{path}: sha256 {got} is not the pinned snapshot {want}")
    return json.loads(raw)


def hex_to_words(h):
    """ACVP hex byte string -> (list[uint32] LE, byte_len)."""
    raw = bytes.fromhex(h)
    n = len(raw)
    pad = raw + b"\x00" * ((-n) % 4)
    words = [int.from_bytes(pad[i : i + 4], "little") for i in range(0, len(pad), 4)]
    return words, n


def find_group(d, path, tgid=None):
    for g in d["testGroups"]:
        if g.get("parameterSet") == PARAM and (tgid is None or g.get("tgId") == tgid):
            return g
    sys.exit(f"no {PARAM} group (tgId={tgid}) in {path}")


def find_kem_group(d, path, function=None):
    """ML-KEM groups key on function as well as parameter set."""
    for g in d["testGroups"]:
        if g.get("parameterSet") != KEM_PARAM:
            continue
        if function is not None and g.get("function") != function:
            continue
        return g
    sys.exit(f"no {KEM_PARAM} group (function={function}) in {path}")


def emit(f, name, words, nbytes, comment):
    f.append(f"/* {comment} ({nbytes} bytes, {len(words)} words) */\n")
    f.append(f"static const uint32_t {name}[{len(words)}] = {{\n")
    for i in range(0, len(words), 8):
        f.append("    " + " ".join(f"0x{w:08x}u," for w in words[i : i + 8]) + "\n")
    f.append("};\n\n")


def c_string(s):
    if '"' in s or "\\" in s:
        sys.exit(f"ACVP reason {s!r} needs escaping")
    return f'"{s}"'


def parse_arrays(text):
    out = {}
    for m in _ARRAY_RE.finditer(text):
        words = [int(tok, 16) for tok in re.findall(r"0x([0-9a-fA-F]+)u", m.group(3))]
        if len(words) != int(m.group(2)):
            sys.exit(f"{m.group(1)}: parsed {len(words)} words, header says {m.group(2)}")
        out[m.group(1)] = words
    return out


def check_unchanged(path, text):
    """Stop unless every array already in ``path`` is regenerated word for word."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        old = parse_arrays(fh.read())
    new = parse_arrays(text)
    bad = [name for name, words in old.items() if new.get(name) != words]
    if bad:
        sys.exit(f"{path}: regeneration changes existing arrays {bad}; header not written")


def write_header(path, parts):
    text = "".join(parts)
    check_unchanged(path, text)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {path}")


def main():
    f = [SPDX]
    f.append("/* AUTO-GENERATED by gen_abr_nist_vectors.py from NIST ACVP-Server\n")
    f.append(f" * commit {ACVP_DSA_SHA}\n")
    f.append(" * ML-DSA-87 FIPS-204 vectors. DO NOT EDIT (regenerate via the script).\n")
    f.append(" * ABR I/O: little-endian 32-bit words; byte b -> word[b/4] bits (b%4)*8. */\n")
    f.append("#ifndef SEP_ABR_NIST_VECTORS_H\n#define SEP_ABR_NIST_VECTORS_H\n\n")
    f.append("#include <stdint.h>\n\n")

    # --- keyGen: seed (xi) -> expected pk ---
    g = find_group(load_json(KG), KG)
    t = next(x for x in g["tests"] if "seed" in x and "pk" in x)
    sw, sn = hex_to_words(t["seed"])
    pw, pn = hex_to_words(t["pk"])
    f.append(f"/* keyGen  ACVP tcId {t['tcId']} */\n")
    emit(f, "nist_kg_seed", sw, sn, "keyGen seed xi")
    emit(f, "nist_kg_pk", pw, pn, "keyGen expected public key")
    f.append(f"#define NIST_KG_SEED_WORDS {len(sw)}\n")
    f.append(f"#define NIST_KG_PK_WORDS   {len(pw)}\n")
    f.append(f"#define NIST_KG_PK_BYTES   {pn}\n\n")

    # --- sigGen: deterministic external-mu (tgId 11): sk + mu -> expected sig ---
    g = find_group(load_json(SG), SG, tgid=11)  # det=True, externalMu=True, internal iface
    t = g["tests"][0]
    skw, skn = hex_to_words(t["sk"])
    muw, mun = hex_to_words(t["mu"])
    sgw, sgn = hex_to_words(t["signature"])
    f.append(f"/* sigGen  ACVP tcId {t['tcId']} (deterministic, external-mu) */\n")
    emit(f, "nist_sg_sk", skw, skn, "sigGen private key (sk in)")
    emit(f, "nist_sg_mu", muw, mun, "sigGen precomputed mu")
    emit(f, "nist_sg_sig", sgw, sgn, "sigGen expected signature")
    f.append(f"#define NIST_SG_SK_WORDS  {len(skw)}\n")
    f.append(f"#define NIST_SG_MU_WORDS  {len(muw)}\n")
    f.append(f"#define NIST_SG_SIG_WORDS {len(sgw)}\n")
    f.append(f"#define NIST_SG_SIG_BYTES {sgn}\n\n")

    # --- sigVer: external-mu (tgId 11): pk + mu + sig -> expected verdict ---
    g = find_group(load_json(SV), SV, tgid=11)
    good = next(x for x in g["tests"] if x.get("testPassed") is True)
    bad = next(x for x in g["tests"] if x.get("testPassed") is False)
    for tag, t in (("ok", good), ("bad", bad)):
        pkw, pkn = hex_to_words(t["pk"])
        muw, mun = hex_to_words(t["mu"])
        sgw, sgn = hex_to_words(t["signature"])
        verdict = 1 if t["testPassed"] else 0
        f.append(f"/* sigVer  ACVP tcId {t['tcId']} testPassed={t['testPassed']} */\n")
        emit(f, f"nist_sv_{tag}_pk", pkw, pkn, f"sigVer {tag} public key")
        emit(f, f"nist_sv_{tag}_mu", muw, mun, f"sigVer {tag} mu")
        emit(f, f"nist_sv_{tag}_sig", sgw, sgn, f"sigVer {tag} signature")
        f.append(f"#define NIST_SV_{tag.upper()}_VERDICT {verdict}\n\n")
    f.append("#define NIST_SV_PK_WORDS  648\n")
    f.append("#define NIST_SV_MU_WORDS  16\n")
    f.append("#define NIST_SV_SIG_WORDS 1157\n\n")
    f.append(f"#define NIST_SV_OK_TCID  {good['tcId']}\n")
    f.append(f"#define NIST_SV_BAD_TCID {bad['tcId']}\n\n")

    # --- sigVer reject table: every tgId 11 case with testPassed false ---
    rejects = sorted(
        (x for x in g["tests"] if x.get("testPassed") is False), key=lambda x: x["tcId"]
    )
    f.append(f"/* sigVer reject table: every ACVP tgId 11 {PARAM} case with testPassed=False */\n")
    f.append(f"#define NIST_SV_REJ_COUNT {len(rejects)}\n\n")
    for k, t in enumerate(rejects):
        pkw, pkn = hex_to_words(t["pk"])
        muw, mun = hex_to_words(t["mu"])
        sgw, sgn = hex_to_words(t["signature"])
        f.append(f"/* sigVer reject {k}  ACVP tcId {t['tcId']} ({t['reason']}) */\n")
        emit(f, f"nist_sv_rej_{k}_pk", pkw, pkn, f"sigVer reject {k} public key")
        emit(f, f"nist_sv_rej_{k}_mu", muw, mun, f"sigVer reject {k} mu")
        emit(f, f"nist_sv_rej_{k}_sig", sgw, sgn, f"sigVer reject {k} signature")
        f.append(f"#define NIST_SV_REJ_{k}_TCID    {t['tcId']}\n")
        f.append(f"#define NIST_SV_REJ_{k}_VERDICT 0\n")
        f.append(f"#define NIST_SV_REJ_{k}_REASON  {c_string(t['reason'])}\n\n")

    f.append("#endif /* SEP_ABR_NIST_VECTORS_H */\n")
    write_header(OUT, f)


def main_mlkem():
    f = [SPDX]
    f.append("/* AUTO-GENERATED by gen_abr_nist_vectors.py --mlkem from NIST ACVP-Server\n")
    f.append(f" * commit {ACVP_KEM_SHA}\n")
    f.append(" * ML-KEM-1024 FIPS-203 vectors. DO NOT EDIT (regenerate via the script).\n")
    f.append(" * ABR I/O: little-endian 32-bit words; byte b -> word[b/4] bits (b%4)*8. */\n")
    f.append("#ifndef SEP_ABR_NIST_KEM_VECTORS_H\n#define SEP_ABR_NIST_KEM_VECTORS_H\n\n")
    f.append("#include <stdint.h>\n\n")

    # --- keyGen: d + z -> expected ek, dk ---
    g = find_kem_group(load_json(KEM_KG), KEM_KG)
    t = g["tests"][0]
    dw, dn = hex_to_words(t["d"])
    zw, zn = hex_to_words(t["z"])
    ekw, ekn = hex_to_words(t["ek"])
    dkw, dkn = hex_to_words(t["dk"])
    f.append(f"/* ML-KEM keyGen  ACVP tcId {t['tcId']} */\n")
    emit(f, "nist_kem_kg_d", dw, dn, "keyGen seed d")
    emit(f, "nist_kem_kg_z", zw, zn, "keyGen seed z")
    emit(f, "nist_kem_kg_ek", ekw, ekn, "keyGen expected encapsulation key")
    emit(f, "nist_kem_kg_dk", dkw, dkn, "keyGen expected decapsulation key")

    # --- encaps: ek + m -> expected c, k ---
    ed = load_json(KEM_ED)
    g = find_kem_group(ed, KEM_ED, function="encapsulation")
    t = g["tests"][0]
    eekw, eekn = hex_to_words(t["ek"])
    mw, mn = hex_to_words(t["m"])
    cw, cn = hex_to_words(t["c"])
    kw, kn = hex_to_words(t["k"])
    f.append(f"/* ML-KEM encaps  ACVP tcId {t['tcId']} */\n")
    emit(f, "nist_kem_enc_ek", eekw, eekn, "encaps encapsulation key")
    emit(f, "nist_kem_enc_m", mw, mn, "encaps message randomness m")
    emit(f, "nist_kem_enc_c", cw, cn, "encaps expected ciphertext")
    emit(f, "nist_kem_enc_k", kw, kn, "encaps expected shared key")

    # --- decaps: a valid case and an implicit-rejection case ---
    # Each ACVP case carries its own dk, so these are not one key walked twice:
    # the rejecting case is graded on its own expected K.
    g = find_kem_group(ed, KEM_ED, function="decapsulation")
    good = next(x for x in g["tests"] if x.get("reason") == "valid decapsulation")
    bad = next(x for x in g["tests"] if x.get("reason") == "modified ciphertext")
    for tag, t in (("ok", good), ("bad", bad)):
        ddkw, ddkn = hex_to_words(t["dk"])
        dcw, dcn = hex_to_words(t["c"])
        dkkw, dkkn = hex_to_words(t["k"])
        f.append(f"/* ML-KEM decaps  ACVP tcId {t['tcId']} ({t['reason']}) */\n")
        emit(f, f"nist_kem_dec_{tag}_dk", ddkw, ddkn, f"decaps {tag} decapsulation key")
        emit(f, f"nist_kem_dec_{tag}_c", dcw, dcn, f"decaps {tag} ciphertext")
        emit(f, f"nist_kem_dec_{tag}_k", dkkw, dkkn, f"decaps {tag} expected shared key")

    f.append(f"#define NIST_KEM_SEED_WORDS {len(dw)}\n")
    f.append(f"#define NIST_KEM_MSG_WORDS  {len(mw)}\n")
    f.append(f"#define NIST_KEM_EK_WORDS   {len(ekw)}\n")
    f.append(f"#define NIST_KEM_DK_WORDS   {len(dkw)}\n")
    f.append(f"#define NIST_KEM_CT_WORDS   {len(cw)}\n")
    f.append(f"#define NIST_KEM_K_WORDS    {len(kw)}\n\n")
    f.append(f"#define NIST_KEM_DEC_OK_TCID  {good['tcId']}\n")
    f.append(f"#define NIST_KEM_DEC_BAD_TCID {bad['tcId']}\n\n")

    # --- decaps modified-ciphertext table: every such case, each with its own K ---
    mods = sorted(
        (x for x in g["tests"] if x.get("reason") == "modified ciphertext"),
        key=lambda x: x["tcId"],
    )
    f.append(f"/* decaps modified-ciphertext table: every ACVP {KEM_PARAM} case */\n")
    f.append(f"#define NIST_KEM_DEC_MOD_COUNT {len(mods)}\n\n")
    for k, t in enumerate(mods):
        ddkw, ddkn = hex_to_words(t["dk"])
        dcw, dcn = hex_to_words(t["c"])
        dkkw, dkkn = hex_to_words(t["k"])
        f.append(f"/* ML-KEM decaps modified {k}  ACVP tcId {t['tcId']} ({t['reason']}) */\n")
        emit(f, f"nist_kem_dec_mod_{k}_dk", ddkw, ddkn, f"decaps modified {k} decapsulation key")
        emit(f, f"nist_kem_dec_mod_{k}_c", dcw, dcn, f"decaps modified {k} ciphertext")
        emit(f, f"nist_kem_dec_mod_{k}_k", dkkw, dkkn, f"decaps modified {k} expected shared key")
        f.append(f"#define NIST_KEM_DEC_MOD_{k}_TCID   {t['tcId']}\n")
        f.append(f"#define NIST_KEM_DEC_MOD_{k}_REASON {c_string(t['reason'])}\n\n")

    f.append("#endif /* SEP_ABR_NIST_KEM_VECTORS_H */\n")
    write_header(KEM_OUT, f)


def z_out_of_range(sig):
    """True when some z coefficient has ||z|| >= gamma1 - beta (FIPS 204 BitUnpack)."""
    body = sig[Z_OFF:H_OFF]
    for i in range(MLDSA_L * MLDSA_N // 2):
        b = body[5 * i : 5 * i + 5]
        for t in (
            b[0] | (b[1] << 8) | ((b[2] & 0x0F) << 16),
            (b[2] >> 4) | (b[3] << 4) | (b[4] << 12),
        ):
            if abs(GAMMA1 - t) >= GAMMA1 - BETA:
                return True
    return False


def hint_malformed(sig):
    """True when the hint encoding breaks FIPS 204 HintBitUnpack (Algorithm 21)."""
    h = sig[H_OFF:]
    k = 0
    for i in range(MLDSA_K):
        end = h[OMEGA + i]
        if end < k or end > OMEGA:
            return True
        for j in range(k + 1, end):
            if h[j] <= h[j - 1]:
                return True
        k = end
    return any(h[j] for j in range(k, OMEGA))


def main_hint():
    """Every ML-DSA-87 sigVer case NIST marks as a modified hint, on both interfaces
    the SEP drives (pure with a context, tgId 5; external mu, tgId 11), after one
    pure-with-context case that must verify."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import mldsa

    d = load_json(SV)
    pure, ext = find_group(d, SV, tgid=5), find_group(d, SV, tgid=11)
    if pure["externalMu"] or pure["preHash"] != "pure" or not ext["externalMu"]:
        sys.exit("tgId 5 is not pure ML-DSA, or tgId 11 is not external mu")

    cases = [(5, next(t for t in pure["tests"] if t["tcId"] == HINT_ACCEPT_TCID))]
    for tgid, g in ((5, pure), (11, ext)):
        cases += [(tgid, t) for t in g["tests"] if t["reason"] == "modified signature - hint"]

    # Each case is checked here, independently of the ACVP verdict: the accepting
    # one verifies, and every hint case has z in range and a malformed hint, so the
    # core reaches the hint decode and must reject there.
    for tgid, t in cases:
        sig = bytes.fromhex(t["signature"])
        if tgid == 5:
            pk = mldsa.MLDSA87PublicKey.from_public_bytes(bytes.fromhex(t["pk"]))
            try:
                pk.verify(sig, bytes.fromhex(t["message"]), bytes.fromhex(t["context"]))
                ok = True
            except InvalidSignature:
                ok = False
            if ok != t["testPassed"] or not t["context"]:
                sys.exit(f"tcId {t['tcId']}: verify gave {ok}, or the context is empty")
        if not t["testPassed"] and (z_out_of_range(sig) or not hint_malformed(sig)):
            sys.exit(f"tcId {t['tcId']}: not a well-formed z with a malformed hint")

    f = [SPDX]
    f.append("/* AUTO-GENERATED by gen_abr_nist_vectors.py --hint from NIST ACVP-Server\n")
    f.append(f" * commit {ACVP_DSA_SHA}\n")
    f.append(" * ML-DSA-87 FIPS-204 sigVer vectors. DO NOT EDIT (regenerate via the script).\n")
    f.append(" * ABR I/O: little-endian 32-bit words; byte b -> word[b/4] bits (b%4)*8. */\n")
    f.append("#ifndef SEP_ABR_NIST_HINT_VECTORS_H\n#define SEP_ABR_NIST_HINT_VECTORS_H\n\n")
    f.append("#include <stdint.h>\n\n")
    f.append(f"#define NIST_HR_CASES {len(cases)}\n\n")
    for i, (tgid, t) in enumerate(cases):
        tag = f"nist_hr{i}"
        f.append(f"/* sigVer  ACVP tgId {tgid} tcId {t['tcId']}: {t['reason']} */\n")
        f.append(f"#define NIST_HR{i}_TCID {t['tcId']}\n")
        f.append(f"#define NIST_HR{i}_VERDICT {1 if t['testPassed'] else 0}\n")
        f.append(f"#define NIST_HR{i}_EXTERNAL_MU {1 if tgid == 11 else 0}\n")
        emit(f, f"{tag}_pk", *hex_to_words(t["pk"]), "public key")
        emit(f, f"{tag}_sig", *hex_to_words(t["signature"]), "signature")
        if tgid == 11:
            emit(f, f"{tag}_mu", *hex_to_words(t["mu"]), "mu")
        else:
            for field in ("message", "context"):
                words, nbytes = hex_to_words(t[field])
                name = "msg" if field == "message" else "ctx"
                f.append(f"#define NIST_HR{i}_{name.upper()}_BYTES {nbytes}\n")
                emit(f, f"{tag}_{name}", words, nbytes, field)
    f.append("#endif /* SEP_ABR_NIST_HINT_VECTORS_H */\n")
    write_header(HINT_OUT, f)


if __name__ == "__main__":
    if "--mlkem" in sys.argv[1:]:
        main_mlkem()
    elif "--hint" in sys.argv[1:]:
        main_hint()
    else:
        main()
