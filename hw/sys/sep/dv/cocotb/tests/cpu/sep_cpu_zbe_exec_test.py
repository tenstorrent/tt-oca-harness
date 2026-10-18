# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The core executes the Zbe instructions bext (bit extract), bdep (bit deposit), pack and packh.

``hw/sys/sep/doc/cpu.adoc`` (Processor Core) states that Zbe is enabled and
gives no encodings. The encodings and the result functions come from the draft,
unratified "RISC-V Bitmanip Extension" specification v0.93 (January 2021):
Table 2.1 (Zbe on RV32 = bext, bdep, pack, packh), section 2.5 (bext, bdep),
section 2.1.4 (pack, packh) and section 2.12 (opcode encodings). The draft also
names the Zbs single-bit extract ``bext``; that is another encoding, and this
test never emits it.

Firmware ``cpu_zbe_exec_test`` is built for RV32I. Its only Zbe encodings are
the explicit instruction words of its table rows. This test draws the operand
rows from the run seed (fixed corner pairs plus seeded dense and sparse rows),
patches them into the DCCM parameter block before reset release, and follows
the console (``env/sep_fw_console``: graded window on ``M G`` / ``M C``). It
grades:

* CHK-ZBE (host) every row result equals the value of the instruction model
  below, written from the v0.93 result functions. A word that the core does
  not execute traps to the crt0 handler, and the run fails. The image holds
  each row encoding (checked against an independent encoder before the boot).

``pack`` is never encoded with rs2 = x0: that word is ``zext.h`` (Zbb).
Expected values come from the drawn operands and the model, never from a DUT
read. cpu run mode, ``+skip_fuse_sense``, Verilator and VCS.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import parse_hex_cells, patch_param_block
from env.sep_fcov_gate import close_graded_window
from env.sep_fw_console import SepFwConsole
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym

TEST = "sep_cpu_zbe_exec_test"
_FW = "cpu_zbe_exec_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", _FW)
_ITCM_HEX = os.path.join(_FW_DIR, f"{_FW}.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, f"{_FW}.dtcm.hex")
_BANNER = "SEP CPU Zbe exec test"
_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 10_000_000
_NO_BOOT_CYCLES = 80_000
_M32 = 0xFFFF_FFFF
XLEN = 32

# Parameter block (fw/tests/cpu_zbe_exec_test, enum P_*).
P_MAGIC = 0x2BE0E7EC
NROW_MAX = 160


def _r_type(f7: int, f3: int) -> int:
    """OP word (opcode 0110011) with rd = rs1 = a0 (x10), rs2 = a1 (x11)."""
    return (f7 << 25) | (11 << 20) | (10 << 15) | (f3 << 12) | (10 << 7) | 0x33


# Firmware op id order (exec_op), name, v0.93 section 2.12 encoding.
OPS: tuple[tuple[str, int], ...] = (
    ("bext", _r_type(0b0000100, 0b110)),
    ("bdep", _r_type(0b0100100, 0b110)),
    ("pack", _r_type(0b0000100, 0b100)),
    ("packh", _r_type(0b0000100, 0b111)),
)
# Every pair of the corner values 0, 1, 0xFFFF_FFFF and 0x8000_0000.
CORNER_VALUES = (0, 1, 0xFFFF_FFFF, 0x8000_0000)
CORNERS = tuple((a, b) for a in CORNER_VALUES for b in CORNER_VALUES)
N_DENSE = 4  # seeded rows with uniform operands
N_SPARSE = 4  # seeded rows whose mask rs2 has about one bit set in eight


def _bext(rs1: int, rs2: int) -> int:
    """v0.93 section 2.5: collect the bits of rs1 at the set bits of rs2, LSB-justified."""
    r = 0
    j = 0
    for i in range(XLEN):
        if (rs2 >> i) & 1:
            if (rs1 >> i) & 1:
                r |= 1 << j
            j += 1
    return r


def _bdep(rs1: int, rs2: int) -> int:
    """v0.93 section 2.5: write the LSB-justified bits of rs1 at the set bits of rs2."""
    r = 0
    j = 0
    for i in range(XLEN):
        if (rs2 >> i) & 1:
            if (rs1 >> j) & 1:
                r |= 1 << i
            j += 1
    return r


def _pack(rs1: int, rs2: int) -> int:
    """v0.93 section 2.1.4: the XLEN/2-bit lower halves, rs1 low and rs2 high."""
    lower = ((rs1 << (XLEN // 2)) & _M32) >> (XLEN // 2)
    upper = (rs2 << (XLEN // 2)) & _M32
    return lower | upper


def _packh(rs1: int, rs2: int) -> int:
    """v0.93 section 2.1.4: the LSB bytes of rs1 and rs2 in rd[15:0], rest zero."""
    return (rs1 & 255) | ((rs2 & 255) << 8)


MODEL = {"bext": _bext, "bdep": _bdep, "pack": _pack, "packh": _packh}


@dataclass
class ZbeCfg:
    """The seeded stimulus. A pure function of the run seed."""

    seed: int
    rows: list[tuple[int, int, int, int]] = field(default_factory=list)  # op id, a, b, exp

    @classmethod
    def from_seed(cls, seed: int) -> "ZbeCfg":
        rng = SepSeededRng(seed)
        cfg = cls(seed)
        for k, (name, _enc) in enumerate(OPS):
            pairs = list(CORNERS)
            pairs += [(rng.getrandbits(32), rng.getrandbits(32)) for _ in range(N_DENSE)]
            pairs += [
                (
                    rng.getrandbits(32),
                    rng.getrandbits(32) & rng.getrandbits(32) & rng.getrandbits(32),
                )
                for _ in range(N_SPARSE)
            ]
            for a, b in pairs:
                cfg.rows.append((k, a, b, MODEL[name](a, b)))
        return cfg

    def words(self) -> list[int]:
        out = [P_MAGIC, self.seed & _M32, len(self.rows)]
        for op, a, b, _exp in self.rows:
            out += [op, a, b]
        out += [0] * (3 * (NROW_MAX - len(self.rows)))
        return out


def _image_bytes(path: str) -> bytes:
    cells = parse_hex_cells(path)
    top = max(cells) + 1
    return bytes(cells.get(a, 0) for a in range(top))


@pyuvm.test()
class sep_cpu_zbe_exec_test(sep_base_test):
    """Zbe bext (bit extract), bdep (bit deposit), pack and packh results."""

    build_env = False
    required_evidence = ("CHK-ZBE",)

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _check_image(self) -> None:
        """Each row encoding is in the instruction image."""
        img = _image_bytes(_ITCM_HEX)
        missing = [name for name, enc in OPS if img.find(enc.to_bytes(4, "little")) < 0]
        if missing:
            raise AssertionError(f"instruction image lacks the encodings of {missing}")
        self.logger.info(
            "CTL-ZBE-ENC LOG encodings_in_image=%d/%d (independent encoder) %s",
            len(OPS),
            len(OPS),
            " ".join(f"{name}=0x{enc:08x}" for name, enc in OPS),
        )

    def _recs(self, prefix: str):
        from env.sep_fw_console import ConsoleRec, parse_kv

        out = []
        for clk, text in self.con.lines:
            if text.split(" ", 1)[0] == prefix:
                out.append(ConsoleRec(clk, prefix, "LOG", parse_kv(text), text))
        return out

    def _chk_zbe(self) -> int:
        cfg = self.tcfg
        rows = [r.kv for r in self._recs("ROW")]
        if len(rows) != len(cfg.rows):
            raise AssertionError(f"CHK-ZBE FAIL: {len(rows)} ROW lines, table has {len(cfg.rows)}")
        bad = []
        per_op = dict.fromkeys((name for name, _enc in OPS), 0)
        for i, (kv, (op, a, b, exp)) in enumerate(zip(rows, cfg.rows, strict=True)):
            got = int(kv["r"])
            if int(kv["i"]) != i or int(kv["op"]) != op or got != exp:
                bad.append(
                    f"row={i} op={OPS[op][0]} a=0x{a:08x} b=0x{b:08x} exp=0x{exp:08x} got=0x{got:08x}"
                )
            per_op[OPS[op][0]] += 1
        body = " ".join(f"{name}_rows={n}" for name, n in per_op.items())
        if bad:
            raise AssertionError(
                f"CHK-ZBE FAIL seed={cfg.seed}: {body}; wrong rows: {bad[:8]} ({len(bad)} total)"
            )
        sample = "; ".join(
            f"row={i} {OPS[op][0]} a=0x{a:08x} b=0x{b:08x} exp=0x{exp:08x} got=0x{int(kv['r']):08x}"
            for i, (kv, (op, a, b, exp)) in enumerate(zip(rows, cfg.rows, strict=True))
            if (a, b) == (0xFFFF_FFFF, 0x8000_0000)
        )
        self.logger.info(
            "CHK-ZBE PASS: seed=%d rows=%d %s all_equal_model; corner %s",
            cfg.seed,
            len(cfg.rows),
            body,
            sample,
        )
        return 1

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.tcfg = cfg = ZbeCfg.from_seed(seed)
        if len(cfg.rows) > NROW_MAX:
            raise AssertionError(f"{len(cfg.rows)} rows exceed the firmware table of {NROW_MAX}")
        self.logger.info("SEED seed=%d", seed)
        self.logger.info(
            "DRAW rows=%d corners_per_op=%d dense_per_op=%d sparse_per_op=%d",
            len(cfg.rows),
            len(CORNERS),
            N_DENSE,
            N_SPARSE,
        )
        self._check_image()
        dtcm = os.path.join(os.getcwd(), "sep_dtcm_zbe_exec.hex")
        patch_param_block(_DTCM_HEX, dtcm, P_MAGIC, cfg.words())
        self.sb.expected_line = _BANNER
        self.con = SepFwConsole(self, graded_test=TEST).start()
        close_graded_window(self.logger)
        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                dtcm,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
            )
        finally:
            await self.con.stop()
        assert self.sb.fw_done and self.sb.fw_pass, "firmware did not complete with PASS"
        seeds = self.con.text_lines("SEED")
        if not seeds or f"seed=0x{seed & _M32:08x}" not in seeds[0]:
            raise AssertionError(f"firmware did not run the patched block: {seeds}")
        self.result_pass(TEST, seed, self._chk_zbe())
