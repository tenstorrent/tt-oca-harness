# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SEP CPU moves SEP SRAM blocks through AES under a key it loads into the Key Manager.

The VeeR EL2 CPU runs ``fw/tests/km_aes_sram_cpu_rand_test``; the KM CPU runs
the production ``rom_main`` image (``+km_rom_hex=rom_main.rom.parhex``), which
reads OTP at boot, so the leaf senses a PROD eFuse image staged at t=0
(``dv_sim_prestage.py`` ``EFUSE_IMAGE_REGISTRY``). The host draws every value,
patches it into the firmware parameter block of the DTCM image
(``env/sep_dtcm_param_patch.py``) and grades the values the firmware prints
(``env/sep_fw_console.py``). The firmware holds no expected value and prints
no ``CHK-`` line.

Procedure:
  1. Draw the KM key and a dummy software key (``SepSeededRng(seed ^
     KMAES_KEY_SALT)``): eight words each, every word not 0, the key words
     pairwise distinct, dummy word i not equal to key word i. Draw the SRAM
     plan (``SepSeededRng(seed ^ SRAM_SALT)``): n in 2..8, a window
     ``[G][SRC][G][G][ENC][G][G][DEC][G]`` at a random 8-byte aligned offset in
     SEP SRAM (each region n 16-byte blocks, each guard G two 32-bit words),
     the plaintext, the encrypt and decrypt fill words and the guard words.
  2. Boot the firmware. It waits for fuse sense, brings up the entropy stack,
     releases AES and the KM, waits for RESP_KM_READY, sends CMD_KEY_LOAD of
     the key with destination AES and CMD_KEY_TRANSFER of the returned handle
     to AES.
  3. The firmware pre-fills the window and prints its readback. It runs the
     encrypt leg (CTRL_SHADOWED with SIDELOAD=1, KEY_LEN 256, ECB, encrypt;
     the dummy key in KEY_SHARE0 and zero in KEY_SHARE1; per block a CPU load
     from SRC, DATA_IN, OUTPUT_VALID, DATA_OUT, a CPU store to ENC) and the
     decrypt leg (ENC to DEC), then prints the readback of every region and
     guard word.

Checks:
  CHK-AES-SRAM-KM-CPU op=enc  ENC reads back AES-256-ECB(key, plaintext), the
      FIPS-197 golden of ``env/sep_aes_golden.py``. The software key registers
      hold the dummy key, so a wrong key select fails it.
  CHK-AES-SRAM-KM-CPU op=dec  DEC reads back the drawn plaintext.

Controls:
  CTRL-KMAES-PARAM       the firmware echo of the parameter header equals the
      draw; the CRC-32C of each key the firmware computes equals the CRC-32C
      of the drawn key (no key word is printed).
  CTRL-KMAES-KM-READY    the RESP_KM_READY wait returns 0.
  CTRL-KMAES-KEY-LOAD    CMD_KEY_LOAD returns status 0; the return argument
      carries REQ_SIZE 7 and DEST_VALID = AES (firmware.adoc, CMD_KEY_LOAD
      success response).
  CTRL-KMAES-KEY-XFER    CMD_KEY_TRANSFER returns status 0; the return
      argument carries the handle of the load and DEST_ENGINE = AES.
  CTRL-KMAES-SIDELOAD    per leg, the CTRL_SHADOWED readback has SIDELOAD 1,
      KEY_LEN 256, MODE ECB and the leg's OPERATION.
  CTRL-AES-SRAM-CPU-PRE  every pre-filled word reads back as written; each fill
      word differs from 0 and from the golden of its slot, each guard word from
      every plaintext and golden word, and the dummy-key ciphertext of every
      block from the key ciphertext.
  CTRL-AES-SRAM-CPU-REGIONS  after both legs SRC and the guard words read back
      unchanged. The CPU is the only agent that writes SEP SRAM in this leaf,
      so this line proves the firmware addressing.

Bench records: INFO-AES-SRAM-KM-CPU-PLAN (n, window, region bases, salts, key
digests), INFO-KMAES-CMD (each firmware step and its return code),
INFO-AES-SRAM-KM-CPU-LAT (OUTPUT_VALID poll counts per leg; the wait has a
liveness bound only, so the counts are not graded).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pyuvm
from env.sep_aes_golden import aes256_ecb_encrypt_words
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_chk_log import SepChkLog, word_digest
from env.sep_crc_golden import crc32c
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_fw_console import SepFwConsole
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AES, sym
from seq_lib.sep_aes_seq import (
    AES_KEY_LEN_256,
    AES_MODE_ECB,
    AES_OP_DEC,
    AES_OP_ENC,
    build_aes_ctrl,
)
from seq_lib.sep_km_mailbox_seq import KM_DEST_AES

TEST = "sep_km_aes_sram_cpu_rand_test"
_FW = "km_aes_sram_cpu_rand_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", _FW)
_ITCM_HEX = os.path.join(_FW_DIR, f"{_FW}.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, f"{_FW}.dtcm.hex")
_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_BANNER = "SEP KM AES SRAM CPU test"
# Liveness bounds of the boot poll; it ends at the firmware completion magic.
_MAX_RUN_CYCLES = 20_000_000
_NO_BOOT_CYCLES = 80_000

SEP_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SEP_SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")

# Domain tags of the two draw streams; each stream moves only its own values.
KMAES_KEY_SALT = 0x4B4D
SRAM_SALT = 0x5352

_M32 = 0xFFFF_FFFF
_BLOCK_WORDS = 4
_BLOCK_BYTES = 16
_GUARD_WORDS = 2
_GUARD_BYTES = 4 * _GUARD_WORDS
_N_GUARDS = 6
_KEY_WORDS = 8
_N_MIN, _N_MAX = 2, 8
_REGION_MAX = _N_MAX * _BLOCK_WORDS

# Parameter block layout of km_aes_sram_cpu_rand_test.c (enum P_*).
P_MAGIC = 0xC5A3_E19B
_P_HDR_WORDS = 8 + _N_GUARDS + _N_GUARDS * _GUARD_WORDS

# CMD_KEY_LOAD success argument: KEY_HANDLE [7:0], REQ_SIZE [14:8],
# DEST_VALID [23:16]; CMD_KEY_TRANSFER success argument: KEY_HANDLE [7:0],
# DEST_ENGINE [15:8] (hw/ip/key_manager/doc/firmware.adoc, "Key-load success
# response" and "Key-transfer success response").
_ARG_HANDLE = (0, 8)
_LOAD_REQ_SIZE = (8, 7)
_LOAD_DEST = (16, 8)
_XFER_DEST = (8, 8)


def _bits(value: int, field: tuple[int, int]) -> int:
    lsb, width = field
    return (value >> lsb) & ((1 << width) - 1)


def _ctrl_field(value: int, name: str) -> int:
    return _bits(
        value,
        (AES.field_lsb("CTRL_SHADOWED", name), AES.field_width("CTRL_SHADOWED", name)),
    )


def _hex(words: list[int]) -> str:
    return "[" + ",".join(f"{w:08x}" for w in words) + "]"


def _le_bytes(words: list[int]) -> bytes:
    return b"".join((w & _M32).to_bytes(4, "little") for w in words)


def _ecb(key: list[int], words: list[int]) -> list[int]:
    out: list[int] = []
    for i in range(0, len(words), _BLOCK_WORDS):
        out += aes256_ecb_encrypt_words(key, words[i : i + _BLOCK_WORDS])
    return out


def _word(rng: SepSeededRng, avoid: set[int]) -> int:
    """A 32-bit word that is not 0 and not in ``avoid``."""
    while True:
        value = rng.getrandbits(32)
        if value != 0 and value not in avoid:
            return value


@dataclass
class _Plan:
    seed: int
    n: int
    base: int
    key: list[int]
    dkey: list[int]
    pt: list[int]
    enc_golden: list[int]
    dummy_golden: list[int]
    enc_fill: list[int]
    dec_fill: list[int]
    guard_vals: list[int]  # _GUARD_WORDS words per guard, in window order

    @staticmethod
    def window_bytes(n: int) -> int:
        return 3 * n * _BLOCK_BYTES + _N_GUARDS * _GUARD_BYTES

    @property
    def words(self) -> int:
        return self.n * _BLOCK_WORDS

    @property
    def src(self) -> int:
        return self.base + _GUARD_BYTES

    @property
    def enc(self) -> int:
        return self.src + self.n * _BLOCK_BYTES + 2 * _GUARD_BYTES

    @property
    def dec(self) -> int:
        return self.enc + self.n * _BLOCK_BYTES + 2 * _GUARD_BYTES

    @property
    def guard_addrs(self) -> list[int]:
        r = self.n * _BLOCK_BYTES
        return [
            self.base,
            self.src + r,
            self.enc - _GUARD_BYTES,
            self.enc + r,
            self.dec - _GUARD_BYTES,
            self.dec + r,
        ]

    @property
    def ctrl_enc(self) -> int:
        return build_aes_ctrl(sideload=True, operation=AES_OP_ENC, mode=AES_MODE_ECB)

    @property
    def ctrl_dec(self) -> int:
        return build_aes_ctrl(sideload=True, operation=AES_OP_DEC, mode=AES_MODE_ECB)

    def header(self) -> list[int]:
        return [
            P_MAGIC,
            self.seed & _M32,
            self.n,
            self.src,
            self.enc,
            self.dec,
            self.ctrl_enc,
            self.ctrl_dec,
            *self.guard_addrs,
            *self.guard_vals,
        ]

    def param_words(self) -> list[int]:
        pad = [0] * (_REGION_MAX - self.words)
        return (
            self.header()
            + self.key
            + self.dkey
            + self.pt
            + pad
            + self.enc_fill
            + pad
            + self.dec_fill
            + pad
        )


def draw_plan(seed: int) -> _Plan:
    """Key stream: key, dummy key. SRAM stream: n, window offset, plaintext,
    encrypt fill, decrypt fill, guards."""
    krng = SepSeededRng(seed ^ KMAES_KEY_SALT)
    key: list[int] = []
    for _ in range(_KEY_WORDS):
        key.append(_word(krng, set(key)))
    dkey = [_word(krng, {k}) for k in key]

    rng = SepSeededRng(seed ^ SRAM_SALT)
    n = rng.randrange(_N_MIN, _N_MAX + 1)
    slots = (SEP_SRAM_SIZE - _Plan.window_bytes(n)) // _GUARD_BYTES + 1
    base = SEP_SRAM_BASE + rng.randrange(slots) * _GUARD_BYTES
    pt = [_word(rng, set()) for _ in range(n * _BLOCK_WORDS)]
    enc_golden = _ecb(key, pt)
    enc_fill = [_word(rng, {g}) for g in enc_golden]
    dec_fill = [_word(rng, {p}) for p in pt]
    goldens = set(pt) | set(enc_golden)
    guard_vals = [_word(rng, goldens) for _ in range(_N_GUARDS * _GUARD_WORDS)]
    return _Plan(
        seed, n, base, key, dkey, pt, enc_golden, _ecb(dkey, pt), enc_fill, dec_fill, guard_vals
    )


@pyuvm.test()
class sep_km_aes_sram_cpu_rand_test(sep_base_test):
    """The SEP CPU moves SRAM blocks through AES under the KM key; ENC is the golden, DEC the plaintext."""

    build_env = False
    required_evidence = ("CHK-AES-SRAM-KM-CPU",)

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    # -- console records -----------------------------------------------------
    def _words(self, stage: str, part: str) -> list[int] | None:
        """Words of the INFO-KMAES-WORDS lines of ``stage``/``part`` in index
        order, or None when the lines are missing or not contiguous."""
        out: list[int] = []
        for rec in self.con.records("INFO-KMAES-WORDS"):
            kv = rec.kv
            if kv.get("stage") != stage or kv.get("part") != part:
                continue
            if int(kv.get("i", -1)) != len(out):
                return None
            for k in range(_BLOCK_WORDS):
                if f"w{k}" in kv:
                    out.append(kv[f"w{k}"])
        return out or None

    def _cmd(self, cmd: str, op: str | None = None) -> dict | None:
        for rec in self.con.records("INFO-KMAES-CMD"):
            if rec.kv.get("cmd") == cmd and (op is None or rec.kv.get("op") == op):
                return rec.kv
        return None

    def _keycrc(self) -> dict:
        for rec in self.con.records("INFO-KMAES-WORDS"):
            if rec.kv.get("part") == "keycrc":
                return rec.kv
        return {}

    # -- scenario ------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        chk = SepChkLog(self, TEST, seed)
        plan = draw_plan(seed)
        chk.info(
            "AES-SRAM-KM-CPU-PLAN",
            n=plan.n,
            window=f"0x{plan.base:08x}",
            src=f"0x{plan.src:08x}",
            enc=f"0x{plan.enc:08x}",
            dec=f"0x{plan.dec:08x}",
            window_bytes=_Plan.window_bytes(plan.n),
            key_sha=word_digest(plan.key),
            dkey_sha=word_digest(plan.dkey),
            key_salt=f"0x{KMAES_KEY_SALT:04x}",
            sram_salt=f"0x{SRAM_SALT:04x}",
        )

        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD
        self.write_efuse_image(image)
        dtcm = os.path.join(os.getcwd(), "sep_dtcm_kmaes.hex")
        patch_param_block(_DTCM_HEX, dtcm, P_MAGIC, plan.param_words())
        self.sb.expected_line = _BANNER
        self.con = SepFwConsole(self).start()
        # +esrc_noise_force routes this driver onto the ring-oscillator noise
        # input; without it the ESRC health window never fills.
        noise = self.start_esrc_noise_driver()
        boot_err: AssertionError | None = None
        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                dtcm,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
            )
        except AssertionError as exc:
            boot_err = exc
        finally:
            await noise.stop()
            await self.con.stop()

        for rec in self.con.records("INFO-KMAES-CMD"):
            chk.info(
                "KMAES-CMD",
                **{k: v if isinstance(v, str) else f"0x{v:08x}" for k, v in rec.kv.items()},
            )
        self._grade(chk, plan)
        if boot_err is not None:
            raise boot_err
        chk.finish(f"n={plan.n}")

    def _grade(self, chk: SepChkLog, plan: _Plan) -> None:
        # Parameter block echo and key CRCs.
        hdr = self._words("param", "hdr")
        crc = self._keycrc()
        kcrc_exp = crc32c(_le_bytes(plan.key))
        dcrc_exp = crc32c(_le_bytes(plan.dkey))
        chk.ctrl(
            "KMAES-PARAM",
            hdr == plan.header() and crc.get("kcrc") == kcrc_exp and crc.get("dcrc") == dcrc_exp,
            hdr_words=len(hdr or []),
            hdr_match=int(hdr == plan.header()),
            kcrc=f"0x{crc.get('kcrc', 0):08x}",
            kcrc_exp=f"0x{kcrc_exp:08x}",
            dcrc=f"0x{crc.get('dcrc', 0):08x}",
            dcrc_exp=f"0x{dcrc_exp:08x}",
        )

        # KM boot and the two KM commands.
        ready = self._cmd("ready")
        chk.ctrl(
            "KMAES-KM-READY",
            ready is not None and ready["rc"] == 0,
            rc=f"0x{ready['rc']:08x}" if ready else "absent",
        )
        load = self._cmd("load")
        load_arg = load["arg"] if load is not None else 0
        handle = _bits(load_arg, _ARG_HANDLE)
        chk.ctrl(
            "KMAES-KEY-LOAD",
            load is not None
            and load["rc"] == 0
            and _bits(load_arg, _LOAD_REQ_SIZE) == _KEY_WORDS - 1
            and _bits(load_arg, _LOAD_DEST) == KM_DEST_AES,
            rc=f"0x{load['rc']:08x}" if load else "absent",
            arg=f"0x{load_arg:08x}",
            handle=f"0x{handle:02x}",
            req_size=_bits(load_arg, _LOAD_REQ_SIZE),
            req_size_exp=_KEY_WORDS - 1,
            dest_valid=f"0x{_bits(load_arg, _LOAD_DEST):02x}",
            dest_exp=f"0x{KM_DEST_AES:02x}",
        )
        xfer = self._cmd("xfer")
        xfer_arg = xfer["arg"] if xfer is not None else 0
        chk.ctrl(
            "KMAES-KEY-XFER",
            xfer is not None
            and xfer["rc"] == 0
            and _bits(xfer_arg, _ARG_HANDLE) == handle
            and _bits(xfer_arg, _XFER_DEST) == KM_DEST_AES,
            rc=f"0x{xfer['rc']:08x}" if xfer else "absent",
            arg=f"0x{xfer_arg:08x}",
            handle=f"0x{_bits(xfer_arg, _ARG_HANDLE):02x}",
            handle_exp=f"0x{handle:02x}",
            dest_engine=f"0x{_bits(xfer_arg, _XFER_DEST):02x}",
            dest_exp=f"0x{KM_DEST_AES:02x}",
        )

        # CTRL_SHADOWED readback per leg.
        for op, operation in (("enc", AES_OP_ENC), ("dec", AES_OP_DEC)):
            rec = self._cmd("ctrl", op)
            ctrl = rec["arg"] if rec is not None else 0
            fields = {
                "sideload": _ctrl_field(ctrl, "sideload"),
                "key_len": _ctrl_field(ctrl, "key_len"),
                "mode": _ctrl_field(ctrl, "mode"),
                "operation": _ctrl_field(ctrl, "operation"),
            }
            exp = {
                "sideload": 1,
                "key_len": AES_KEY_LEN_256,
                "mode": AES_MODE_ECB,
                "operation": operation,
            }
            chk.ctrl(
                "KMAES-SIDELOAD",
                rec is not None and fields == exp,
                op=op,
                ctrl=f"0x{ctrl:08x}",
                **{k: f"0x{v:x}" for k, v in fields.items()},
                **{f"{k}_exp": f"0x{v:x}" for k, v in exp.items()},
            )

        # Pre-fill readback and the draw constraints that make the checks failable.
        gvals = plan.guard_vals
        pre = {p: self._words("pre", p) for p in ("src", "enc", "dec", "guard")}
        pre_exp = {"src": plan.pt, "enc": plan.enc_fill, "dec": plan.dec_fill, "guard": gvals}
        goldens = set(plan.pt) | set(plan.enc_golden)
        draw_ok = (
            all(f != 0 and f != g for f, g in zip(plan.enc_fill, plan.enc_golden))
            and all(f != 0 and f != p for f, p in zip(plan.dec_fill, plan.pt))
            and all(g != 0 and g not in goldens for g in gvals)
            and all(
                plan.dummy_golden[i : i + _BLOCK_WORDS] != plan.enc_golden[i : i + _BLOCK_WORDS]
                for i in range(0, plan.words, _BLOCK_WORDS)
            )
        )
        bad = [p for p in pre if pre[p] != pre_exp[p]]
        chk.ctrl(
            "AES-SRAM-CPU-PRE",
            not bad and draw_ok,
            words=sum(len(v) for v in pre_exp.values()),
            mismatch=bad,
            draw_ok=draw_ok,
            **{f"{p}_got": _hex(pre[p] or []) for p in pre},
        )

        # Graded: the two AES legs.
        enc_got = self._words("post", "enc")
        chk.ok(
            "AES-SRAM-KM-CPU",
            enc_got == plan.enc_golden,
            op="enc",
            n=plan.n,
            key_sha=word_digest(plan.key),
            got=_hex(enc_got or []),
            exp=_hex(plan.enc_golden),
            dummy_key_exp=_hex(plan.dummy_golden),
        )
        dec_got = self._words("post", "dec")
        chk.ok(
            "AES-SRAM-KM-CPU",
            dec_got == plan.pt,
            op="dec",
            n=plan.n,
            got=_hex(dec_got or []),
            exp=_hex(plan.pt),
        )

        src_got = self._words("post", "src")
        guard_got = self._words("post", "guard")
        chk.ctrl(
            "AES-SRAM-CPU-REGIONS",
            src_got == plan.pt and guard_got == gvals,
            part="src,guard",
            src_got=_hex(src_got or []),
            src_exp=_hex(plan.pt),
            guard_addrs=_hex(plan.guard_addrs),
            guard_got=_hex(guard_got or []),
            guard_exp=_hex(gvals),
        )

        for rec in self.con.records("INFO-AES-SRAM-KM-CPU-LAT"):
            chk.info("AES-SRAM-KM-CPU-LAT", unit="status_polls", **rec.kv)
