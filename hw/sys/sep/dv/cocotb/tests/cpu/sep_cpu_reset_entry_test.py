# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CPU reset entry: default vector, reset-vector TDR redirect and persistence, TAP reset scope.

The test stages three code images by backdoor and drives the reset, run-request
and core TAP pins. The boot ROM holds code at 0x1004_0000 that stores marker
``M_ROM`` to the outbound mailbox; the SRAM holds code at the drawn vectors
``A1`` and ``A2`` that stores ``M1`` and ``M2``. Each sequence then jumps to one
common retention routine in the SRAM. The routine stores the entry values of
the first word of both scratch banks, ``WKUP_THOLD_LO`` and ``SEP_SW_DEBUG``,
writes a unique non-zero value to each, and then loops: it reads the four back,
compares them with the written values and stores a pass count (or a fail
record with the mismatch mask). The marker and routine words are read on the
PR-OUT tap (outbound write address and data). One sampler reads the CPU trace
port, the ``rom_req`` and ``ifu_req`` taps and the ``sep_cpu_reset_n`` and
``sep_reset_n`` taps on every ``clk_i`` rising edge for the whole leaf.

Checks:
  CHK-RSTVEC-DEFAULT : after each cold reset with run request 1 and the
                       default TDR, the first retired PC is 0x1004_0000 and the
                       marker is ``M_ROM`` (rom.adoc Boot ROM; cpu.adoc Reset
                       Vector).
  CHK-RSTVEC         : after the TDR (IR 0x18) is shifted with ``A1`` and then
                       ``A2`` while the CPU is in reset, the first retired PC is
                       that vector and the marker is the one planted there.
  CHK-RSTVEC-PERSIST : after a ``wdt_rst_ni`` CPU reset the first retired PC is
                       ``A1`` again.
  CHK-RSTVEC-TAPRST  : after a TAP reset (``jtag_trst_ni`` or Test-Logic-Reset)
                       and a CPU reset the first retired PC is 0x1004_0000 and
                       the marker is ``M_ROM``, with the TDR at its default or
                       holding ``A2`` before the TAP reset.
  CHK-TRST-SCOPE     : during each TAP reset the ``sep_reset_n`` and
                       ``sep_cpu_reset_n`` taps stay high, the routine reports
                       two more passes with all four compares true and
                       ``scratch_cold_probe_o`` word 0 does not change. Control:
                       the CPU reset that follows clears the warm scratch word,
                       keeps the cold one and moves the ``sep_cpu_reset_n`` tap.
  CHK-NO-EARLY-RETIRE: no trace beat while the ``sep_cpu_reset_n`` tap is low,
                       in every cold reset and every CPU reset of the leaf.
  CHK-NO-EARLY-FETCH : no ``rom_req`` or ``ifu_req`` request while the
                       ``sep_cpu_reset_n`` tap is low, in the same resets.
  CTL-RUNREQ         : (control) the first retirement falls inside the
                       observation window after the tap rise, for the drawn
                       ``ext_boot_seq_done_i`` delay and for the zero delay.
  CHK-WDT-STORE-RESP : every write to a WDT register pair (``WKUP_THOLD_HI/LO``,
                       ``WKUP_COUNT_HI/LO``, ``WDOG_BARK/BITE_THOLD``) ends with
                       BRESP OKAY and the written value reads back: (a) one
                       full-strobe 64-bit write per pair from the debug-module
                       system bus, (b) a CPU 32-bit store to the even word,
                       (c) a CPU 32-bit store to the odd word. One line per
                       access (watchdog.adoc Bus Interface: the 64-bit port is
                       narrowed to the 32-bit ``aon_timer`` register block).
                       Graded last, after every other check.

Every CPU reset is applied at a quiet point: after a pass-count store of the
routine has its write response, while the core runs the routine spin loop in
the SRAM. No load or store is then in flight, and an in-flight instruction
fetch goes to the SRAM, not to ``rom_req``. The SRAM images are written again
while each cold reset holds ``rst_ni`` low, because the SRAM content across a
cold reset is not stated.

The expected vectors come from the specification (0x1004_0000) and the drawn
``A1``/``A2``; the markers and written values come from the staged images. No
expected value is read from the DUT.

The core TAP pins are bench-owned for the whole leaf. At power-on
``jtag_trst_ni`` presents 1 and then 0, so the asynchronous TAP reset fires,
and it stays low through the three cold resets. From step 7 the TAP is driven
through ``env/sep_jtag_dmi`` on the shared ``OcahJtagMasterDriver``, with a TCK
period of the drawn number of ``clk_i`` periods.

The routine programs ``SEP_NMI_VEC`` with a handler in the SRAM before it arms
the registers. A store that ends in a bus error raises an NMI on VeeR EL2; the
handler stores ``mcause`` and ``mdseac`` to the mailbox, unlocks ``mdseac`` and
returns, and the leaf logs each record (``OBS-STORE-BUS-ERR``). The retention
compares, not the bus response, decide whether a register holds its value.

The WDT store leg runs after the last scope leg. The bench sets a flag word in
the SRAM; the routine reads it after each spin and jumps to the store routine,
which issues the (b) and (c) stores, reads each register back and stores the
read value to the mailbox, then idles in a self-loop. The CPU issues no 8-byte
store (RV32), so the full 64-bit write (a) comes from the debug-module system
bus (``sbaccess`` 64) through the core TAP with ``dmi_core_enable_i`` at 1, and
read back the same way. The write address, size, strobe and BRESP of each access
are read on the PR-LSU-XBAR tap (CPU) and the PR-DBG-SB tap (system bus). The
WDT is idle in this leaf (``WKUP_CTRL`` and ``WDOG_CTRL`` keep their reset
values, ``enable`` 0), so the six registers are plain read-write storage
(integration/rdl/sep/aon_timer.rdl: 32-bit ``sw = rw`` fields). The other
64-bit-aligned pairs are not written: ``ALERT_TEST`` and ``INTR_TEST`` are
write-only, ``WKUP_CTRL`` and ``WDOG_CTRL`` start the counters,
``WDOG_REGWEN``, ``INTR_STATE`` and ``WKUP_CAUSE`` clear on write.

cpu run mode (real core), ``+skip_fuse_sense``; Verilator and VCS.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import RegBlock, sym

TEST = "sep_cpu_reset_entry_test"

# hw/sys/sep/doc/rom.adoc (Boot ROM) and hw/sys/sep/doc/cpu.adoc (Reset Vector):
# the first CPU fetch after reset with the default TDR is at the boot ROM base.
DEFAULT_RESET_PC = 0x1004_0000
ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
ROM_WORDS = sym("SEP_BOOT_ROM_MEM_SIZE") // 8
SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_WORDS = sym("SEP_SRAM_MEM_SIZE") // 8
if ROM_BASE != DEFAULT_RESET_PC:
    raise RuntimeError(f"the ROM image base 0x{ROM_BASE:08x} is not the stated reset PC")

# Vector range of the contract (halfword aligned), and the routine address,
# below the vector range so no drawn image overlaps it.
VEC_LO = 0x1000_1000
VEC_HI = 0x1003_F000
ROUTINE = SRAM_BASE + 0x400
NMI_HANDLER = SRAM_BASE + 0x300
# Store-leg flag (one 64-bit SRAM word, written by backdoor) and store routine.
ST_FLAG = SRAM_BASE + 0x100
STORE_RT = SRAM_BASE + 0xC00

_CPU_CTRL = RegBlock("SEP_CPU_CTRL")
_WDT = RegBlock("WDT_TIMER")
_COLD = RegBlock("SEP_SCRATCH_COLD")
_WARM = RegBlock("SEP_SCRATCH_WARM")
_OUTF = RegBlock("OUTBOUND_FILTER_CTRL_0_")

# Outbound mailbox (tb/sep_outbound_mbx.sv: STDOUT is the SMU_GLOBAL_BASE_ADDR
# reset value). The routine stores 32-bit words at these offsets.
MBX = _CPU_CTRL.reset("SMU_GLOBAL_BASE_ADDR") & _CPU_CTRL.mask("SMU_GLOBAL_BASE_ADDR")
OFF_MARK = 0x10
OFF_ENTRY = (0x20, 0x24, 0x28, 0x2C)
OFF_PASS = 0x30
OFF_FAIL = 0x34
OFF_NMI_CAUSE = 0x38
OFF_NMI_ADDR = 0x3C
OFF_ST_RD = 0x40
OFF_ST_DONE = 0x44
ST_DONE = 0x5D0E_0519
MARKERS = {"M_ROM": 0x4D52_4F4D, "M1": 0x4D31_0001, "M2": 0x4D32_0002}
MARKER_NAME = {v: k for k, v in MARKERS.items()}

# The four armed registers, in routine order, with the unique value written.
ARMED = (
    ("SCRATCH_COLD_0", _COLD.addr("SCRATCH_0_"), _COLD.mask("SCRATCH_0_"), 0xC01D_5C01),
    ("SCRATCH_WARM_0", _WARM.addr("SCRATCH_0_"), _WARM.mask("SCRATCH_0_"), 0x3A3D_5C02),
    ("WKUP_THOLD_LO", _WDT.addr("WKUP_THOLD_LO"), _WDT.mask("WKUP_THOLD_LO"), 0x5EC0_7703),
    ("SEP_SW_DEBUG", _CPU_CTRL.addr("SEP_SW_DEBUG"), _CPU_CTRL.mask("SEP_SW_DEBUG"), 0x5D3B_0004),
)
for _n, _a, _m, _v in ARMED:
    # The routine compares the full 32-bit word, so every bit must be a field bit.
    if (_m & 0xFFFF_FFFF) != 0xFFFF_FFFF:
        raise RuntimeError(f"{_n}: field mask 0x{_m:x} does not cover bits 31:0")
V_COLD = ARMED[0][3]
# Warm scratch value after a CPU reset: its RDL reset value.
WARM_RESET = _WARM.reset("SCRATCH_0_") & 0xFFFF_FFFF

# WDT register pairs of the store leg: (even word, odd word) of one 64-bit
# aligned doubleword, each a 32-bit read-write field.
WDT_PAIRS = (
    ("WKUP_THOLD_HI", "WKUP_THOLD_LO"),
    ("WKUP_COUNT_HI", "WKUP_COUNT_LO"),
    ("WDOG_BARK_THOLD", "WDOG_BITE_THOLD"),
)
WDT_LO = sym("WDT_TIMER_REG_MAP_BASE_ADDR")
WDT_HI = WDT_LO + sym("WDT_TIMER_REG_MAP_SIZE")
for _p, (_e, _o) in enumerate(WDT_PAIRS):
    if _WDT.addr(_e) % 8 or _WDT.addr(_o) != _WDT.addr(_e) + 4:
        raise RuntimeError(f"{_e}/{_o} is not one 64-bit aligned doubleword")
    for _r in (_e, _o):
        if (_WDT.mask(_r) & 0xFFFF_FFFF) != 0xFFFF_FFFF:
            raise RuntimeError(f"{_r}: field mask does not cover bits 31:0")
# CPU accesses, in store-routine order: (kind, register, address, value).
# (b) a 32-bit store to the even word, (c) to the odd word.
CPU_ACCESSES = tuple(
    (kind, reg, _WDT.addr(reg), 0x5700_0000 | (p << 16) | (0xB0 if kind == "b" else 0xC0) << 8 | w)
    for p, pair in enumerate(WDT_PAIRS)
    for kind, w, reg in (("b", 0, pair[0]), ("c", 1, pair[1]))
)
# (a) one full-strobe 64-bit system-bus write per pair: (even register, value).
SBA_ACCESSES = tuple(
    (pair[0], ((0x5A00_A001 | (p << 16)) << 32) | (0x5A00_A000 | (p << 16)))
    for p, pair in enumerate(WDT_PAIRS)
)

FILTER_CFG_OPEN = (
    _OUTF.field_mask("FILTER_CONFIG", "read_allowed")
    | _OUTF.field_mask("FILTER_CONFIG", "write_allowed")
    | _OUTF.field_mask("FILTER_CONFIG", "entry_enabled")
    | _OUTF.field_mask("FILTER_CONFIG", "allow_burst")
    | (_OUTF.reset("FILTER_CONFIG") & _OUTF.field_mask("FILTER_CONFIG", "data_bus_width"))
)

# Environment choices (logged).
W_OBS = 10_000  # clk_i cycles from the sep_cpu_reset_n rise: first retire and marker
RST_HOLD = 20  # clk_i cycles of each rst_ni and wdt_rst_ni pulse
PASS_BOUND = 400_000  # clk_i cycles for one routine pass record
RISE_BOUND = 20_000  # clk_i cycles from a reset release to the sep_cpu_reset_n rise
B_BOUND = 2_000  # clk_i cycles for the write responses of the outbound stores
QUIET = 8  # clk_i cycles after the last write response before a CPU reset
SPIN = 400  # spin-loop iterations after each routine pass
ST_SETTLE = 2_000  # clk_i cycles after the store-routine end record (late NMI records)


# ---- RV32I encoder for the staged images ----
ZERO, T0, T1, T2, S0, S1, A0, A1, A2, A3, A4, A5 = 0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15
S2, S3, T3, T4, T5 = 18, 19, 28, 29, 30
GP, T6 = 3, 31
FENCE = 0x0FF0000F
MRET = 0x3020_0073
CSR_MCAUSE = 0x342
CSR_MDSEAC = 0xFC0  # VeeR EL2 D-bus error address capture
CSR_MDEAU = 0xBC0  # VeeR EL2 D-bus error address unlock


def _i(op: int, f3: int, rd: int, rs1: int, imm: int) -> int:
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op


def _lui(rd: int, imm20: int) -> int:
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | 0x37


def _addi(rd: int, rs1: int, imm: int) -> int:
    return _i(0x13, 0, rd, rs1, imm)


def _ori(rd: int, rs1: int, imm: int) -> int:
    return _i(0x13, 6, rd, rs1, imm)


def _slli(rd: int, rs1: int, sh: int) -> int:
    return _i(0x13, 1, rd, rs1, sh & 0x1F)


def _or(rd: int, rs1: int, rs2: int) -> int:
    return (rs2 << 20) | (rs1 << 15) | (6 << 12) | (rd << 7) | 0x33


def _lw(rd: int, rs1: int, off: int) -> int:
    return _i(0x03, 2, rd, rs1, off)


def _sw(rs2: int, rs1: int, off: int) -> int:
    return (
        (((off >> 5) & 0x7F) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (2 << 12)
        | ((off & 0x1F) << 7)
        | 0x23
    )


def _jalr(rd: int, rs1: int, off: int) -> int:
    return _i(0x67, 0, rd, rs1, off)


def _branch(f3: int, rs1: int, rs2: int, off: int) -> int:
    return (
        (((off >> 12) & 1) << 31)
        | (((off >> 5) & 0x3F) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (f3 << 12)
        | (((off >> 1) & 0xF) << 8)
        | (((off >> 11) & 1) << 7)
        | 0x63
    )


def _jal(rd: int, off: int) -> int:
    return (
        (((off >> 20) & 1) << 31)
        | (((off >> 1) & 0x3FF) << 21)
        | (((off >> 11) & 1) << 20)
        | (((off >> 12) & 0xFF) << 12)
        | (rd << 7)
        | 0x6F
    )


def _csrr(rd: int, csr: int) -> int:
    return (csr << 20) | (2 << 12) | (rd << 7) | 0x73


def _csrw0(csr: int) -> int:
    return (csr << 20) | (1 << 12) | 0x73


def _li(rd: int, v: int) -> list[int]:
    v &= 0xFFFF_FFFF
    hi = ((v + 0x800) >> 12) & 0xFFFFF
    lo = (v - (hi << 12)) & 0xFFF
    return [_lui(rd, hi), _addi(rd, rd, lo)]


class _Asm:
    """A tiny two-pass assembler: 32-bit words, labels, branches and jumps."""

    def __init__(self) -> None:
        self.items: list = []
        self.labels: dict[str, int] = {}

    def op(self, *words: int) -> None:
        self.items.extend(words)

    def label(self, name: str) -> None:
        self.labels[name] = len(self.items)

    def br(self, f3: int, rs1: int, rs2: int, target: str) -> None:
        self.items.append(("b", f3, rs1, rs2, target))

    def j(self, target: str) -> None:
        self.items.append(("j", target))

    def words(self) -> list[int]:
        out = []
        for idx, it in enumerate(self.items):
            if isinstance(it, int):
                out.append(it)
            elif it[0] == "b":
                out.append(_branch(it[1], it[2], it[3], 4 * (self.labels[it[4]] - idx)))
            else:
                out.append(_jal(ZERO, 4 * (self.labels[it[1]] - idx)))
        return out


def entry_words(marker: int) -> list[int]:
    """Open the outbound mailbox window, store ``marker``, jump to the routine."""
    w = _li(T0, MBX)
    for reg, val in (
        ("START_ADDR", MBX),
        ("END_ADDR", MBX + 0xFF),
        ("FILTER_CONFIG", FILTER_CFG_OPEN),
    ):
        w += _li(T1, _OUTF.addr(reg)) + _li(T2, val & 0xFFFF_FFFF)
        w += [_sw(T2, T1, 0)] + _li(T2, val >> 32) + [_sw(T2, T1, 4)]
    w += [FENCE] + _li(T2, marker) + [_sw(T2, T0, OFF_MARK), FENCE]
    w += _li(T3, ROUTINE) + [_jalr(ZERO, T3, 0)]
    return w


def nmi_words() -> list[int]:
    """NMI handler: store mcause and mdseac to the mailbox, unlock mdseac, return.

    A store that ends in a bus error raises an NMI on VeeR EL2. The handler makes
    each such error a mailbox record, which the leaf logs, and resumes the
    routine. It uses only gp and t6, which the routine does not use.
    """
    w = _li(GP, MBX)
    w += [_csrr(T6, CSR_MCAUSE), _sw(T6, GP, OFF_NMI_CAUSE)]
    w += [_csrr(T6, CSR_MDSEAC), _sw(T6, GP, OFF_NMI_ADDR), FENCE]
    w += [_csrw0(CSR_MDEAU), MRET]
    return w


def routine_words() -> list[int]:
    """The common retention routine (never returns)."""
    a = _Asm()
    regs = (S0, S1, S2, S3)
    vals = (A0, A1, A2, A3)
    a.op(*_li(T0, MBX))
    a.op(*_li(T1, _CPU_CTRL.addr("SEP_NMI_VEC")), *_li(T2, NMI_HANDLER), _sw(T2, T1, 0), FENCE)
    for r, (_n, addr, _m, _v) in zip(regs, ARMED):
        a.op(*_li(r, addr))
    for r, off in zip(regs, OFF_ENTRY):
        a.op(_lw(T1, r, 0), _sw(T1, T0, off))
    a.op(FENCE)
    for r, v, (_n, _a, _m, val) in zip(regs, vals, ARMED):
        a.op(*_li(v, val), _sw(v, r, 0))
    a.op(FENCE, _addi(A4, ZERO, 0), _addi(A5, ZERO, 0))
    a.label("loop")
    a.op(_addi(T3, ZERO, 0))
    for k, (r, v) in enumerate(zip(regs, vals)):
        a.op(_lw(T1, r, 0))
        a.br(0, T1, v, f"ok{k}")  # beq
        a.op(_ori(T3, T3, 1 << k))
        a.label(f"ok{k}")
    a.br(1, T3, ZERO, "fail")  # bne
    a.op(_addi(A4, A4, 1), _sw(A4, T0, OFF_PASS), FENCE)
    a.j("spin")
    a.label("fail")
    a.op(_addi(A5, A5, 1), _slli(T4, A5, 8), _or(T4, T4, T3), _sw(T4, T0, OFF_FAIL), FENCE)
    a.label("spin")
    a.op(*_li(T5, SPIN))
    a.label("spin_loop")
    a.op(_addi(T5, T5, -1))
    a.br(1, T5, ZERO, "spin_loop")
    # Store-leg flag: 0 continues the loop, any other value starts the store routine.
    a.op(*_li(T1, ST_FLAG), _lw(T1, T1, 0))
    a.br(0, T1, ZERO, "loop")  # beq
    a.op(*_li(T3, STORE_RT), _jalr(ZERO, T3, 0))
    return a.words()


def store_words() -> list[int]:
    """WDT store routine: each CPU access, a fence, a read-back to the mailbox; then idle."""
    w = _li(T0, MBX)
    for _k, _r, addr, val in CPU_ACCESSES:
        w += _li(S0, addr) + _li(A0, val) + [_sw(A0, S0, 0), FENCE]
        w += [_lw(T1, S0, 0), _sw(T1, T0, OFF_ST_RD), FENCE]
    w += _li(T2, ST_DONE) + [_sw(T2, T0, OFF_ST_DONE), FENCE]
    w += [_jal(ZERO, 0)]
    return w


def _to_bytes(words: list[int]) -> bytes:
    return b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in words)


ENTRY_BYTES = len(_to_bytes(entry_words(0)))
ROUTINE_BYTES = len(_to_bytes(routine_words()))
STORE_BYTES = len(_to_bytes(store_words()))
if NMI_HANDLER + len(_to_bytes(nmi_words())) > ROUTINE or ROUTINE + ROUTINE_BYTES > STORE_RT:
    raise RuntimeError("the routine overlaps the store routine")
if STORE_RT + STORE_BYTES > VEC_LO or ST_FLAG + 8 > NMI_HANDLER:
    raise RuntimeError("the store routine or flag overlaps another image")


@dataclass
class _Epoch:
    """One reset: from its assertion to the next reset assertion."""

    idx: int
    kind: str  # cold | cpu
    start_clk: int
    tap_low: int = 0
    sep_low: int = 0
    rise_clk: int | None = None
    first_retire: tuple[int, int] | None = None
    retired_in_window: int = 0
    early_retire: list = field(default_factory=list)
    early_fetch: list = field(default_factory=list)
    first_rom_fetch_clk: int | None = None


@dataclass
class _Scope:
    """Tap levels sampled during one TAP-reset window."""

    samples: int = 0
    sep_low: int = 0
    cpu_low: int = 0


@dataclass
class _Rec:
    seq: int
    clk: int
    off: int
    val: int


@pyuvm.test()
class sep_cpu_reset_entry_test(sep_base_test):
    """Default reset vector, TDR redirect and persistence, TAP reset scope."""

    build_env = False

    # ---------------------------------------------------------------- set-up
    def _draw(self) -> None:
        seed = self.random_seed()
        rng = SepSeededRng(seed)
        self.logger.info("SEED seed=%d", seed)
        n = (VEC_HI - VEC_LO) // 2 + 1
        s1 = rng.randrange(n)
        self.a1 = VEC_LO + 2 * s1
        # A2: any slot at least one image apart from A1.
        m = (ENTRY_BYTES + 1) // 2
        ex_lo, ex_hi = max(0, s1 - m + 1), min(n - 1, s1 + m - 1)
        k = rng.randrange(n - (ex_hi - ex_lo + 1))
        s2 = k if k < ex_lo else k + (ex_hi - ex_lo + 1)
        self.a2 = VEC_LO + 2 * s2
        self.tck_clks = 4 + rng.randrange(13)
        self.trst_tck = 2 + rng.randrange(49)
        self.d = rng.randrange(201)
        self.logger.info("DRAW A1=0x%08x", self.a1)
        self.logger.info("DRAW A2=0x%08x image_bytes=%d", self.a2, ENTRY_BYTES)
        self.logger.info(
            "DRAW tck_period=%d clk_i periods (%d ps)",
            self.tck_clks,
            self.tck_period_ps,
        )
        self.logger.info("DRAW trst_width=%d TCK cycles", self.trst_tck)
        self.logger.info("DRAW d=%d clk_i cycles", self.d)
        self.logger.info(
            "ENV W_obs=%d rst_hold=%d pass_bound=%d rise_bound=%d quiet=%d spin=%d routine=0x%08x "
            "store_routine=0x%08x st_settle=%d",
            W_OBS,
            RST_HOLD,
            PASS_BOUND,
            RISE_BOUND,
            QUIET,
            SPIN,
            ROUTINE,
            STORE_RT,
            ST_SETTLE,
        )

    @property
    def tck_period_ps(self) -> int:
        return int(round(self.tck_clks * self.cfg.sys_clk_period_ns * 1000))

    def _mem(self, which: str):
        ipi = cocotb.top.u_dut.u_sep_ip_integration
        if which == "rom":
            return ipi.u_sep_boot_rom.mem
        sram = ipi.u_sep_sram
        try:
            return sram.gen_ram_inst[0].u_mem.mem
        except (IndexError, AttributeError):
            # VCS lists the instance as the child ``gen_ram_inst[0].u_mem`` and
            # gives no element for the index.
            return sram._id("gen_ram_inst[0].u_mem", extended=False).mem

    def _write_image(self, which: str, base: int, nwords: int, blobs: dict[int, bytes]) -> None:
        """Write the 64-bit words that hold ``blobs`` (address -> bytes); other bytes 0."""
        img: dict[int, bytearray] = {}
        for addr, data in blobs.items():
            for i, b in enumerate(data):
                widx, lane = divmod(addr + i - base, 8)
                if not 0 <= widx < nwords:
                    raise ValueError(f"image byte 0x{addr + i:08x} is outside the {which} macro")
                img.setdefault(widx, bytearray(8))[lane] = b
        mem = self._mem(which)
        for widx, word in sorted(img.items()):
            mem[widx].value = int.from_bytes(bytes(word), "little")
        self.logger.info(
            "STAGE %s words=%d %s",
            which,
            len(img),
            " ".join(f"0x{a:08x}+{len(d)}" for a, d in blobs.items()),
        )

    def _stage_rom(self) -> None:
        self._write_image(
            "rom", ROM_BASE, ROM_WORDS, {ROM_BASE: _to_bytes(entry_words(MARKERS["M_ROM"]))}
        )

    def _stage_sram(self) -> None:
        self._write_image(
            "sram",
            SRAM_BASE,
            SRAM_WORDS,
            {
                ST_FLAG: bytes(8),
                NMI_HANDLER: _to_bytes(nmi_words()),
                ROUTINE: _to_bytes(routine_words()),
                STORE_RT: _to_bytes(store_words()),
                self.a1: _to_bytes(entry_words(MARKERS["M1"])),
                self.a2: _to_bytes(entry_words(MARKERS["M2"])),
            },
        )

    # ---------------------------------------------------------------- sampler
    async def _sampler(self) -> None:
        dut = cocotb.top
        prev_rst = prev_wdt = None
        while not self._stop:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.clk += 1
            rst = self.rd(dut.rst_ni)
            wdt = self.rd(dut.wdt_rst_ni_i)
            if (prev_rst is None and rst == 0) or (prev_rst == 1 and rst == 0):
                self.epochs.append(_Epoch(len(self.epochs), "cold", self.clk))
            elif prev_wdt == 1 and wdt == 0 and rst == 1:
                self.epochs.append(_Epoch(len(self.epochs), "cpu", self.clk))
            prev_rst, prev_wdt = rst, wdt
            cpu_tap = self.rd(dut.sep_cpu_reset_n_o)
            sep_tap = self.rd(dut.dbg_sep_reset_n_o)
            tv = self.rd(dut.cpu_trace_valid_o)
            pc = self.rd(dut.cpu_trace_addr_o) if tv else None
            rom_req = self.rd(dut.pr_rom_req_o)
            ifu_req = self.rd(dut.pr_ifu_arvalid_o)
            if self.scope is not None:
                self.scope.samples += 1
                self.scope.sep_low += sep_tap == 0
                self.scope.cpu_low += cpu_tap == 0
            if not self.epochs:
                continue
            ep = self.epochs[-1]
            if cpu_tap == 0:
                ep.tap_low += 1
                if tv:
                    ep.early_retire.append((self.clk, pc))
                if rom_req or ifu_req:
                    ep.early_fetch.append((self.clk, rom_req, ifu_req))
            elif ep.tap_low and ep.rise_clk is None:
                ep.rise_clk = self.clk
            if sep_tap == 0:
                ep.sep_low += 1
            if ep.rise_clk is not None and cpu_tap:
                if tv:
                    if ep.first_retire is None:
                        ep.first_retire = (self.clk, pc)
                    if self.clk - ep.rise_clk < W_OBS:
                        ep.retired_in_window += 1
                if rom_req and ep.first_rom_fetch_clk is None:
                    ep.first_rom_fetch_clk = self.clk

    # ---------------------------------------------------------------- mailbox
    def _mbx(self) -> list[_Rec]:
        """Outbound word stores (PR-OUT AW paired in order with its single W beat)."""
        aws = [b for b in self.out_tap.beats if b.ch == "aw"]
        ws = [b for b in self.out_tap.beats if b.ch == "w"]
        while len(self.recs) < min(len(aws), len(ws)):
            i = len(self.recs)
            aw, w = aws[i], ws[i]
            if aw.len != 0 or not w.last:
                raise AssertionError(f"outbound write {i} is not a single beat: {aw.fmt()}")
            # A 32-bit store leaves on the 64-bit port with its lane in the strobe.
            if w.strb not in (0x0F, 0xF0):
                raise AssertionError(f"outbound write {i} strobe 0x{w.strb:x} for {aw.fmt()}")
            lane = 1 if w.strb == 0xF0 else 0
            off = (aw.addr & ~7) + 4 * lane - MBX
            val = (w.data >> (32 * lane)) & 0xFFFF_FFFF
            self.recs.append(_Rec(i, self.clk, off, val))
        return self.recs

    async def _wait_rec(self, after: int, off: int, bound: int, what: str) -> _Rec:
        for _ in range(bound):
            for r in self._mbx()[after:]:
                if r.off == off:
                    return r
            await RisingEdge(cocotb.top.clk_i)
        raise AssertionError(f"{what}: no mailbox store at +0x{off:x} within {bound} clk_i cycles")

    def _fails_since(self, after: int) -> list[_Rec]:
        return [r for r in self._mbx()[after:] if r.off == OFF_FAIL]

    async def _wait_b_drain(self) -> None:
        for _ in range(B_BOUND):
            n_aw = sum(1 for b in self.out_tap.beats if b.ch == "aw")
            n_b = sum(1 for b in self.rsp_tap.beats if b.ch == "b")
            if n_b >= n_aw:
                return
            await RisingEdge(cocotb.top.clk_i)
        raise AssertionError(f"outbound write responses outstanding after {B_BOUND} cycles")

    # ---------------------------------------------------------------- resets
    async def _new_epoch(self, n_before: int) -> _Epoch:
        for _ in range(8):
            if len(self.epochs) > n_before:
                return self.epochs[-1]
            await RisingEdge(cocotb.top.clk_i)
        raise AssertionError("the sampler saw no reset assertion")

    async def _cold_pulse(self) -> tuple[_Epoch, int]:
        """Pulse rst_ni with clocks running; write the SRAM images while it is low."""
        dut = cocotb.top
        await RisingEdge(dut.clk_i)
        mark = len(self._mbx())
        n = len(self.epochs)
        dut.rst_ni.value = 0
        ep = await self._new_epoch(n)
        self._stage_sram()
        await ClockCycles(dut.clk_i, RST_HOLD)
        dut.rst_ni.value = 1
        return ep, mark

    async def _quiet_point(self) -> None:
        """Wait for the next routine pass and its write response (core in the SRAM spin loop)."""
        rec = await self._wait_rec(len(self._mbx()), OFF_PASS, PASS_BOUND, "quiet point")
        self.last_pass = rec
        await self._wait_b_drain()
        await ClockCycles(cocotb.top.clk_i, QUIET)

    async def _cpu_reset(self, during=None) -> tuple[_Epoch, int]:
        """A wdt_rst_ni CPU reset at a quiet point; ``during`` runs while it is held."""
        dut = cocotb.top
        await self._quiet_point()
        await RisingEdge(dut.clk_i)
        mark = len(self._mbx())
        n = len(self.epochs)
        dut.wdt_rst_ni_i.value = 0
        ep = await self._new_epoch(n)
        await ClockCycles(dut.clk_i, RST_HOLD)
        if during is not None:
            await during()
        dut.wdt_rst_ni_i.value = 1
        return ep, mark

    async def _entry(self, ep: _Epoch, mark: int, what: str) -> tuple[int | None, str, list]:
        """Wait for the tap rise, the first retirement and the marker of the run of ``ep``.

        Returns (first PC, marker name, entry words). The first retirement and the
        marker must fall within W_obs clk_i cycles of the tap rise.
        """
        dut = cocotb.top
        for _ in range(RISE_BOUND):
            if ep.rise_clk is not None:
                break
            await RisingEdge(dut.clk_i)
        else:
            raise AssertionError(f"{what}: sep_cpu_reset_n tap did not rise in {RISE_BOUND} cycles")
        while ep.first_retire is None and self.clk - ep.rise_clk < W_OBS:
            await RisingEdge(dut.clk_i)
        marker = None
        while self.clk - ep.rise_clk < W_OBS:
            marks = [r for r in self._mbx()[mark:] if r.off == OFF_MARK]
            if marks:
                marker = marks[0]
                break
            await RisingEdge(dut.clk_i)
        first_pc = ep.first_retire[1] if ep.first_retire else None
        if first_pc is None:
            raise AssertionError(
                f"{what}: CTL-RUNREQ FAIL no instruction retired within {W_OBS} clk_i cycles "
                "of the sep_cpu_reset_n rise"
            )
        if marker is None:
            raise AssertionError(f"{what}: no marker store within {W_OBS} cycles of the tap rise")
        entry = []
        for off in OFF_ENTRY:
            r = await self._wait_rec(marker.seq + 1, off, PASS_BOUND, f"{what} entry word")
            entry.append(r.val)
        name = MARKER_NAME.get(marker.val, f"0x{marker.val:08x}")
        self.logger.info(
            "OBS-ENTRY LOG %s epoch=%d kind=%s rise_clk=%d first_retire_clk=%d first_pc=0x%08x "
            "marker=%s entry=%s",
            what,
            ep.idx,
            ep.kind,
            ep.rise_clk,
            ep.first_retire[0],
            first_pc,
            name,
            " ".join(f"0x{v:08x}" for v in entry),
        )
        return first_pc, name, entry

    # ---------------------------------------------------------------- grading
    def _grade(self, chk: str, ok: bool, text: str) -> None:
        if ok:
            self.logger.info("%s PASS: %s", chk, text)
            self.n_checks += 1
        else:
            self.logger.error("%s FAIL: %s", chk, text)
            self.failures.append(f"{chk}: {text}")

    def _grade_vector(self, chk: str, prefix: str, pc, marker, exp_pc: int, exp_marker: str):
        ok = pc == exp_pc and marker == exp_marker
        text = f"{prefix}first_pc=0x{pc:08x} marker={marker}"
        if not ok:
            text += f" expected first_pc=0x{exp_pc:08x} marker={exp_marker}"
        self._grade(chk, ok, text)

    # ---------------------------------------------------------------- legs
    async def _power_on(self) -> tuple[_Epoch, int]:
        """Step 4: the first cold reset, with ext_boot_seq_done_i delayed by d."""
        dut = cocotb.top
        self.drive_idle_defaults(dut, cpu_run=True, rst_vec=0)
        dut.ext_boot_seq_done_i.value = 0
        # Power-on TAP reset on the bench-owned pins: jtag_trst_ni presents 1 and
        # then 0, so the asynchronous TAP reset fires (a level that is low from
        # time 0 has no falling edge) and the TDR holds its default. TRST stays
        # low through the three cold resets.
        for pin, val in (("jtag_tck_i", 0), ("jtag_tms_i", 1), ("jtag_tdi_i", 0)):
            getattr(dut, pin).value = val
        dut.jtag_trst_n_i.value = 1
        dut.jtag_bench_own_i.value = 1
        await self.assert_cold_reset(dut)
        dut.jtag_trst_n_i.value = 0
        await Timer(1, units="ns")
        self._set_if_exists(dut, "dbg_rstb_i", 0)
        self._stage_rom()
        self._stage_sram()
        self.start_clocks(dut)
        cocotb.start_soon(self._sampler())
        self.out_tap.start()
        self.rsp_tap.start()
        ep = await self._new_epoch(0)
        open_graded_window(TEST, self.logger)
        await ClockCycles(dut.clk_i, RST_HOLD)
        dut.rst_ni.value = 1
        self._set_if_exists(dut, "dbg_rstb_i", 1)
        await ClockCycles(dut.clk_i, self.d)
        dut.ext_boot_seq_done_i.value = 1
        return ep, 0

    async def _run_req_leg(self, ep: _Epoch, mark: int, d: int, label: str) -> None:
        pc, marker, _ = await self._entry(ep, mark, label)
        while self.clk - ep.rise_clk < W_OBS:
            await RisingEdge(cocotb.top.clk_i)
        self.logger.info(
            "CTL-RUNREQ: run_req=1 d=%d first_pc=0x%08x retired_in_window=%d window=%d",
            d,
            pc,
            ep.retired_in_window,
            W_OBS,
        )
        self._grade_vector(
            "CHK-RSTVEC-DEFAULT", f"reset={label} ", pc, marker, DEFAULT_RESET_PC, "M_ROM"
        )

    async def _tap_reset(self, via: str) -> None:
        if via == "TRST":
            await self.dmi.trst_pulse(tck_cycles=self.trst_tck)
        else:
            await self.dmi.tlr()

    async def _program(self, vector: int) -> None:
        cap = await self.dmi.shift_rstvec(vector)
        self.logger.info("TDR shift IR=0x18 vector=0x%08x (capture 0x%08x not graded)", vector, cap)

    async def _tap_then_cpu_reset(self, via: str, tdr: str) -> None:
        """Step 7: a TAP reset, then a CPU reset; the core starts at the ROM base."""
        await self._quiet_point()
        await self._tap_reset(via)
        ep, mark = await self._cpu_reset()
        pc, marker, _ = await self._entry(ep, mark, f"step7 {via}")
        self._grade_vector(
            "CHK-RSTVEC-TAPRST", f"via={via} tdr={tdr} ", pc, marker, DEFAULT_RESET_PC, "M_ROM"
        )

    async def _scope_leg(self, via: str, tdr: str, cur_mark: int) -> int:
        """Step 11 sub-leg: retention across a TAP reset, then the CPU reset."""
        dut = cocotb.top
        start = await self._wait_rec(cur_mark, OFF_PASS, PASS_BOUND, f"scope {via} start")
        probe0 = self.rd(dut.scratch_cold_probe_o, mask=0xFFFF_FFFF)
        self.logger.info(
            "OBS-TRST-SCOPE LOG via=%s tdr=%s start_pass=%d scratch_cold_probe0=0x%08x",
            via,
            tdr,
            start.val,
            probe0,
        )
        self.scope = _Scope()
        await self._tap_reset(via)
        end = len(self._mbx())
        p1 = await self._wait_rec(end, OFF_PASS, PASS_BOUND, f"scope {via} pass 1")
        p2 = await self._wait_rec(p1.seq + 1, OFF_PASS, PASS_BOUND, f"scope {via} pass 2")
        scope, self.scope = self.scope, None
        probe1 = self.rd(dut.scratch_cold_probe_o, mask=0xFFFF_FFFF)
        fails = self._fails_since(start.seq)
        bad_mask = 0
        for f in fails:
            bad_mask |= f.val & 0xF
        retained = 4 - bin(bad_mask).count("1")
        ep, mark = await self._cpu_reset()
        pc, marker, entry = await self._entry(ep, mark, f"scope {via}")
        self._grade_vector(
            "CHK-RSTVEC-TAPRST", f"via={via} tdr={tdr} ", pc, marker, DEFAULT_RESET_PC, "M_ROM"
        )
        warm_cleared = int(entry[1] == WARM_RESET and entry[0] == V_COLD and ep.tap_low > 0)
        ok = (
            scope.sep_low == 0
            and scope.cpu_low == 0
            and not fails
            and p2.val > p1.val > start.val
            and probe0 == probe1 == V_COLD
            and warm_cleared == 1
            and self.control_sep_low > 0
        )
        self._grade(
            "CHK-TRST-SCOPE",
            ok,
            f"via={via} tdr={tdr} sep_reset_n_low={scope.sep_low} "
            f"sep_cpu_reset_n_low={scope.cpu_low} regs_retained={retained}/4 "
            f"control_warm_cleared={warm_cleared} samples={scope.samples} "
            f"passes={start.val}->{p1.val}->{p2.val} probe0=0x{probe0:08x}->0x{probe1:08x} "
            f"entry_cold=0x{entry[0]:08x} entry_warm=0x{entry[1]:08x} "
            f"cpu_tap_low={ep.tap_low} control_sep_reset_low={self.control_sep_low}",
        )
        return mark

    # ---------------------------------------------------------------- scenario
    async def run_scenario(self) -> None:
        dut = cocotb.top
        self.clk = 0
        self._stop = False
        self.epochs: list[_Epoch] = []
        self.scope: _Scope | None = None
        self.recs: list[_Rec] = []
        self.failures: list[str] = []
        self.n_checks = 0
        self.last_pass = None
        self.out_tap = SepFabricTap("PR-OUT")
        self.rsp_tap = SepFabricTap("PR-OUT-RSP")
        self._draw()
        self.required_evidence = (
            "CHK-RSTVEC-DEFAULT",
            "CHK-NO-EARLY-RETIRE",
            "CHK-NO-EARLY-FETCH",
            "CHK-RSTVEC",
            "CHK-RSTVEC-PERSIST",
            "CHK-RSTVEC-TAPRST",
            "CHK-TRST-SCOPE",
            "CHK-WDT-STORE-RESP",
        )
        self.st_rows: list[dict] = []
        self.st_errors: list[str] = []

        # Steps 4-6: three cold resets with the default TDR (TAP held in TRST).
        ep, mark = await self._power_on()
        await self._run_req_leg(ep, mark, self.d, "cold1")
        self.control_sep_low = ep.sep_low
        ep, mark = await self._cold_pulse()
        await self._run_req_leg(ep, mark, 0, "cold2")
        ep, mark = await self._cold_pulse()
        pc, marker, _ = await self._entry(ep, mark, "cold3")
        self._grade_vector(
            "CHK-RSTVEC-DEFAULT", "reset=cold3 ", pc, marker, DEFAULT_RESET_PC, "M_ROM"
        )

        await self._jtag_legs()

        # Step 12.
        await self._quiet_point()
        for leg in (self._cpu_store_leg, self._sba_store_leg):
            try:
                await leg()
            except AssertionError as exc:
                # Graded at the end with the other store results, so the other
                # checks of the leaf still run.
                self.st_errors.append(f"{leg.__name__}: {exc}")
        self._stop = True
        await ClockCycles(dut.clk_i, 2)
        close_graded_window(self.logger)
        late_fails = self._fails_since(0)
        if late_fails:
            self.failures.append(
                "routine compare fail records: "
                + " ".join(f"0x{r.val:08x}@{r.seq}" for r in late_fails)
            )
        causes = [r for r in self._mbx() if r.off == OFF_NMI_CAUSE]
        addrs = [r for r in self._mbx() if r.off == OFF_NMI_ADDR]
        self.logger.info(
            "OBS-STORE-BUS-ERR LOG nmi_records=%d %s",
            len(causes),
            " ".join(
                f"mcause=0x{c.val:08x}/mdseac=0x{a.val:08x}@{c.seq}" for c, a in zip(causes, addrs)
            ),
        )
        self._grade_no_early()
        # Graded last: every other check above has already run.
        self._grade_store_resp()
        if self.failures:
            raise AssertionError("; ".join(self.failures))
        self.logger.info(
            "RESULT %s seed=%d PASS checks=%d", TEST, self.random_seed(), self.n_checks
        )

    async def _jtag_legs(self) -> None:
        dut = cocotb.top
        from env.sep_jtag_dmi import IR_WIDTH, PIN_MAP, SepJtagDmi
        from ocah_jtag_vip import OcahJtagMasterDriver

        tap = OcahJtagMasterDriver(
            dut,
            name="sep_core_tap",
            tck_period_ns=self.tck_period_ps,
            ir_width=IR_WIDTH,
            tap_type="dtm",
            signal_map=dict(PIN_MAP),
            time_unit="ps",
        )
        self.dmi = SepJtagDmi(tap, dut=dut, log=self.logger)
        self.dmi.take_pins()

        # Step 7: TAP reset with the default TDR, by TRST and by Test-Logic-Reset.
        await self._tap_then_cpu_reset("TRST", "default")
        await self._tap_then_cpu_reset("TLR", "default")

        # Step 8: redirect to A1 (SRAM written again while the CPU is in reset).
        async def _arm_a1() -> None:
            self._stage_sram()
            await self._program(self.a1)

        ep, mark = await self._cpu_reset(_arm_a1)
        pc, marker, _ = await self._entry(ep, mark, "redirect")
        self._grade_vector(
            "CHK-RSTVEC", f"leg=redirect vector=0x{self.a1:08x} ", pc, marker, self.a1, "M1"
        )

        # Step 9: persistence across a CPU reset.
        ep, mark = await self._cpu_reset()
        pc, marker, _ = await self._entry(ep, mark, "persist")
        self._grade_vector("CHK-RSTVEC-PERSIST", "after wdt reset ", pc, marker, self.a1, "M1")

        # Step 10: rewrite to A2.
        async def _arm_a2() -> None:
            await self._program(self.a2)

        ep, mark = await self._cpu_reset(_arm_a2)
        pc, marker, _ = await self._entry(ep, mark, "rewrite")
        self._grade_vector(
            "CHK-RSTVEC", f"leg=rewrite vector=0x{self.a2:08x} ", pc, marker, self.a2, "M2"
        )

        # Step 11: TAP reset scope, four sub-legs in the contract order.
        mark = await self._scope_leg("TRST", "programmed", mark)
        mark = await self._scope_leg("TLR", "default", mark)
        mark = await self._scope_leg("TRST", "default", mark)
        ep, mark = await self._cpu_reset(_arm_a2)
        pc, marker, _ = await self._entry(ep, mark, "re-arm A2")
        # Precondition of the last sub-leg: the TDR holds A2 before its TAP reset.
        if (pc, marker) != (self.a2, "M2"):
            self.failures.append(
                f"re-arm precondition: first_pc=0x{pc:08x} marker={marker}, "
                f"expected 0x{self.a2:08x} M2"
            )
        self.logger.info(
            "CTL-TDR-ARM: vector=0x%08x first_pc=0x%08x marker=%s", self.a2, pc, marker
        )
        await self._scope_leg("TLR", "programmed", mark)

    # ---------------------------------------------------------------- WDT stores
    @staticmethod
    def _writes(tap: SepFabricTap) -> list[tuple]:
        """(aw, w, b) per write on ``tap``: W in AW order, B by ID in AW order."""
        aws = [b for b in tap.beats if b.ch == "aw"]
        ws = [b for b in tap.beats if b.ch == "w"]
        bs = [b for b in tap.beats if b.ch == "b"]
        used: set[int] = set()
        out = []
        for k, aw in enumerate(aws):
            w = ws[k] if k < len(ws) else None
            b = next(
                (x for x in bs if x.seq not in used and x.id == aw.id and x.seq > aw.seq), None
            )
            if b is not None:
                used.add(b.seq)
            out.append((aw, w, b))
        return out

    async def _cpu_store_leg(self) -> None:
        """(b) and (c): the store routine, started by the SRAM flag at a quiet point."""
        dut = cocotb.top
        tap = SepFabricTap("PR-LSU-XBAR").start()
        await RisingEdge(dut.clk_i)
        mark = len(self._mbx())
        mem = self._mem("sram")
        mem[(ST_FLAG - SRAM_BASE) // 8].value = 1
        self.logger.info("CTL-STORE-LEG: flag set at 0x%08x", ST_FLAG)
        await self._wait_rec(mark, OFF_ST_DONE, PASS_BOUND, "store routine end")
        await self._wait_b_drain()
        await ClockCycles(dut.clk_i, ST_SETTLE)
        await tap.stop()
        recs = self._mbx()[mark:]
        rds = [r.val for r in recs if r.off == OFF_ST_RD]
        causes = [r for r in recs if r.off == OFF_NMI_CAUSE]
        addrs = [r for r in recs if r.off == OFF_NMI_ADDR]
        nmis = [(c.val, a.val) for c, a in zip(causes, addrs)]
        wdt = [
            x for x in self._writes(tap) if x[0].addr is not None and WDT_LO <= x[0].addr < WDT_HI
        ]
        self.logger.info(
            "OBS-STORE-LEG LOG wdt_writes=%d readbacks=%d nmi=%s",
            len(wdt),
            len(rds),
            " ".join(f"mcause=0x{c:08x}/mdseac=0x{a:08x}" for c, a in nmis) or "-",
        )
        for i, (kind, reg, addr, val) in enumerate(CPU_ACCESSES):
            aw, w, b = wdt[i] if i < len(wdt) else (None, None, None)
            self.st_rows.append(
                {
                    "kind": kind,
                    "master": "cpu",
                    "reg": reg,
                    "addr": addr,
                    "aw": aw,
                    "w": w,
                    "b": b,
                    "exp": val,
                    "rd": rds[i] if i < len(rds) else None,
                    "nmi": [c for c, a in nmis if a == addr],
                    "sberr": None,
                }
            )
        if len(wdt) != len(CPU_ACCESSES):
            self.st_errors.append(
                f"{len(wdt)} WDT writes on PR-LSU-XBAR, expected {len(CPU_ACCESSES)}"
            )

    async def _sba_store_leg(self) -> None:
        """(a): one full-strobe 64-bit system-bus write per pair, read back the same way."""
        from env.sep_jtag_dmi import DM_DMCONTROL, DMCONTROL_DMACTIVE

        dut = cocotb.top
        dut.dmi_core_enable_i.value = 1
        tap = SepFabricTap("PR-DBG-SB").start()
        await self.dmi.dmi_write(DM_DMCONTROL, DMCONTROL_DMACTIVE)
        res = []
        for reg, val in SBA_ACCESSES:
            addr = _WDT.addr(reg)
            werr = await self.dmi.sba_write(addr, val, size=8)
            rd, rerr = await self.dmi.sba_read(addr, size=8)
            res.append((reg, addr, val, werr, rd, rerr))
        await ClockCycles(dut.clk_i, QUIET)
        await tap.stop()
        dut.dmi_core_enable_i.value = 0
        wdt = [
            x for x in self._writes(tap) if x[0].addr is not None and WDT_LO <= x[0].addr < WDT_HI
        ]
        for i, (reg, addr, val, werr, rd, rerr) in enumerate(res):
            aw, w, b = wdt[i] if i < len(wdt) else (None, None, None)
            self.st_rows.append(
                {
                    "kind": "a",
                    "master": "sba",
                    "reg": f"{reg}+next",
                    "addr": addr,
                    "aw": aw,
                    "w": w,
                    "b": b,
                    "exp": val,
                    "rd": rd,
                    "nmi": [],
                    "sberr": (werr, rerr),
                }
            )
        if len(wdt) != len(SBA_ACCESSES):
            self.st_errors.append(
                f"{len(wdt)} WDT writes on PR-DBG-SB, expected {len(SBA_ACCESSES)}"
            )

    def _grade_store_resp(self) -> None:
        """One CHK-WDT-STORE-RESP line per access: BRESP OKAY and the value reads back."""

        def h(v, width=8):
            return "X" if v is None else f"0x{v:0{width}x}"

        for err in self.st_errors:
            self._grade("CHK-WDT-STORE-RESP", False, f"leg error: {err}")
        for row in self.st_rows:
            aw, w, b = row["aw"], row["w"], row["b"]
            resp = None if b is None else b.resp
            ok = (
                aw is not None
                and w is not None
                and resp == 0
                and row["rd"] == row["exp"]
                and (row["kind"] != "a" or (aw.size == 3 and w.strb == 0xFF))
                and (row["sberr"] is None or row["sberr"] == (0, 0))
            )
            width = 16 if row["kind"] == "a" else 8
            text = (
                f"access=({row['kind']}) master={row['master']} reg={row['reg']} "
                f"addr={h(row['addr'])} bus_addr={h(None if aw is None else aw.addr)} "
                f"size={'X' if aw is None else aw.size} strb={h(None if w is None else w.strb, 2)} "
                f"resp={'X' if resp is None else resp} "
                f"wrote={h(row['exp'], width)} read={h(row['rd'], width)}"
            )
            if row["nmi"]:
                text += " nmi_mcause=" + ",".join(f"0x{c:08x}" for c in row["nmi"])
            if row["sberr"] is not None:
                text += f" sberror_wr={row['sberr'][0]} sberror_rd={row['sberr'][1]}"
            self._grade("CHK-WDT-STORE-RESP", ok, text)

    def _grade_no_early(self) -> None:
        eps = self.epochs
        no_low = [e.idx for e in eps if e.tap_low == 0]
        retire_bad = [(e.idx, e.kind, r) for e in eps for r in e.early_retire]
        fetch_bad = [(e.idx, e.kind, f) for e in eps for f in e.early_fetch]
        ctl_retire = next((e.first_retire[0] - e.start_clk for e in eps if e.first_retire), None)
        ctl_fetch = next(
            (e.first_rom_fetch_clk - e.start_clk for e in eps if e.first_rom_fetch_clk), None
        )
        kinds = f"cold={sum(e.kind == 'cold' for e in eps)} cpu={sum(e.kind == 'cpu' for e in eps)}"
        self._grade(
            "CHK-NO-EARLY-RETIRE",
            not retire_bad and not no_low and ctl_retire is not None,
            f"resets={len(eps)} ({kinds}) retire_before_release={len(retire_bad)} "
            f"control_retire_cycle={ctl_retire} tap_never_low={no_low} first={retire_bad[:4]}",
        )
        self._grade(
            "CHK-NO-EARLY-FETCH",
            not fetch_bad and not no_low and ctl_fetch is not None,
            f"resets={len(eps)} ({kinds}) fetch_before_release={len(fetch_bad)} "
            f"control_fetch_cycle={ctl_fetch} tap_never_low={no_low} first={fetch_bad[:4]}",
        )
