# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The core runs RV32 M, C, Zba, Zbb and Zbc, traps Zbs, keeps 16 distinct pmpaddr registers, and mrac grants no permission.

Firmware ``cpu_isa_pmp_csr_test`` is built for RV32I. Its only M, C, Zba, Zbb,
Zbc or Zbs encodings are the explicit instruction words of the table rows and
of ``bset`` (the crt0 start-up code before ``main`` and the completion code
after it are outside the graded window). This test draws the operands, the 16
``pmpaddr`` values, the four ``mrac`` values and the seeded SRAM words from the
run seed, computes the expected result of every row with an instruction model
written from the ratified ISA text (``env/sep_rv_isa_golden`` for M, Zba, Zbb
and Zbc, ``_c_model`` below for the four C rows), patches operands and
expected results into the DCCM parameter block before reset release, follows
the console (``env/sep_fw_console``: graded window on ``M G`` / ``M C``) and
counts the CPU trace retirements of the ``minstret`` block. It grades:

* CHK-ISA (host) every row result equals the model value; ``bset`` traps once
  with ``mcause`` 2 at the ``bset`` word; one row of each extension, re-run
  after the trap, equals the model value (control). The image holds each row
  encoding (checked against an independent encoder before the boot).
* CHK-PMP (host) the complement write of entry i changes the readback of entry
  i and leaves the other 15 readbacks unchanged, for every i; ``mseccfg``
  reads without a trap. Readbacks are logged and never compared with the
  drawn values or with each other: the implemented width and granularity are
  not claimed.
* CHK-MRAC (host) for each drawn ``mrac`` value the CSR reads back the drawn
  value, the user-mode load from the PMP-denied SRAM region traps with
  ``mcause`` 5 and the denied word does not reach its register; the
  allowed-region load of the same run returns the stored word (control). Each
  2-bit region field of a draw is 0b00, 0b01 or 0b10 (cpu.adoc, Memory
  attributes: a cacheability and a side-effect attribute per region); a field
  with both bits set, whose readback the specification does not state, is not
  drawn. A draw equal to the start-up value ``MRAC_BOOT`` is redrawn, so a
  core that ignores the write fails the readback.
* CHK-TRACE-INSTRET (host) the ``minstret`` delta over the straight-line block
  equals the retirements that the trace monitor counts from the first
  ``minstret`` read up to the second.

Expected values come from the drawn stimulus and the ISA model, never from a
DUT read. cpu run mode, ``+skip_fuse_sense``, Verilator and VCS.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import parse_hex_cells, patch_param_block
from env.sep_fcov_gate import close_graded_window
from env.sep_fw_console import SepFwConsole
from env.sep_rv_isa_golden import evaluate
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym

TEST = "sep_cpu_isa_pmp_csr_test"
_FW = "cpu_isa_pmp_csr_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", _FW)
_ITCM_HEX = os.path.join(_FW_DIR, f"{_FW}.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, f"{_FW}.dtcm.hex")
_BANNER = "SEP CPU ISA PMP CSR test"
_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
_SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
_MAX_RUN_CYCLES = 20_000_000
_NO_BOOT_CYCLES = 80_000
_M32 = 0xFFFF_FFFF

# Parameter block (fw/tests/cpu_isa_pmp_csr_test, enum P_*).
P_MAGIC = 0x3529A15A
NROW_MAX = 306
NCTRL = 5
NPMP = 16
NMRAC = 4
# The mrac value that fw/startup/crt0.s writes and the firmware restores after
# each mrac iteration.
MRAC_BOOT = 0xA8AAAAAA

# Two 4 KiB naturally aligned SRAM regions that the firmware uses for nothing
# else: the PMP-allowed and the PMP-denied region of the mrac step.
ALLOW_REG = _SRAM_BASE + _SRAM_SIZE - 0x2000
DENY_REG = _SRAM_BASE + _SRAM_SIZE - 0x1000

# RISC-V cause codes (Privileged Architecture, mcause table).
MCAUSE_ILLEGAL = 2
MCAUSE_LOAD_FAULT = 5


def _r_type(f7: int, f3: int, op: int = 0x33) -> int:
    """R-type word with rd = rs1 = a0 (x10), rs2 = a1 (x11)."""
    return (f7 << 25) | (11 << 20) | (10 << 15) | (f3 << 12) | (10 << 7) | op


def _i_unary(imm12: int, f3: int) -> int:
    """OP-IMM word with rd = rs1 = a0 and a fixed 12-bit function field."""
    return (imm12 << 20) | (10 << 15) | (f3 << 12) | (10 << 7) | 0x13


# Firmware op id order (exec_op), extension, ratified encoding with rd = rs1 =
# a0 and rs2 = a1. The C rows hold their immediates in the encoding:
# c.addi a0, -7 and c.slli a0, 13.
OPS: tuple[tuple[str, str, int, int], ...] = (
    ("mul", "M", _r_type(0x01, 0), 4),
    ("mulh", "M", _r_type(0x01, 1), 4),
    ("mulhsu", "M", _r_type(0x01, 2), 4),
    ("mulhu", "M", _r_type(0x01, 3), 4),
    ("div", "M", _r_type(0x01, 4), 4),
    ("divu", "M", _r_type(0x01, 5), 4),
    ("rem", "M", _r_type(0x01, 6), 4),
    ("remu", "M", _r_type(0x01, 7), 4),
    ("c.add", "C", (0b1001 << 12) | (10 << 7) | (11 << 2) | 0b10, 2),
    ("c.addi", "C", (0b000 << 13) | (1 << 12) | (10 << 7) | (0b11001 << 2) | 0b01, 2),
    ("c.sub", "C", (0b100011 << 10) | (2 << 7) | (0b00 << 5) | (3 << 2) | 0b01, 2),
    ("c.slli", "C", (0b000 << 13) | (0 << 12) | (10 << 7) | (13 << 2) | 0b10, 2),
    ("sh1add", "Zba", _r_type(0x10, 2), 4),
    ("sh2add", "Zba", _r_type(0x10, 4), 4),
    ("sh3add", "Zba", _r_type(0x10, 6), 4),
    ("andn", "Zbb", _r_type(0x20, 7), 4),
    ("orn", "Zbb", _r_type(0x20, 6), 4),
    ("xnor", "Zbb", _r_type(0x20, 4), 4),
    ("clz", "Zbb", _i_unary(0x600, 1), 4),
    ("ctz", "Zbb", _i_unary(0x601, 1), 4),
    ("cpop", "Zbb", _i_unary(0x602, 1), 4),
    ("min", "Zbb", _r_type(0x05, 4), 4),
    ("minu", "Zbb", _r_type(0x05, 5), 4),
    ("max", "Zbb", _r_type(0x05, 6), 4),
    ("maxu", "Zbb", _r_type(0x05, 7), 4),
    ("rol", "Zbb", _r_type(0x30, 1), 4),
    ("ror", "Zbb", _r_type(0x30, 5), 4),
    ("rev8", "Zbb", _i_unary(0x698, 5), 4),
    ("orc.b", "Zbb", _i_unary(0x287, 5), 4),
    ("sext.b", "Zbb", _i_unary(0x604, 1), 4),
    ("sext.h", "Zbb", _i_unary(0x605, 1), 4),
    ("clmul", "Zbc", _r_type(0x05, 1), 4),
    ("clmulh", "Zbc", _r_type(0x05, 3), 4),
    ("clmulr", "Zbc", _r_type(0x05, 2), 4),
)
BSET = ("bset", "Zbs", _r_type(0x14, 1), 4)
EXTS = ("M", "C", "Zba", "Zbb", "Zbc")
# Fixed corner pairs of every op: division by zero, the signed overflow case
# 0x8000_0000 / -1, and the corner values 0, 1, 0xFFFF_FFFF and 0x8000_0000.
CORNERS = (
    (0, 1),
    (1, 0),
    (0xFFFF_FFFF, 0x8000_0000),
    (0x8000_0000, 0xFFFF_FFFF),
    (0xFFFF_FFFF, 0xFFFF_FFFF),
    (0x8000_0000, 0),
)
N_SEEDED = 3


def _c_model(op: str, a: int, b: int) -> int:
    """The four C rows, from the RVC expansions of the ratified ISA text:
    c.add rd = rd + rs2, c.addi rd = rd + sext(nzimm), c.sub rd' = rd' - rs2',
    c.slli rd = rd << shamt."""
    if op == "c.add":
        return (a + b) & _M32
    if op == "c.addi":
        return (a - 7) & _M32
    if op == "c.sub":
        return (a - b) & _M32
    if op == "c.slli":
        return (a << 13) & _M32
    raise KeyError(op)


def model(op: str, a: int, b: int) -> int:
    return _c_model(op, a, b) if op.startswith("c.") else evaluate(op, a, b)


def load_symbols(fw_dir: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for path in glob.glob(os.path.join(fw_dir, f"{_FW}*.sym")):
        with open(path) as fh:
            for line in fh:
                parts = line.split()
                if len(parts) == 3:
                    try:
                        out[parts[2]] = int(parts[0], 16)
                    except ValueError:
                        continue
    return out


@dataclass
class IsaCfg:
    """The seeded stimulus. A pure function of the run seed."""

    seed: int
    rows: list[tuple[int, int, int, int]] = field(default_factory=list)  # op id, a, b, exp
    ctrl: list[int] = field(default_factory=list)
    pmp: list[int] = field(default_factory=list)
    mrac: list[int] = field(default_factory=list)
    aw: list[int] = field(default_factory=list)
    dw: list[int] = field(default_factory=list)

    @classmethod
    def from_seed(cls, seed: int) -> "IsaCfg":
        rng = SepSeededRng(seed)
        cfg = cls(seed)
        for k, (name, _ext, _enc, _len) in enumerate(OPS):
            pairs = list(CORNERS) + [
                (rng.getrandbits(32), rng.getrandbits(32)) for _ in range(N_SEEDED)
            ]
            for a, b in pairs:
                cfg.rows.append((k, a, b, model(name, a, b)))
        for ext in EXTS:
            idx = [i for i, r in enumerate(cfg.rows) if OPS[r[0]][1] == ext]
            cfg.ctrl.append(rng.choice(idx))
        while len(cfg.pmp) < NPMP:
            v = rng.getrandbits(32)
            if v not in cfg.pmp:  # a draw equal to an earlier one is redrawn
                cfg.pmp.append(v)
        while len(cfg.mrac) < NMRAC:
            v = sum(rng.choice((0, 1, 2)) << (2 * r) for r in range(16))
            if v != MRAC_BOOT:  # a draw equal to the start-up value is redrawn
                cfg.mrac.append(v)
        for _ in range(NMRAC):
            aw = rng.getrandbits(32) | 1
            dw = rng.getrandbits(32) | 1
            while dw == aw:
                dw = rng.getrandbits(32) | 1
            cfg.aw.append(aw)
            cfg.dw.append(dw)
        return cfg

    def words(self) -> list[int]:
        out = [P_MAGIC, self.seed & _M32, len(self.rows)]
        out += self.ctrl
        out += self.pmp + self.mrac + self.aw + self.dw
        out += [ALLOW_REG, DENY_REG]
        for r in self.rows:
            out += list(r)
        out += [0] * (4 * (NROW_MAX - len(self.rows)))
        return out

    def draw_lines(self) -> list[str]:
        out = [
            f"DRAW rows={len(self.rows)} corners={len(CORNERS)} seeded_per_op={N_SEEDED} "
            f"ctrl_rows={','.join(str(i) for i in self.ctrl)}",
            "DRAW pmpaddr=" + ",".join(f"0x{v:08x}" for v in self.pmp),
            "DRAW mrac=" + ",".join(f"0x{v:08x}" for v in self.mrac),
            "DRAW allowed_words="
            + ",".join(f"0x{v:08x}" for v in self.aw)
            + " denied_words="
            + ",".join(f"0x{v:08x}" for v in self.dw)
            + f" allowed_region=0x{ALLOW_REG:08x} denied_region=0x{DENY_REG:08x}",
        ]
        return out


def _image_bytes(path: str) -> bytes:
    cells = parse_hex_cells(path)
    top = max(cells) + 1
    return bytes(cells.get(a, 0) for a in range(top))


def _list(kv: dict) -> list[int]:
    return [int(kv[f"r{i}"]) for i in range(NPMP)]


@pyuvm.test()
class sep_cpu_isa_pmp_csr_test(sep_base_test):
    """RV32 M/C/Zba/Zbb/Zbc results, the Zbs trap, pmpaddr non-aliasing, mrac and minstret."""

    build_env = False
    required_evidence = ("CHK-ISA", "CHK-PMP", "CHK-MRAC", "CHK-TRACE-INSTRET")

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def _trace(self, pc1: int, pc2: int) -> None:
        """Count the retirements from the record at ``pc1`` up to, and not
        including, the record at ``pc2``. Exception and interrupt records are
        counted apart."""
        dut = cocotb.top
        counting = False
        n = 0
        events = 0
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if not int(dut.cpu_trace_valid_o.value):
                continue
            pc = int(dut.cpu_trace_addr_o.value) & _M32
            ev = int(dut.dbg_cpu_trace_exc_o.value) or int(dut.cpu_trace_interrupt_o.value)
            if not counting and pc == pc1 and not ev:
                counting = True
                n = 0
                events = 0
            if counting:
                if pc == pc2 and not ev:
                    self.trace_window = (n, events)
                    return
                if ev:
                    events += 1
                else:
                    n += 1

    def _check_image(self) -> None:
        """Each row encoding and the bset word are in the instruction image."""
        img = _image_bytes(_ITCM_HEX)
        missing = []
        for name, _ext, enc, ln in OPS + (BSET,):
            if img.find(enc.to_bytes(ln, "little")) < 0:
                missing.append(name)
        if missing:
            raise AssertionError(f"instruction image lacks the encodings of {missing}")
        self.logger.info(
            "CTL-ISA-ENC LOG encodings_in_image=%d/%d (independent encoder)",
            len(OPS) + 1,
            len(OPS) + 1,
        )

    def _chk_isa(self, sy: dict[str, int]) -> int:
        cfg = self.tcfg
        rows = [r.kv for r in self._recs("ROW")]
        if len(rows) != len(cfg.rows):
            raise AssertionError(f"CHK-ISA FAIL: {len(rows)} ROW lines, table has {len(cfg.rows)}")
        bad = []
        per_ext = dict.fromkeys(EXTS, 0)
        for i, (kv, (op, a, b, exp)) in enumerate(zip(rows, cfg.rows, strict=True)):
            got = int(kv["r"])
            if int(kv["i"]) != i or int(kv["op"]) != op or got != exp:
                bad.append(
                    f"row={i} op={OPS[op][0]} a=0x{a:08x} b=0x{b:08x} exp=0x{exp:08x} got=0x{got:08x}"
                )
            per_ext[OPS[op][1]] += 1
        zbs = self._recs("ZBS")
        if len(zbs) != 1:
            raise AssertionError(f"CHK-ISA FAIL: {len(zbs)} ZBS lines")
        z = zbs[0].kv
        pc = sy["isa_bset"]
        zbs_ok = (
            int(z["traps"]) == 1 and int(z["mcause"]) == MCAUSE_ILLEGAL and int(z["mepc"]) == pc
        )
        crows = [r.kv for r in self._recs("CROW")]
        ctrl_bad = []
        for kv, idx in zip(crows, cfg.ctrl, strict=False):
            op, a, b, exp = cfg.rows[idx]
            if int(kv["i"]) != idx or int(kv["r"]) != exp:
                ctrl_bad.append(
                    f"row={idx} op={OPS[op][0]} exp=0x{exp:08x} got=0x{int(kv['r']):08x}"
                )
        if len(crows) != NCTRL:
            ctrl_bad.append(f"{len(crows)} CROW lines, expected {NCTRL}")
        body = (
            "; ".join(f"ext={e} ops={per_ext[e]} ok" for e in EXTS)
            + f"; Zbs mcause=0x{int(z['mcause']):x} traps={int(z['traps'])} mepc=0x{int(z['mepc']):08x}"
            f" bset_pc=0x{pc:08x}; control_rows={NCTRL - len(ctrl_bad)}/{NCTRL} ok"
        )
        if bad or not zbs_ok or ctrl_bad:
            raise AssertionError(
                f"CHK-ISA FAIL seed={cfg.seed}: {body}; wrong rows: {bad[:8]} ({len(bad)} total); "
                f"control: {ctrl_bad}"
            )
        self.logger.info("CHK-ISA PASS: seed=%d %s", cfg.seed, body)
        return 1

    def _chk_pmp(self) -> int:
        p0 = self._recs("PMP0")
        pc = self._recs("PMPC")
        ms = self._recs("MSECCFG")
        if len(p0) != 1 or len(pc) != NPMP or len(ms) != 1:
            raise AssertionError(
                f"CHK-PMP FAIL: {len(p0)} PMP0, {len(pc)} PMPC, {len(ms)} MSECCFG lines"
            )
        prev = _list(p0[0].kv)
        changed = 0
        unchanged = 0
        aliases = []
        for i, rec in enumerate(pc):
            if int(rec.kv["i"]) != i:
                raise AssertionError(f"CHK-PMP FAIL: PMPC line {i} has i={rec.kv['i']}")
            cur = _list(rec.kv)
            self.logger.info(
                "OBS-PMP-READBACK LOG after_complement=%d readback=%s",
                i,
                ",".join(f"0x{v:08x}" for v in cur),
            )
            if cur[i] != prev[i]:
                changed += 1
            others = [j for j in range(NPMP) if j != i and cur[j] != prev[j]]
            if others:
                aliases.append((i, others))
            else:
                unchanged += 1
            prev = cur
        ms_traps = int(ms[0].kv["traps"])
        lst = ",".join(f"0x{v:08x}" for v in _list(p0[0].kv))
        body = (
            f"entries={NPMP} complement_changed={changed} others_unchanged={unchanged} "
            f"aliases={len(aliases)} readback={lst}; mseccfg=0x{int(ms[0].kv['v']):08x} "
            f"mseccfg_traps={ms_traps}"
        )
        if changed != NPMP or unchanged != NPMP or aliases or ms_traps != 0:
            raise AssertionError(f"CHK-PMP FAIL: {body} alias_detail={aliases}")
        self.logger.info("CHK-PMP PASS: %s; mseccfg read ok", body)
        return 1

    def _chk_mrac(self) -> int:
        cfg = self.tcfg
        recs = self._recs("MRAC")
        if len(recs) != NMRAC:
            raise AssertionError(f"CHK-MRAC FAIL: {len(recs)} MRAC lines, expected {NMRAC}")
        for j, rec in enumerate(recs):
            kv = rec.kv
            mc = int(kv["mcause"])
            rok = int(kv["rok"])
            rden = int(kv["rden"])
            body = (
                f"mrac=0x{cfg.mrac[j]:08x} mrac_readback=0x{int(kv['rb']):08x} denied "
                f"mcause=0x{mc:x} traps={int(kv['traps'])} allowed_reg=0x{rok:08x} "
                f"allowed_word=0x{cfg.aw[j]:08x} denied_reg=0x{rden:08x} "
                f"denied_word=0x{cfg.dw[j]:08x}"
            )
            ok = (
                int(kv["j"]) == j
                and int(kv["v"]) == cfg.mrac[j]
                and int(kv["rb"]) == cfg.mrac[j]
                and mc == MCAUSE_LOAD_FAULT
                and int(kv["traps"]) == 1
                and rok == cfg.aw[j]
                and rden != cfg.dw[j]
            )
            if not ok:
                raise AssertionError(f"CHK-MRAC FAIL: {body}")
            self.logger.info("CHK-MRAC PASS: %s allowed=ok", body)
        return NMRAC

    def _chk_instret(self, sy: dict[str, int]) -> int:
        recs = self._recs("INSTRET")
        if len(recs) != 1:
            raise AssertionError(f"CHK-TRACE-INSTRET FAIL: {len(recs)} INSTRET lines")
        kv = recs[0].kv
        if int(kv["pc1"]) != sy["isa_r1"] or int(kv["pc2"]) != sy["isa_r2"]:
            raise AssertionError(
                f"CHK-TRACE-INSTRET FAIL: firmware block 0x{int(kv['pc1']):08x}-"
                f"0x{int(kv['pc2']):08x} disagrees with the symbol listing"
            )
        delta = (int(kv["r2"]) - int(kv["r1"])) & _M32
        win = getattr(self, "trace_window", None)
        if win is None:
            raise AssertionError("CHK-TRACE-INSTRET FAIL: the trace never retired the block")
        n, events = win
        body = (
            f"delta_instret={delta} trace_retires={n} trace_events={events} "
            f"r1=0x{int(kv['r1']):08x} r2=0x{int(kv['r2']):08x}"
        )
        if delta != n or n == 0 or events:
            raise AssertionError(f"CHK-TRACE-INSTRET FAIL: {body}")
        self.logger.info("CHK-TRACE-INSTRET PASS: %s", body)
        return 1

    def _recs(self, prefix: str):
        from env.sep_fw_console import ConsoleRec, parse_kv

        out = []
        for clk, text in self.con.lines:
            if text.split(" ", 1)[0] == prefix:
                out.append(ConsoleRec(clk, prefix, "LOG", parse_kv(text), text))
        return out

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.tcfg = cfg = IsaCfg.from_seed(seed)
        self.logger.info("SEED seed=%d", seed)
        for line in cfg.draw_lines():
            self.logger.info("%s", line)
        sy = load_symbols(_FW_DIR)
        need = ("isa_r1", "isa_r2", "isa_bset", "umode_stub", "trap_entry")
        missing = [n for n in need if n not in sy]
        if missing:
            raise AssertionError(f"firmware symbol listing lacks {missing} in {_FW_DIR}")
        if sy["umode_stub"] & 0xFFF:
            raise AssertionError(f"umode_stub 0x{sy['umode_stub']:08x} is not 4 KiB aligned")
        self._check_image()
        dtcm = os.path.join(os.getcwd(), "sep_dtcm_isa_pmp.hex")
        patch_param_block(_DTCM_HEX, dtcm, P_MAGIC, cfg.words())
        self.sb.expected_line = _BANNER
        self.con = SepFwConsole(self, graded_test=TEST).start()
        tr = cocotb.start_soon(self._trace(sy["isa_r1"], sy["isa_r2"]))
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
            tr.cancel()
            await self.con.stop()
        assert self.sb.fw_done and self.sb.fw_pass, "firmware did not complete with PASS"
        seeds = self.con.text_lines("SEED")
        if not seeds or f"seed=0x{seed & _M32:08x}" not in seeds[0]:
            raise AssertionError(f"firmware did not run the patched block: {seeds}")
        n = self._chk_isa(sy) + self._chk_pmp() + self._chk_mrac() + self._chk_instret(sy)
        self.result_pass(TEST, seed, n)
