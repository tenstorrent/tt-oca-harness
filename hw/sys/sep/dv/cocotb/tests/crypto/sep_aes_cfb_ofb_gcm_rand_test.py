# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AES CFB-128, OFB and GCM, encrypt and decrypt, at key sizes 128, 192 and 256.

Contract (``hw/sys/sep/doc/aes.adoc`` Features: key sizes 128/192/256, modes CFB,
OFB and CTR-GCM; ``vendor/lowRISC/opentitan/upstream/hw/ip/aes/data/aes.hjson``:
AES.MODE.CFB-128, AES.MODE.OFB and AES.MODE.GCM do both operations at all three key
lengths, CFB with a data-segment size of 128 only; CTRL_GCM_SHADOWED phases and
NUM_VALID_BYTES):
  * CFB and OFB: each DATA_OUT block equals the NIST SP 800-38A result for the
    written key, IV and input.
  * GCM: each TEXT-phase DATA_OUT block equals the NIST SP 800-38D ciphertext
    (encrypt) or plaintext (decrypt), and the DATA_OUT block after GCM_TAG equals
    the SP 800-38D tag over the AAD and the ciphertext. Phase order:
    GCM_INIT -> GCM_AAD (when there is AAD) -> GCM_TEXT (when there is text) ->
    GCM_TAG. The last AAD or text block carries NUM_VALID_BYTES = its byte count.

Golden: ``env/sep_aes_mode_golden.py`` (SP 800-38A CFB-128 and OFB, SP 800-38D GCM on
the FIPS-197 cipher of ``env/sep_aes_golden.py``), self-checked against the published
vectors by ``env/run_golden_selftests.py``.

GCM register programming (vendor/lowRISC/opentitan/upstream/hw/ip/aes/doc/
programmers_guide.md, GCM Encryption and GCM Decryption): in GCM_INIT software writes
the 96-bit IV to IV_0..IV_2 and 0 to IV_3, and the hardware forms J0 = IV || 0^31 || 1;
before a partial last AAD or text block it waits for IDLE and sets NUM_VALID_BYTES.
The byte order of the GCM_TAG length block is not stated in-tree: the leaf writes
[len(A)]_64 || [len(C)]_64 in bits, big-endian, in the data byte order (stimulus, not
golden). A DUT result that disagrees fails the check.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. The internal entropy source feeds ESRC, CSRNG and EDN for
the AES masking reseed. HMAC, KMAC, OTBN and ABR stay in reset.

Randomization (``SepSeededRng`` from the run seed, drawn before the first stimulus
by ``draw_plan``): the mode {CFB, OFB, GCM}, the key size {128, 192, 256}, the
direction {encrypt, decrypt}, the key, the IV and the input. CFB and OFB: 2 to 4
whole blocks. GCM: a 96-bit IV, an AAD length of 0 to 40 bytes and a text length of
0 to 48 bytes, so the last AAD or text block can be partial. The DATA_IN bytes
past NUM_VALID_BYTES of a partial block are 16 drawn non-zero bytes, so a DUT that
does not mask them by NUM_VALID_BYTES shows a wrong text or tag. One cell runs per
seed; the 18 cells close over merged regressions (docs/SEP_FCOV.adoc).

Checkers (each logs mode, key size, direction and the first mismatched word):
  CHK-AES-CFB   every DATA_OUT block equals the SP 800-38A CFB-128 golden.
  CHK-AES-OFB   every DATA_OUT block equals the SP 800-38A OFB golden.
  CHK-AES-GCM   part=text: every TEXT-phase DATA_OUT block equals the SP 800-38D
                golden (the valid bytes of a partial last block);
                part=tag: the DATA_OUT block after GCM_TAG equals the SP 800-38D tag.
Controls (from the plan, before the first stimulus):
  CTRL-AES-OUT-NE-IN       every golden output block differs from its input block,
                           so a DUT that returns DATA_IN fails the check.
  CTRL-AES-MODE-DISTINCT   the golden differs from the golden of the other
                           feedback modes (CFB, OFB, CTR) for the same key, IV and
                           input, so a DUT that runs another mode fails the check.
                           GCM: the text golden differs from CTR mode from J0 (no
                           inc32) and the tag golden differs from the length block.
A passing check writes one FCOV record (``sep_aes_cfb_ofb_gcm_cg``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_aes_golden import aes_ctr_encrypt
from env.sep_aes_mode_golden import (
    bytes_to_words,
    cfb_decrypt,
    cfb_encrypt,
    gcm_decrypt,
    gcm_encrypt,
    gcm_j0,
    gcm_len_block,
    ofb_crypt,
    words_to_bytes,
)
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import fcov_present, owner_code
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import ot_rdl_named_codes
from sep_base_test import sep_base_test
from sep_reg_meta import AES
from seq_lib.sep_aes_seq import (
    AES_DATA_IN_0,
    AES_DATA_OUT_0,
    AES_KEYLEN_CTRL,
    AES_MODE_CTRL,
    AES_OP_DEC,
    AES_OP_ENC,
    AES_STATUS,
    AES_STATUS_IDLE,
    AES_STATUS_INPUT_READY,
    AES_STATUS_OUTPUT_VALID,
    SepAes,
)

TEST = "sep_aes_cfb_ofb_gcm_rand_test"

MODES = ("cfb", "ofb", "gcm")
KEY_SIZES = (128, 192, 256)
DIRECTIONS = ("enc", "dec")
CHK_NAME = {"cfb": "AES-CFB", "ofb": "AES-OFB", "gcm": "AES-GCM"}

# --- Field codes from the OpenTitan AES register description ---------------
_AES_HJSON = (
    Path(__file__).resolve().parents[7]
    / "vendor"
    / "lowRISC"
    / "opentitan"
    / "upstream"
    / "hw"
    / "ip"
    / "aes"
    / "data"
    / "aes.hjson"
)
_HJSON_REG = re.compile(r'\{\s*name:\s*"([A-Z0-9_]+)",')
_HJSON_ENUM_ROW = re.compile(r'value:\s*"(\w+)",\s*name:\s*"([A-Z0-9_]+)"')


@lru_cache(maxsize=None)
def hjson_enum(reg: str, field: str) -> dict[str, int]:
    """The ``enum`` list of field ``field`` of register ``reg`` in aes.hjson."""
    text = _AES_HJSON.read_text(encoding="utf-8")
    starts = [m for m in _HJSON_REG.finditer(text) if m.group(1) == reg]
    if len(starts) != 1:
        raise ValueError(f"aes.hjson: register {reg} found {len(starts)} times")
    fld = re.compile(rf'name:\s*"{field}",').search(text, starts[0].end())
    if fld is None:
        raise ValueError(f"aes.hjson: {reg}.{field} not found")
    nxt = text.find("enum: [", fld.end())
    end = text.find("]", nxt)
    if nxt < 0 or end < 0:
        raise ValueError(f"aes.hjson: {reg}.{field} has no enum list")
    return {name: int(value, 0) for value, name in _HJSON_ENUM_ROW.findall(text[nxt:end])}


def _check_codes() -> tuple[dict[str, int], dict[str, int]]:
    """Mode and GCM phase codes from aes.hjson, cross-checked before any use.

    The ECB, CBC and CTR codes that ``seq_lib/sep_aes_seq.py`` programs must equal
    the parsed MODE enum, GCM_INIT must equal the code that aes.rdl states, and
    every code must be one-hot in its RDL field width, so a parse of the wrong
    field fails at import.
    """
    mode = hjson_enum("CTRL_SHADOWED", "MODE")
    phase = hjson_enum("CTRL_GCM_SHADOWED", "PHASE")
    for name, ours in (("AES_ECB", "ecb"), ("AES_CBC", "cbc"), ("AES_CTR", "ctr")):
        if mode.get(name) != AES_MODE_CTRL[ours]:
            raise ValueError(f"aes.hjson MODE {name}={mode.get(name)} != sep_aes_seq code")
    stated = ot_rdl_named_codes("aes", "CTRL_GCM_SHADOWED")
    if phase.get("GCM_INIT") != stated.get("GCM_INIT"):
        raise ValueError(f"aes.hjson GCM_INIT={phase.get('GCM_INIT')} != aes.rdl {stated}")
    codes = {
        ("CTRL_SHADOWED", "mode"): [mode[n] for n in ("AES_CFB", "AES_OFB", "AES_GCM")],
        ("CTRL_GCM_SHADOWED", "phase"): [
            phase[n] for n in ("GCM_INIT", "GCM_AAD", "GCM_TEXT", "GCM_TAG")
        ],
    }
    for (reg, fld), values in codes.items():
        width = AES.field_width(reg, fld)
        for v in values:
            if v >= 1 << width or bin(v).count("1") != 1:
                raise ValueError(f"AES {reg}.{fld} code 0b{v:b} is not one-hot in {width} bits")
    return mode, phase


_MODE_ENUM, _PHASE_ENUM = _check_codes()
AES_MODE_CODE = {
    "cfb": _MODE_ENUM["AES_CFB"],
    "ofb": _MODE_ENUM["AES_OFB"],
    "gcm": _MODE_ENUM["AES_GCM"],
}
GCM_INIT = _PHASE_ENUM["GCM_INIT"]
GCM_AAD = _PHASE_ENUM["GCM_AAD"]
GCM_TEXT = _PHASE_ENUM["GCM_TEXT"]
GCM_TAG = _PHASE_ENUM["GCM_TAG"]
AES_CTRL_GCM_SHADOWED = AES.addr("CTRL_GCM_SHADOWED")
GCM_PHASE_LSB = AES.field_lsb("CTRL_GCM_SHADOWED", "phase")
GCM_NVB_LSB = AES.field_lsb("CTRL_GCM_SHADOWED", "num_valid_bytes")
GCM_NVB_WIDTH = AES.field_width("CTRL_GCM_SHADOWED", "num_valid_bytes")
assert 16 < 1 << GCM_NVB_WIDTH, "NUM_VALID_BYTES must hold 16"


def gcm_ctrl(phase: int, num_valid_bytes: int = 16) -> int:
    """CTRL_GCM_SHADOWED word for a phase and the valid-byte count of the next block."""
    assert 1 <= num_valid_bytes <= 16, "NUM_VALID_BYTES is 1 to 16"
    return (phase << GCM_PHASE_LSB) | (num_valid_bytes << GCM_NVB_LSB)


def _blocks(data: bytes) -> list[bytes]:
    return [data[i : i + 16] for i in range(0, len(data), 16)]


def _pad(block: bytes, fill: bytes) -> bytes:
    """A 16-byte DATA_IN block: ``block``, then the bytes of ``fill`` past its length."""
    return block + fill[len(block) : 16]


# --- Plan ---------------------------------------------------------------------
@dataclass(frozen=True)
class Plan:
    seed: int
    mode: str
    key_bits: int
    direction: str
    key: bytes
    iv: bytes  # 16 bytes (CFB, OFB) or the 12-byte GCM IV
    data: bytes  # the DATA_IN stream: plaintext (enc) or ciphertext (dec)
    aad: bytes = b""
    # DATA_IN bytes past NUM_VALID_BYTES of a partial last block: non-zero, so a
    # DUT that does not mask them by NUM_VALID_BYTES shows a wrong text or tag.
    pad_fill: bytes = bytes(16)

    @property
    def key_words(self) -> list[int]:
        return bytes_to_words(self.key)

    def iv_words(self) -> list[int]:
        """IV_0..IV_3: the IV (CFB, OFB), or the 96-bit IV with IV_3 = 0 (GCM)."""
        return bytes_to_words(self.iv + bytes(4) if self.mode == "gcm" else self.iv)

    def golden(self) -> tuple[bytes, bytes | None]:
        """(the DATA_OUT stream, the GCM tag or None)."""
        if self.mode == "cfb":
            fn = cfb_encrypt if self.direction == "enc" else cfb_decrypt
            return fn(self.key, self.iv, self.data), None
        if self.mode == "ofb":
            return ofb_crypt(self.key, self.iv, self.data), None
        fn = gcm_encrypt if self.direction == "enc" else gcm_decrypt
        return fn(self.key, self.iv, self.aad, self.data)

    def len_block(self) -> bytes:
        return gcm_len_block(len(self.aad), len(self.data))

    def cell(self) -> str:
        return f"{self.mode}-{self.key_bits}-{self.direction}"

    def describe(self) -> str:
        return (
            f"mode={self.mode} keylen={self.key_bits} dir={self.direction} "
            f"key={self.key.hex()} iv={self.iv.hex()} data_len={len(self.data)} "
            f"aad_len={len(self.aad)}"
        )


def _other_mode_goldens(p: Plan) -> dict[str, bytes]:
    """Output of the other feedback modes for the same key, IV and input."""
    out = {
        "cfb_enc": cfb_encrypt(p.key, p.iv, p.data),
        "cfb_dec": cfb_decrypt(p.key, p.iv, p.data),
        "ofb": ofb_crypt(p.key, p.iv, p.data),
        "ctr": aes_ctr_encrypt(p.key, p.iv, p.data),
    }
    own = {"cfb": f"cfb_{p.direction}", "ofb": "ofb"}[p.mode]
    out.pop(own)
    return out


def plan_guards(p: Plan) -> dict[str, int]:
    """Construction guards of the plan: 1 when the property holds (see the controls)."""
    out, tag = p.golden()
    ne_in = all(o != i for o, i in zip(_blocks(out), _blocks(p.data), strict=True))
    if p.mode == "gcm":
        j0_ctr = aes_ctr_encrypt(p.key, gcm_j0(p.iv), p.data)
        distinct = (not p.data or j0_ctr != out) and tag != p.len_block()
    else:
        distinct = all(g != out for g in _other_mode_goldens(p).values())
    return {"out_ne_in": int(ne_in), "mode_distinct": int(distinct)}


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    mode = rng.choice(MODES)
    key_bits = rng.choice(KEY_SIZES)
    direction = rng.choice(DIRECTIONS)
    key = rng.getrandbits(key_bits).to_bytes(key_bits // 8, "little")
    iv_len = 12 if mode == "gcm" else 16
    iv = rng.getrandbits(8 * iv_len).to_bytes(iv_len, "little")
    if mode == "gcm":
        aad_len = rng.randrange(0, 41)
        text_len = rng.randrange(0, 49)
    else:
        aad_len = 0
        text_len = 16 * rng.randrange(2, 5)
    # Redraw the bytes until every whole input word is unique and non-zero (the
    # area data rule) and the construction guards hold; a pure function of the seed.
    while True:
        aad = rng.getrandbits(8 * aad_len).to_bytes(aad_len, "little") if aad_len else b""
        data = rng.getrandbits(8 * text_len).to_bytes(text_len, "little") if text_len else b""
        words = [w for buf in (aad, data) for w in _whole_words(buf)]
        if 0 in words or len(set(words)) != len(words):
            continue
        plan = Plan(seed, mode, key_bits, direction, key, iv, data, aad)
        if all(plan_guards(plan).values()):
            break
    pad_fill = bytes(rng.randrange(1, 256) for _ in range(16))
    return replace(plan, pad_fill=pad_fill)


def _whole_words(buf: bytes) -> list[int]:
    return bytes_to_words(buf[: len(buf) - len(buf) % 4])


def first_mismatch(got: bytes, exp: bytes) -> dict[str, object]:
    """Index of the first word that differs, with both words, or ``none``."""
    for i in range(0, max(len(got), len(exp)), 4):
        g, e = got[i : i + 4], exp[i : i + 4]
        if g != e:
            return {
                "first_bad_word": i // 4,
                "got": "0x" + bytes(reversed(g)).hex(),
                "exp": "0x" + bytes(reversed(e)).hex(),
            }
    return {"first_bad_word": "none"}


# --- FCOV record ------------------------------------------------------------
async def aes_mode_fcov(plan: Plan) -> bool:
    """Record one passed cell for ``sep_aes_cfb_ofb_gcm_cg``; call only after its check passed.

    Writes the owner code, the MODE, KEY_LEN and OPERATION codes of the cell into the
    ``aes_mx_*`` variables of ``u_sep_fcov`` and adds 1 to ``aes_mx_seq``. The sampler
    scores the cell only when these codes equal the committed AES control. Returns False
    on Verilator (no sampler); on any other simulator a sampler without ``aes_mx_seq`` is
    a testbench error.
    """
    code = owner_code(TEST)
    if not fcov_present():
        return False
    top = cocotb.top
    fcov = top.u_sep_fcov
    if not hasattr(fcov, "aes_mx_seq"):
        raise AttributeError("u_sep_fcov has no aes_mx_seq variable (cov/sv/sep_fcov.sv)")
    fcov.aes_mx_owner.value = code
    fcov.aes_mx_mode.value = AES_MODE_CODE[plan.mode]
    fcov.aes_mx_key.value = AES_KEYLEN_CTRL[plan.key_bits]
    fcov.aes_mx_op.value = AES_OP_ENC if plan.direction == "enc" else AES_OP_DEC
    fcov.aes_mx_seq.value = (int(fcov.aes_mx_seq.value) + 1) & 0xFFFF_FFFF
    await ClockCycles(top.clk_i, 2)
    return True


@pyuvm.test()
class sep_aes_cfb_ofb_gcm_rand_test(sep_base_test):
    """AES CFB-128, OFB and GCM at 128/192/256 bits, encrypt and decrypt, match NIST SP 800-38A/D."""

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.plan = plan
        self.required_evidence = (f"CHK-{CHK_NAME[plan.mode]}",)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())

        await self.bring_up_no_cpu(park=("otbn", "hmac", "kmac", "abr"))
        await self.bring_up_entropy(strict=True, score_km=False)
        self.start_fifo_drain()
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"

        self.chk = SepChkLog(self, TEST, seed)
        self.aes = SepAes(self)
        guards = plan_guards(plan)
        self.chk.ctrl(
            "AES-OUT-NE-IN", guards["out_ne_in"] == 1, mode=plan.mode, blocks=len(plan.data) // 16
        )
        self.chk.ctrl("AES-MODE-DISTINCT", guards["mode_distinct"] == 1, mode=plan.mode)
        await self.aes.trigger_prng_reseed()  # seed the masking PRNG from EDN

        op = AES_OP_ENC if plan.direction == "enc" else AES_OP_DEC
        await self.aes.configure(
            mode=AES_MODE_CODE[plan.mode], key_len=AES_KEYLEN_CTRL[plan.key_bits], operation=op
        )
        if plan.mode == "gcm":
            await self._run_gcm(plan)
        else:
            await self._run_cfb_ofb(plan)
        await self.aes.check_status_clean(plan.cell())

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.chk.finish()

    def _fields(self, plan: Plan) -> dict[str, object]:
        return {"mode": plan.mode, "keylen": plan.key_bits, "dir": plan.direction}

    async def _run_cfb_ofb(self, plan: Plan) -> None:
        golden, _ = plan.golden()
        got = b""
        reason = ""
        try:
            await self.aes.load_key_iv(plan.key_words, plan.iv_words())
            for blk in _blocks(plan.data):
                got += words_to_bytes(await self.aes.run_ecb_block(bytes_to_words(blk)))
        except AssertionError as exc:  # a bounded STATUS wait expired
            reason = str(exc).replace(" ", "_")
        fields = {**self._fields(plan), "blocks": len(golden) // 16}
        fields.update(first_mismatch(got, golden))
        if reason:
            fields["reason"] = reason
        if self.chk.ok(CHK_NAME[plan.mode], not reason and got == golden, **fields):
            await aes_mode_fcov(plan)

    async def _gcm_phase(self, phase: int, num_valid_bytes: int = 16) -> None:
        """Write CTRL_GCM_SHADOWED twice (shadowed) with the unit idle, then wait idle."""
        await self.aes.wait_idle("pre-gcm-ctrl")
        value = gcm_ctrl(phase, num_valid_bytes)
        await self.aes._wr(AES_CTRL_GCM_SHADOWED, value)
        await self.aes._wr(AES_CTRL_GCM_SHADOWED, value)
        await self.aes.wait_idle("post-gcm-ctrl")
        self.logger.info("AES CTRL_GCM_SHADOWED=0x%03x", value)

    async def _write_block(self, block: bytes) -> None:
        await self.aes._poll_status_bit(AES_STATUS_INPUT_READY, "input_ready")
        for i, w in enumerate(bytes_to_words(_pad(block, self.plan.pad_fill))):
            await self.aes._wr(AES_DATA_IN_0 + 4 * i, w)

    async def _read_out(self) -> bytes:
        await self.aes._poll_status_bit(AES_STATUS_OUTPUT_VALID, "output_valid")
        return words_to_bytes([await self.aes._rd(AES_DATA_OUT_0 + 4 * i) for i in range(4)])

    async def _phase_blocks(self, phase: int, data: bytes, *, read: bool) -> bytes:
        """Write ``data`` in one GCM phase entered with NUM_VALID_BYTES = 16; a partial
        last block gets its byte count after IDLE, as the programmer's guide states."""
        out = b""
        blocks = _blocks(data)
        n, last_len = len(blocks), len(blocks[-1])
        await self._gcm_phase(phase)
        for i, blk in enumerate(blocks):
            if i == n - 1 and last_len < 16:
                await self._gcm_phase(phase, last_len)
            await self._write_block(blk)
            if read:
                out += (await self._read_out())[: len(blk)]
        await self.aes.wait_idle("gcm-phase-end")
        return out

    async def _run_gcm(self, plan: Plan) -> None:
        golden, tag_golden = plan.golden()
        got = b""
        tag = b""
        reason = ""
        try:
            await self._gcm_phase(GCM_INIT)
            await self.aes.write_key(plan.key_words)
            await self.aes.wait_idle("post-key")
            await self.aes.write_iv(plan.iv_words())
            await self.aes.wait_idle("post-iv")  # hash subkey and E(K, J0)
            if plan.aad:
                await self._phase_blocks(GCM_AAD, plan.aad, read=False)
            if plan.data:
                got = await self._phase_blocks(GCM_TEXT, plan.data, read=True)
            await self._gcm_phase(GCM_TAG)
            await self._write_block(plan.len_block())
            tag = await self._read_out()
            st = await self.aes._rd(AES_STATUS)
            self.chk.obs(
                "AES-GCM-TAG-STATUS", status=f"0x{st:08x}", idle=(st >> AES_STATUS_IDLE) & 1
            )
        except AssertionError as exc:  # a bounded STATUS wait expired
            reason = str(exc).replace(" ", "_")
        base = {**self._fields(plan), "aad_bytes": len(plan.aad), "text_bytes": len(plan.data)}
        if reason:
            base["reason"] = reason
        text_ok = True
        if plan.data:
            text_ok = self.chk.ok(
                CHK_NAME["gcm"],
                not reason and got == golden,
                part="text",
                **base,
                **first_mismatch(got, golden),
            )
        tag_ok = self.chk.ok(
            CHK_NAME["gcm"],
            not reason and tag == tag_golden,
            part="tag",
            **base,
            **first_mismatch(tag, tag_golden or b""),
        )
        if text_ok and tag_ok:
            await aes_mode_fcov(plan)
