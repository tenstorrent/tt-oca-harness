# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU demux targets: an unmapped fetch gets DECERR, the LSU routes, ICCM is core-only.

The bench generates the code (``env/sep_rv32_asm``) and stages it before reset
release: the boot ROM holds a stub, the trap handler and the NMI handler
(backdoor write of the ROM macro); the ICCM holds the routine, the marker code
at a drawn word offset and the word W at a drawn data word (``tcm_load_i``);
the DCCM holds the known word K of the DCCM pair. The reset vector keeps its
default, the boot ROM base (cpu.adoc, Reset Vector), so the stub runs first. It
sets ``mtvec`` to the ROM trap handler and jumps to the ICCM routine. Before a
step that can trap, the routine writes its recovery address to ``mscratch``;
the handler logs ``mcause`` and ``mtval`` and resumes there. The routine logs
every value as a 32-bit store to the outbound mailbox; each marker store has
its own mailbox slot, so the bench finds it by address on the PR-LSU-XBAR tap
and bounds each window with two markers. A gate record opens the graded window
for steps 5, 7, 8 and the LSU pair of step 10 and closes it for every control leg.

Checks:
  CHK-IFU-DECERR     : the PR-IFU response to each fetch at an unmapped target
                       U is DECERR, with no PR-ROM or PR-SRAM request between the
                       fetch handshake and its response and no PR-IFU-XBAR
                       request outside the SRAM in the fetch window (cpu.adoc,
                       CPU: the IFU demux sends every address other than ROM and
                       SRAM to a DECERR responder). Control: the ROM fetches
                       (boot stub, trap handler) and the SRAM fetch of the
                       copied routine appear on those taps, the SRAM fetch also
                       on PR-IFU-XBAR.
  CHK-IFU-NEVER      : no request at U on PR-EXT or PR-OUT, and no PR-IFU-XBAR
                       request outside the SRAM, in the fetch window. Control:
                       the LSU read at 0x2000_0100 is on PR-EXT, the LSU store at
                       0x8000_0000 is on PR-OUT and the SRAM fetch of the copied
                       routine is on PR-IFU-XBAR.
  CHK-LSU-ROUTE      : the ROM load is on PR-LSU-ROM only and the SRAM load on
                       PR-LSU-XBAR only (cpu.adoc, CPU: the LSU demux).
  CHK-CORE-PATH-XBAR : the ICCM marker run, the DCCM pattern accesses and the
                       LSU load and store at the ICCM word raise no PR-XBAR-TCM
                       request (fabric.adoc, Fabric Topology). Control: the DMA
                       copy to the DCCM shows PR-XBAR-TCM requests.
  CHK-LSU-ICCM       : the LSU load at the ICCM word returns no W (a trap also
                       satisfies it) and the word still holds W after the LSU
                       store, read by a DMA copy to the SRAM (rom.adoc, ROM
                       Architecture: the load/store unit cannot access ICCM).
                       Control: the DCCM pair reads K, writes V2 and reads V2.
  CHK-LSU-ICCM-WE    : no ICCM write enable on PR-TCM during the LSU store.
                       Control: the DMA copy of an SRAM word to another ICCM
                       word shows the ICCM write enable.
  CTL-CORE-PATH      : (control) the marker code logs the drawn marker value and
                       the DCCM patterns read back exact; a difference fails the
                       leaf as a failed precondition.

The routine first sets ``mrac`` as the SEP firmware start-up does
(``fw/startup/crt0.s``): every 256 MiB region side-effect except region 12
(ICCM, DCCM, PIC). The core then issues each store at its own size, so a 32-bit
register write reaches a register block with its own strobe and no zero-strobe
neighbour beat. ``OBS-DMA-CSR-WRITE`` logs the shape and BRESP of every LSU
write to the secure DMA registers; ``OBS-EXT-READ`` logs every NMI.

The core reaction to an unmapped fetch and the response to an ICCM data access
are not scored; their records are logged (``OBS-``). Every expected value comes
from the drawn plan and the staged images; no expected value is read from the
DUT.

cpu run mode (real core), ``+skip_fuse_sense``; Verilator and VCS.
"""

from __future__ import annotations

import os

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from env.sep_fabric_common import RESP_DECERR
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_mbx_words import SepMbxWords
from env.sep_rom_image import ROM_WORDS, SepRomImage
from env.sep_rv32_asm import (
    A0,
    A1,
    CSR_MCAUSE,
    CSR_MDEAU,
    CSR_MDSEAC,
    CSR_MEPC,
    CSR_MSCRATCH,
    CSR_MTVAL,
    CSR_MTVEC,
    FENCE,
    FENCE_I,
    GP,
    MRET,
    RA,
    S11,
    T0,
    T1,
    T2,
    T3,
    T5,
    T6,
    ZERO,
    Asm,
    addi,
    and_,
    csrr,
    csrw,
    jalr,
    lw,
    sw,
    xor_,
)
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import RegBlock, sym
from seq_lib.sep_dma_ops import (
    CONTROL,
    OP_COPY,
    RANGE_BASE,
    RANGE_LIMIT,
    RANGE_VALID,
    SECURE_DMA,
    ST_ABORTED,
    ST_CLEAN_W1C,
    ST_DONE,
    ST_ERROR,
    STATUS,
    addr_cfg,
    control_word,
)

TEST = "sep_cpu_demux_unmapped_fetch_test"

ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
ROM_BYTES = sym("SEP_BOOT_ROM_MEM_SIZE")
SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_BYTES = sym("SEP_SRAM_MEM_SIZE")
ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
ICCM_BYTES = sym("SEP_ICCM_MEM_SIZE")
DCCM_BASE = sym("SEP_DCCM_MEM_BASE_ADDR")
DCCM_BYTES = sym("SEP_DCCM_MEM_SIZE")
if ROM_BYTES // 8 != ROM_WORDS:
    raise RuntimeError("the ROM image model and the memory map disagree on the ROM size")

_CPU_CTRL = RegBlock("SEP_CPU_CTRL")
_OUTF = RegBlock("OUTBOUND_FILTER_CTRL_0_")
NMI_VEC_ADDR = _CPU_CTRL.addr("SEP_NMI_VEC")
MBX = _CPU_CTRL.reset("SMU_GLOBAL_BASE_ADDR") & _CPU_CTRL.mask("SMU_GLOBAL_BASE_ADDR")
FILTER_CFG_OPEN = (
    _OUTF.field_mask("FILTER_CONFIG", "read_allowed")
    | _OUTF.field_mask("FILTER_CONFIG", "write_allowed")
    | _OUTF.field_mask("FILTER_CONFIG", "entry_enabled")
    | _OUTF.field_mask("FILTER_CONFIG", "allow_burst")
    | (_OUTF.reset("FILTER_CONFIG") & _OUTF.field_mask("FILTER_CONFIG", "data_bus_width"))
)
FILTER_ENTRY = (
    ("START_ADDR", MBX),
    # END_ADDR holds a 4 KiB granule: bits 11:0 read as 1.
    ("END_ADDR", MBX + 0xFFF),
    ("FILTER_CONFIG", FILTER_CFG_OPEN),
)

# The unmapped fetch targets of the contract. Each is outside the boot ROM, the
# SRAM, the core wiring 0xC000_0000-0xCFFF_FFFF, the local alias
# 0xD000_0000-0xFFFF_FFFF and the console address.
U_SET = (
    0x1005_0000,
    0x1090_0000,
    0x10A0_0000,
    0x10C0_0000,
    0x1100_0000,
    0x2000_0100,
    0x4000_0000,
    0x0000_1000,
)
EXT_ADDR = 0x2000_0100  # extension port read of step 6
OUT_ADDR = MBX  # outbound port store of step 6 (the console address)
OUT_VAL = 0x5EC0_0006

# Mailbox slots (8 bytes each; offset 0 is the step-6 outbound store).
_SLOTS = (
    "GATE FAIL TRAP_CAUSE TRAP_VAL NMI NMI_ADDR ROMLD_B ROMLD_V ROMLD_E SRAMLD_B SRAMLD_V "
    "SRAMLD_E EXT_B EXT_E OUT_B OUT_E FB0 FE0 FB1 FE1 FB2 FE2 CORE_B MARKV CORE_M DCCMV CORE_E "
    "DMA1_B DMA_ST DMA1_E LSUL_B ILOAD LSUL_E LSUS_B LSUS_E DMA2_B IREAD DMA2_E DMA3_B DMA3_E "
    "PAIR_B PAIR0 PAIR1 PAIR_E DONE"
).split()
OFF = {name: 8 * (k + 1) for k, name in enumerate(_SLOTS)}
if max(OFF.values()) + 8 > 0x200:
    raise RuntimeError("mailbox slots run past the outbound filter window")

# Images.
ROM_HANDLER = ROM_BASE + 0x100
ROM_NMI = ROM_BASE + 0x180
SRAM_RT = SRAM_BASE + 0x100  # routine copied by LSU stores (step 4)
SRAM_A = SRAM_BASE + 0x200  # DMA source of the DCCM copy (step 9)
SRAM_R = SRAM_BASE + 0x208  # DMA destination of the ICCM readback (step 10)
SRAM_S = SRAM_BASE + 0x210  # DMA source of the ICCM write control (step 10)
SRAM_LD_LO = SRAM_BASE + 0x1000

# VeeR EL2 mrac (region access control): two bits per 256 MiB region, bit 2r
# cacheable, bit 2r+1 side-effect. The SEP firmware value of fw/startup/crt0.s:
# every region side-effect except region 12.
CSR_MRAC = 0x7C0
MRAC_SEP = 0xA8AA_AAAA

# Environment choices (logged).
DMA_POLL = 4_000  # STATUS reads per DMA copy
NMI_WAIT = 200  # spin iterations after the extension-port read
DONE_BOUND = 400_000  # clk_i cycles from the boot to the done record
PROGRESS = 20_000  # clk_i cycles between progress lines


class _Plan:
    """Seed-drawn stimulus in the contract draw order."""

    def __init__(self, rng: SepSeededRng) -> None:
        self.u = rng.sample(list(U_SET), 3)
        self.mark_off = 4 * rng.randrange(0x8000 // 4, 0x10000 // 4)
        self.mark_val = rng.getrandbits(32)
        self.dccm_offs = [4 * x for x in rng.sample(range(0x1000 // 4, 0x10000 // 4), 4)]
        self.pattern = [rng.getrandbits(32) for _ in self.dccm_offs]
        self.w_val = 1 + rng.randrange(0xFFFF_FFFF)
        self.v_val = rng.getrandbits(32)
        if self.v_val == self.w_val:
            self.v_val ^= 1
        # Placement of the control words (bench choices, drawn after the
        # contract dimensions).
        self.w_off = 4 * rng.randrange(0x20000 // 4, 0x30000 // 4)
        self.iccm_d2_off = 4 * rng.randrange(0x30000 // 4, ICCM_BYTES // 4)
        self.dccm_d1_off = 4 * rng.randrange(0x10000 // 4, 0x18000 // 4)
        self.k_off = 4 * rng.randrange(0x18000 // 4, DCCM_BYTES // 4)
        self.k_val = rng.getrandbits(32)
        self.v2_val = self.k_val ^ (1 + rng.randrange(0xFFFF_FFFF))
        self.rom_ld = ROM_BASE + 8 * rng.randrange(64, ROM_WORDS)
        self.sram_ld = SRAM_LD_LO + 4 * rng.randrange((SRAM_BASE + SRAM_BYTES - SRAM_LD_LO) // 4)
        self.sram_ld_val = rng.getrandbits(32)
        self.sram_a_val = rng.getrandbits(32)
        self.sram_s_val = rng.getrandbits(32)

    @property
    def iccm_w(self) -> int:
        return ICCM_BASE + self.w_off

    @property
    def iccm_d2(self) -> int:
        return ICCM_BASE + self.iccm_d2_off

    @property
    def dccm_d1(self) -> int:
        return DCCM_BASE + self.dccm_d1_off

    @property
    def dccm_k(self) -> int:
        return DCCM_BASE + self.k_off


def _mark(a: Asm, name: str) -> None:
    a.op(FENCE, sw(ZERO, GP, OFF[name]), FENCE)


def _gate(a: Asm, on: int) -> None:
    a.op(FENCE, addi(T3, ZERO, on), sw(T3, GP, OFF["GATE"]), FENCE)


def _store_const(a: Asm, addr: int, val: int) -> None:
    a.li(T1, addr).li(T2, val).op(sw(T2, T1, 0))


def _fail_if_ne(a: Asm, addr: int, exp: int, mask: int, code: int, tag: str) -> None:
    """Read ``addr``; go to the fail path when ``(read ^ exp) & mask`` is non-zero."""
    a.li(T1, addr).op(lw(A0, T1, 0), addi(A1, A0, 0)).li(T2, exp).li(T3, mask)
    a.op(xor_(A0, A0, T2), and_(A0, A0, T3)).br("beq", A0, ZERO, f"ok_{tag}")
    a.op(sw(A1, GP, OFF["FAIL"] + 4))
    a.li(T0, code).op(sw(T0, GP, OFF["FAIL"]), FENCE).j("halt")
    a.label(f"ok_{tag}")


def _dma_copy(a: Asm, src: int, dst: int, tag: str) -> None:
    """One 4-byte secure DMA copy, polled to DONE or ERROR (bounded); logs STATUS."""
    _store_const(a, STATUS, ST_CLEAN_W1C)
    for reg, val in (
        ("SRC_ADDR_LO", src),
        ("SRC_ADDR_HI", 0),
        ("DST_ADDR_LO", dst),
        ("DST_ADDR_HI", 0),
        ("TOTAL_DATA_SIZE", 4),
        ("CHUNK_DATA_SIZE", 4),
        ("TRANSFER_WIDTH", 2),
        ("SRC_CONFIG", addr_cfg(True, False)),
        ("DST_CONFIG", addr_cfg(True, False)),
    ):
        _store_const(a, SECURE_DMA.addr(reg), val)
    a.op(FENCE)
    _store_const(a, CONTROL, control_word(opcode=OP_COPY, initial=1, go=1))
    a.li(T1, STATUS).li(T2, DMA_POLL).li(T3, ST_DONE | ST_ERROR | ST_ABORTED)
    a.label(f"dma_{tag}").op(lw(A0, T1, 0), and_(A1, A0, T3)).br("bne", A1, ZERO, f"dmax_{tag}")
    a.op(addi(T2, T2, -1)).br("bne", T2, ZERO, f"dma_{tag}")
    a.label(f"dmax_{tag}").op(sw(A0, GP, OFF["DMA_ST"]), FENCE)


def build_rom() -> SepRomImage:
    """Boot stub, trap handler and NMI handler; every other word 0."""
    img = SepRomImage(fill=0)
    stub = Asm(ROM_BASE)
    stub.li(T0, ROM_HANDLER).op(csrw(CSR_MTVEC, T0)).li(T0, ICCM_BASE).op(jalr(ZERO, T0, 0))
    h = Asm(ROM_HANDLER)
    h.op(csrr(T6, CSR_MCAUSE), sw(T6, GP, OFF["TRAP_CAUSE"]))
    h.op(csrr(T6, CSR_MTVAL), sw(T6, GP, OFF["TRAP_VAL"]), FENCE, addi(S11, S11, 1))
    h.op(csrr(T6, CSR_MSCRATCH), csrw(CSR_MEPC, T6), MRET)
    n = Asm(ROM_NMI)
    n.op(csrr(T6, CSR_MCAUSE), sw(T6, GP, OFF["NMI"]), csrr(T6, CSR_MDSEAC))
    n.op(sw(T6, GP, OFF["NMI_ADDR"]), FENCE, csrw(CSR_MDEAU, ZERO), MRET)
    for asm in (stub, h, n):
        img.place_insns(asm.base - ROM_BASE, asm.words())
    if stub.nbytes > ROM_HANDLER - ROM_BASE or h.nbytes > ROM_NMI - ROM_HANDLER:
        raise RuntimeError("ROM images overlap")
    return img


def build_marker(p: _Plan) -> Asm:
    a = Asm(ICCM_BASE + p.mark_off)
    a.li(T5, p.mark_val).op(sw(T5, GP, OFF["MARKV"]), FENCE, jalr(ZERO, RA, 0))
    return a


def build_main(p: _Plan) -> Asm:
    a = Asm(ICCM_BASE)
    a.li(T0, MRAC_SEP).op(csrw(CSR_MRAC, T0))
    a.li(GP, MBX).op(addi(S11, ZERO, 0))
    _store_const(a, NMI_VEC_ADDR, ROM_NMI)
    # Step 3: the outbound filter entry and the DMA range, each read back.
    for reg, val in FILTER_ENTRY:
        _store_const(a, _OUTF.addr(reg), val & 0xFFFF_FFFF)
        _store_const(a, _OUTF.addr(reg) + 4, val >> 32)
    a.op(FENCE)
    for reg, val in FILTER_ENTRY:
        m = _OUTF.mask(reg)
        _fail_if_ne(a, _OUTF.addr(reg), val, m & 0xFFFF_FFFF, 0x100 | len(a.labels), f"{reg}_lo")
        _fail_if_ne(a, _OUTF.addr(reg) + 4, val >> 32, m >> 32, 0x100 | len(a.labels), f"{reg}_hi")
    rng_regs = ((RANGE_BASE, 0), (RANGE_LIMIT, 0xFFFF_FFFF), (RANGE_VALID, 1))
    for addr, val in rng_regs:
        _store_const(a, addr, val)
    a.op(FENCE)
    for name, (addr, val) in zip(
        ("ENABLED_MEMORY_RANGE_BASE", "ENABLED_MEMORY_RANGE_LIMIT", "RANGE_VALID"), rng_regs
    ):
        _fail_if_ne(a, addr, val, SECURE_DMA.mask32(name), 0x200 | len(a.labels), name)
    # Staged SRAM words: the load word, the DMA sources and a readback word that
    # differs from W.
    _store_const(a, p.sram_ld, p.sram_ld_val)
    _store_const(a, SRAM_A, p.sram_a_val)
    _store_const(a, SRAM_S, p.sram_s_val)
    _store_const(a, SRAM_R, ~p.w_val & 0xFFFF_FFFF)
    a.op(FENCE)
    # Step 4: copy a routine to the SRAM, call it and return.
    for k, insn in enumerate((addi(ZERO, ZERO, 0x5A5), jalr(ZERO, RA, 0))):
        _store_const(a, SRAM_RT + 4 * k, insn)
    a.op(FENCE, FENCE_I).li(T0, SRAM_RT).op(jalr(RA, T0, 0))
    # Step 5: one ROM load and one SRAM load, each between two markers.
    _gate(a, 1)
    _mark(a, "ROMLD_B")
    a.li(T0, p.rom_ld).op(lw(A0, T0, 0), sw(A0, GP, OFF["ROMLD_V"]))
    _mark(a, "ROMLD_E")
    _mark(a, "SRAMLD_B")
    a.li(T0, p.sram_ld).op(lw(A0, T0, 0), sw(A0, GP, OFF["SRAMLD_V"]))
    _mark(a, "SRAMLD_E")
    _gate(a, 0)
    # Step 6: extension-port read (its bus error ends in an NMI) and the
    # outbound store.
    _mark(a, "EXT_B")
    a.la(T0, "ext_rec").op(csrw(CSR_MSCRATCH, T0))
    a.li(T0, EXT_ADDR).op(lw(A0, T0, 0), FENCE)
    a.label("ext_rec").li(T2, NMI_WAIT)
    a.label("ext_spin").op(addi(T2, T2, -1)).br("bne", T2, ZERO, "ext_spin")
    _mark(a, "EXT_E")
    _mark(a, "OUT_B")
    _store_const(a, OUT_ADDR, OUT_VAL)
    _mark(a, "OUT_E")
    # Step 7: a fetch at each unmapped target; the ROM handler resumes at
    # the recovery address.
    for k, u in enumerate(p.u):
        _gate(a, 1)
        _mark(a, f"FB{k}")
        a.la(T0, f"rec{k}").op(csrw(CSR_MSCRATCH, T0))
        a.li(T1, u).op(jalr(ZERO, T1, 0))
        a.label(f"rec{k}")
        _mark(a, f"FE{k}")
        _gate(a, 0)
    # Step 8: the ICCM marker code and the DCCM patterns.
    _gate(a, 1)
    _mark(a, "CORE_B")
    a.li(T0, ICCM_BASE + p.mark_off).op(jalr(RA, T0, 0))
    _mark(a, "CORE_M")
    for off, pat in zip(p.dccm_offs, p.pattern):
        _store_const(a, DCCM_BASE + off, pat)
    a.op(FENCE)
    for off in p.dccm_offs:
        # A fence after each record store keeps the core from merging the
        # stores to one mailbox slot.
        a.li(T1, DCCM_BASE + off).op(lw(A0, T1, 0), sw(A0, GP, OFF["DCCMV"]), FENCE)
    _mark(a, "CORE_E")
    _gate(a, 0)
    # Step 9: DMA copy of an SRAM word to a DCCM word (control).
    _mark(a, "DMA1_B")
    _dma_copy(a, SRAM_A, p.dccm_d1, "d1")
    _mark(a, "DMA1_E")
    # Step 10: LSU load and store at the ICCM word W.
    _gate(a, 1)
    _mark(a, "LSUL_B")
    a.la(T0, "il_rec").op(csrw(CSR_MSCRATCH, T0))
    a.li(A0, ~p.w_val & 0xFFFF_FFFF).li(T1, p.iccm_w).op(lw(A0, T1, 0))
    a.label("il_rec").op(sw(A0, GP, OFF["ILOAD"]))
    _mark(a, "LSUL_E")
    _mark(a, "LSUS_B")
    a.la(T0, "is_rec").op(csrw(CSR_MSCRATCH, T0))
    a.li(T1, p.iccm_w).li(T2, p.v_val).op(sw(T2, T1, 0))
    a.label("is_rec").op(FENCE)
    _mark(a, "LSUS_E")
    _gate(a, 0)
    _mark(a, "DMA2_B")
    _dma_copy(a, p.iccm_w, SRAM_R, "d2")
    a.li(T1, SRAM_R).op(lw(A0, T1, 0), sw(A0, GP, OFF["IREAD"]))
    _mark(a, "DMA2_E")
    _mark(a, "DMA3_B")
    _dma_copy(a, SRAM_S, p.iccm_d2, "d3")
    _mark(a, "DMA3_E")
    # Step 11: the DCCM pair.
    _mark(a, "PAIR_B")
    a.li(T0, p.dccm_k).op(lw(A0, T0, 0), sw(A0, GP, OFF["PAIR0"]))
    a.li(T1, p.v2_val).op(sw(T1, T0, 0), FENCE, lw(A0, T0, 0), sw(A0, GP, OFF["PAIR1"]))
    _mark(a, "PAIR_E")
    _mark(a, "DONE")
    a.label("halt").j("halt")
    if a.nbytes > p.mark_off:
        raise RuntimeError(f"the routine ({a.nbytes} bytes) overlaps the marker code")
    return a


def _hex_bytes(blobs: dict[int, bytes]) -> str:
    """A ``$readmemh`` byte image: one ``@offset`` line per blob."""
    lines = []
    for off, data in sorted(blobs.items()):
        lines.append(f"@{off:08x}")
        for k in range(0, len(data), 16):
            lines.append(" ".join(f"{b:02x}" for b in data[k : k + 16]))
    return "\n".join(lines) + "\n"


@pyuvm.test()
class sep_cpu_demux_unmapped_fetch_test(sep_base_test):
    """IFU and LSU demux targets, DECERR for an unmapped fetch, ICCM core-only."""

    build_env = False
    required_evidence = (
        "CHK-IFU-DECERR",
        "CHK-IFU-NEVER",
        "CHK-LSU-ROUTE",
        "CHK-CORE-PATH-XBAR",
        "CHK-LSU-ICCM",
        "CHK-LSU-ICCM-WE",
    )

    def _grade(self, chk: str, ok: bool, text: str) -> None:
        if ok:
            self.logger.info("%s PASS: %s", chk, text)
            self.n_checks += 1
        else:
            self.logger.error("%s FAIL: %s", chk, text)
            self.failures.append(f"{chk}: {text}")

    # ---------------------------------------------------------------- set-up
    def _draw(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        p = self.plan = _Plan(SepSeededRng(seed))
        self.logger.info("DRAW U=%s", ",".join(f"0x{u:08x}" for u in p.u))
        self.logger.info("DRAW marker_offset=0x%x marker_value=0x%08x", p.mark_off, p.mark_val)
        self.logger.info(
            "DRAW dccm_offsets=%s pattern=%s",
            ",".join(f"0x{o:x}" for o in p.dccm_offs),
            ",".join(f"0x{v:08x}" for v in p.pattern),
        )
        self.logger.info("DRAW W=0x%08x V=0x%08x", p.w_val, p.v_val)
        self.logger.info(
            "DRAW iccm_w=0x%08x iccm_dma_dst=0x%08x dccm_dma_dst=0x%08x dccm_k=0x%08x "
            "K=0x%08x V2=0x%08x rom_load=0x%08x sram_load=0x%08x",
            p.iccm_w,
            p.iccm_d2,
            p.dccm_d1,
            p.dccm_k,
            p.k_val,
            p.v2_val,
            p.rom_ld,
            p.sram_ld,
        )
        self.logger.info(
            "ENV dma_poll=%d nmi_wait=%d done_bound=%d", DMA_POLL, NMI_WAIT, DONE_BOUND
        )

    def _stage(self) -> None:
        p = self.plan
        main = build_main(p)
        marker = build_marker(p)
        itcm = {
            0: main.to_bytes(),
            p.mark_off: marker.to_bytes(),
            p.w_off: p.w_val.to_bytes(4, "little"),
        }
        dtcm = {p.k_off: p.k_val.to_bytes(4, "little")}
        cwd = os.getcwd()
        with open(os.path.join(cwd, "sep_itcm.hex"), "w") as f:
            f.write(_hex_bytes(itcm))
        with open(os.path.join(cwd, "sep_dtcm.hex"), "w") as f:
            f.write(_hex_bytes(dtcm))
        mem = cocotb.top.u_dut.u_sep_ip_integration.u_sep_boot_rom.mem
        for i, w in enumerate(build_rom().words):
            mem[i].value = w
        self.logger.info(
            "STAGE rom words=%d iccm routine=0x%08x+%d marker=0x%08x+%d W@0x%08x dccm K@0x%08x",
            ROM_WORDS,
            ICCM_BASE,
            main.nbytes,
            ICCM_BASE + p.mark_off,
            marker.nbytes,
            p.iccm_w,
            p.dccm_k,
        )

    async def _tap_default(self) -> None:
        """Reset the core TAP so the reset-vector TDR holds its default.

        The bench owns the TAP pins: ``jtag_trst_ni`` presents 1 and then 0, so
        the asynchronous TAP reset fires (a level that is low from time 0 has no
        falling edge), and it stays low for the rest of the leaf. The first fetch
        is then at the default vector, the boot ROM base (cpu.adoc, Reset Vector).
        """
        dut = cocotb.top
        for pin, val in (("jtag_tck_i", 0), ("jtag_tms_i", 1), ("jtag_tdi_i", 0)):
            self._set_pin(dut, pin, val)
        self._set_pin(dut, "jtag_trst_n_i", 1)
        self._set_pin(dut, "jtag_bench_own_i", 1)
        await Timer(1, units="ns")
        self._set_pin(dut, "jtag_trst_n_i", 0)
        await Timer(1, units="ns")
        self.logger.info("CFG core TAP reset by jtag_trst_ni 1->0; reset vector TDR at its default")

    # ---------------------------------------------------------------- scenario
    async def run_scenario(self) -> None:
        dut = cocotb.top
        self.failures: list[str] = []
        self.n_checks = 0
        self._draw()
        names = (
            "PR-OUT",
            "PR-EXT",
            "PR-ROM",
            "PR-SRAM",
            "PR-IFU",
            "PR-IFU-XBAR",
            "PR-LSU-ROM",
            "PR-LSU-XBAR",
            "PR-XBAR-TCM",
            "PR-TCM",
        )
        self.taps = {n: SepFabricTap(n) for n in names}
        self.mbx = SepMbxWords(self.taps["PR-OUT"], MBX)

        async def _pre() -> None:
            await self._tap_default()
            self._stage()
            for t in self.taps.values():
                t.start()
            dut.tcm_load_i.value = 1
            await ClockCycles(dut.clk_i, 4)
            dut.tcm_load_i.value = 0
            await ClockCycles(dut.clk_i, 4)

        await self.bring_up_cpu_boot(0, pre_reset_hook=_pre)
        gate = cocotb.start_soon(self._gate_follower())
        try:
            done = await self._wait_done()
            await ClockCycles(dut.clk_i, 8)
            self.logger.info("CTL-DONE: done record seq=%d", done.seq)
        finally:
            gate.cancel()
            close_graded_window(self.logger)
            for t in self.taps.values():
                await t.stop()
        self._grade_all()
        if self.failures:
            raise AssertionError("; ".join(self.failures))
        self.result_pass(TEST, self.random_seed(), self.n_checks)

    async def _wait_done(self):
        """The done record; a fail record or the bound ends the leaf."""
        names = {v: k for k, v in OFF.items()}
        for cyc in range(DONE_BOUND):
            fail = self.mbx.find(OFF["FAIL"])
            if fail is not None:
                raw = self.mbx.find(OFF["FAIL"] + 4)
                raise AssertionError(
                    f"routine fail marker 0x{fail.val:x} (set-up readback, read "
                    f"0x{(raw.val if raw else 0):08x})"
                )
            done = self.mbx.find(OFF["DONE"])
            if done is not None:
                return done
            if cyc % PROGRESS == 0:
                recs = self.mbx.records()
                self.logger.info(
                    "progress cyc=%d records=%d last=%s",
                    cyc,
                    len(recs),
                    ",".join(f"{names.get(r.off, hex(r.off))}=0x{r.val:x}" for r in recs[-4:]),
                )
            await RisingEdge(cocotb.top.clk_i)
        recs = self.mbx.records()
        raise AssertionError(
            f"no done record within {DONE_BOUND} clk_i cycles; last records "
            + ",".join(f"{names.get(r.off, hex(r.off))}=0x{r.val:x}" for r in recs[-6:])
        )

    async def _gate_follower(self) -> None:
        """Open or close the graded window on each gate record of the routine."""
        seen = 0
        while True:
            await RisingEdge(cocotb.top.clk_i)
            # Beats of the previous edge are recorded; a write is legal here.
            recs = self.mbx.since(seen, OFF["GATE"])
            seen = self.mbx.mark()
            for r in recs:
                if r.val:
                    open_graded_window(TEST, self.logger)
                else:
                    close_graded_window(self.logger)

    # ---------------------------------------------------------------- windows
    def _t_lsu(self, name: str) -> int:
        hits = [
            b.t_ps
            for b in self.taps["PR-LSU-XBAR"].beats
            if b.ch == "aw" and b.addr is not None and (b.addr & ~7) == MBX + OFF[name]
        ]
        if len(hits) != 1:
            raise AssertionError(f"marker {name}: {len(hits)} AW handshakes on PR-LSU-XBAR")
        return hits[0]

    def _t_out(self, name: str) -> int:
        r = self.mbx.find(OFF[name])
        if r is None:
            raise AssertionError(f"marker {name}: no mailbox record")
        return r.t_ps

    def _win(self, b: str, e: str) -> tuple[int, int]:
        """From the begin marker on PR-LSU-XBAR to the end marker on PR-OUT."""
        return self._t_lsu(b), max(self._t_lsu(e), self._t_out(e))

    def _beats(self, tap: str, w: tuple[int, int], chs=None) -> list:
        return [
            b
            for b in self.taps[tap].beats
            if w[0] <= b.t_ps <= w[1] and (chs is None or b.ch in chs)
        ]

    def _recs(self, b: str, e: str, name: str) -> list:
        rb, re_ = self.mbx.find(OFF[b]), self.mbx.find(OFF[e])
        return [r for r in self.mbx.records()[rb.seq : re_.seq] if r.off == OFF[name]]

    # ---------------------------------------------------------------- grading
    def _grade_all(self) -> None:
        self._log_dma_csr_writes()
        for step in (
            self._grade_ifu,
            self._grade_route,
            self._grade_core,
            self._grade_iccm,
        ):
            try:
                step()
            except AssertionError as exc:
                self.failures.append(f"{step.__name__}: {exc}")
                self.logger.error("%s: %s", step.__name__, exc)

    def _grade_ifu(self) -> None:
        p = self.plan
        ifu = self.taps["PR-IFU"].beats
        rom_req = [b for b in self.taps["PR-ROM"].beats if b.ch == "req"]
        sram_req = [b for b in self.taps["PR-SRAM"].beats if b.ch == "req"]
        ifu_ar = [b for b in ifu if b.ch == "ar" and b.addr is not None]
        ctl_rom = sum(1 for b in ifu_ar if ROM_BASE <= b.addr < ROM_BASE + ROM_BYTES)
        ctl_sram = sum(1 for b in ifu_ar if SRAM_RT <= b.addr < SRAM_RT + 8)
        rt_off = (SRAM_RT - SRAM_BASE) >> 3
        ctl_sram_port = sum(
            1 for b in sram_req if b.addr is not None and (b.addr & (SRAM_BYTES - 1)) >> 3 == rt_off
        )
        ctl_rom_port = sum(1 for b in rom_req if b.we == 0)
        # The IFU demux port to the local crossbar: the SRAM fetch of the copied
        # routine is its control; a request outside the SRAM is a misroute.
        xbar_ar = [b for b in self.taps["PR-IFU-XBAR"].beats if b.ch == "ar"]
        ctl_xbar = sum(1 for b in xbar_ar if b.addr is not None and SRAM_RT <= b.addr < SRAM_RT + 8)
        ctl_ok = ctl_rom >= 1 and ctl_sram >= 1 and ctl_rom_port >= 1 and ctl_sram_port >= 1
        ctl_ok = ctl_ok and ctl_xbar >= 1
        e0 = self._win("EXT_B", "EXT_E")
        ext_ctl = sum(
            1
            for b in self._beats("PR-EXT", e0, ("ar",))
            if b.addr is not None and b.addr == EXT_ADDR
        )
        o0 = self._win("OUT_B", "OUT_E")
        out_ctl = sum(
            1
            for b in self._beats("PR-OUT", o0, ("aw",))
            if b.addr is not None and (b.addr & ~7) == OUT_ADDR
        )
        for k, u in enumerate(p.u):
            w = self._win(f"FB{k}", f"FE{k}")
            ars = [b for b in ifu_ar if w[0] <= b.t_ps <= w[1] and b.addr == u]
            xbar_n = sum(
                1
                for b in xbar_ar
                if w[0] <= b.t_ps <= w[1]
                and (b.addr is None or not SRAM_BASE <= b.addr < SRAM_BASE + SRAM_BYTES)
            )
            causes = self._recs(f"FB{k}", f"FE{k}", "TRAP_CAUSE")
            tvals = self._recs(f"FB{k}", f"FE{k}", "TRAP_VAL")
            self.logger.info(
                "OBS-IFU-TRAP LOG fetch=0x%08x mcause=%s mtval=%s",
                u,
                ",".join(f"0x{r.val:x}" for r in causes) or "-",
                ",".join(f"0x{r.val:08x}" for r in tvals) or "-",
            )
            resp = None
            rom_n = sram_n = -1
            if ars:
                ar = ars[0]
                rs = [b for b in ifu if b.ch == "r" and b.t_ps > ar.t_ps and b.id == ar.id]
                if rs:
                    burst = []
                    for b in rs:
                        burst.append(b)
                        if b.last:
                            break
                    resps = {b.resp for b in burst}
                    resp = resps.pop() if len(resps) == 1 else None
                    t_r = burst[-1].t_ps
                    rom_n = sum(1 for b in rom_req if ar.t_ps <= b.t_ps <= t_r)
                    sram_n = sum(1 for b in sram_req if ar.t_ps <= b.t_ps <= t_r)
            self._grade(
                "CHK-IFU-DECERR",
                resp == RESP_DECERR and rom_n == 0 and sram_n == 0 and xbar_n == 0 and ctl_ok,
                f"fetch=0x{u:08x} resp={'X' if resp is None else ('DECERR' if resp == RESP_DECERR else resp)} "
                f"rom_req={rom_n} sram_req={sram_n} ifu_xbar_req_outside_sram={xbar_n} "
                f"control_rom={ctl_rom} control_sram={ctl_sram} "
                f"control_rom_port={ctl_rom_port} control_sram_port={ctl_sram_port} "
                f"control_ifu_xbar_sram={ctl_xbar} ifu_req_at_U={len(ars)}",
            )
            ext_seen = sum(
                1
                for b in self._beats("PR-EXT", w, ("ar", "aw"))
                if b.addr is None or (b.addr & 0xFFFF_FFFF) == u
            )
            out_seen = sum(
                1
                for b in self._beats("PR-OUT", w, ("ar", "aw"))
                if b.addr is None or (b.addr & 0xFFFF_FFFF) == u
            )
            self._grade(
                "CHK-IFU-NEVER",
                ext_seen == 0
                and out_seen == 0
                and xbar_n == 0
                and ext_ctl >= 1
                and out_ctl >= 1
                and ctl_xbar >= 1
                and len(ars) >= 1,
                f"target=0x{u:08x} ext_seen={ext_seen} out_seen={out_seen} "
                f"ifu_xbar_req_outside_sram={xbar_n} lsu_ext_seen={ext_ctl} "
                f"lsu_out_seen={out_ctl} control_ifu_xbar_sram={ctl_xbar} ifu_req_at_U={len(ars)}",
            )
        # Each NMI record with the last marker before it and its D-bus error address.
        names = {v: k for k, v in OFF.items()}
        last, rows = "-", []
        recs = self.mbx.records()
        for i, r in enumerate(recs):
            if r.off == OFF["NMI"]:
                nxt = recs[i + 1].val if i + 1 < len(recs) else 0
                rows.append(f"0x{r.val:08x}@{last}/0x{nxt:08x}")
            elif names.get(r.off, "").endswith(("_B", "_E", "_M")) or r.off in (
                OFF["FB0"],
                OFF["FB1"],
                OFF["FB2"],
                OFF["FE0"],
                OFF["FE1"],
                OFF["FE2"],
            ):
                last = names[r.off]
        self.logger.info(
            "OBS-EXT-READ LOG nmi_records=%d mcause@marker/mdseac=%s",
            len(rows),
            " ".join(rows) or "-",
        )

    def _log_dma_csr_writes(self) -> None:
        """OBS: each LSU write to the secure DMA registers, with its shape and BRESP."""
        lo = SECURE_DMA.addr("STATUS") & ~0xFFF
        beats = self.taps["PR-LSU-XBAR"].beats
        aws = [b for b in beats if b.ch == "aw"]
        ws = [b for b in beats if b.ch == "w"]
        bs = [b for b in beats if b.ch == "b"]
        used: set[int] = set()
        rows = []
        for k, aw in enumerate(aws):
            if aw.addr is None or not lo <= aw.addr < lo + 0x1000:
                continue
            w = ws[k] if k < len(ws) else None
            b = next(
                (x for x in bs if x.seq not in used and x.id == aw.id and x.seq > aw.seq), None
            )
            if b is not None:
                used.add(b.seq)
            rows.append(
                f"0x{aw.addr:08x}/sz{aw.size}/strb=0x{(w.strb if w else 0):02x}"
                f"/resp={'X' if b is None else b.resp}"
            )
        self.logger.info("OBS-DMA-CSR-WRITE LOG writes=%d %s", len(rows), " ".join(rows))

    def _grade_route(self) -> None:
        p = self.plan
        w_rom = self._win("ROMLD_B", "ROMLD_E")
        w_sram = self._win("SRAMLD_B", "SRAMLD_E")
        rom_w = (p.rom_ld - ROM_BASE) >> 3
        rom_on_rom = sum(
            1
            for b in self._beats("PR-LSU-ROM", w_rom, ("ar",))
            if b.addr is not None and (b.addr - ROM_BASE) >> 3 == rom_w
        )
        rom_on_xbar = sum(
            1
            for b in self._beats("PR-LSU-XBAR", w_rom, ("ar", "aw"))
            if b.addr is None or ROM_BASE <= b.addr < ROM_BASE + ROM_BYTES
        )
        sram_on_xbar = sum(
            1
            for b in self._beats("PR-LSU-XBAR", w_sram, ("ar",))
            if b.addr is not None and (b.addr & ~7) == (p.sram_ld & ~7)
        )
        sram_on_rom = len(self._beats("PR-LSU-ROM", w_sram))
        self._grade(
            "CHK-LSU-ROUTE",
            rom_on_rom >= 1 and rom_on_xbar == 0 and sram_on_xbar >= 1 and sram_on_rom == 0,
            f"rom_addr_lsu_rom_req={rom_on_rom} lsu_xbar_req_for_rom={rom_on_xbar} "
            f"sram_addr_lsu_xbar_req={sram_on_xbar} lsu_rom_req_for_sram={sram_on_rom}",
        )

    def _grade_core(self) -> None:
        p = self.plan
        marks = self._recs("CORE_B", "CORE_M", "MARKV")
        pats = self._recs("CORE_M", "CORE_E", "DCCMV")
        ctl = len(marks) == 1 and marks[0].val == p.mark_val
        ctl = ctl and [r.val for r in pats] == p.pattern
        self.logger.info(
            "CTL-CORE-PATH: mem=iccm_fetch addr=0x%08x value=%s exp=0x%08x",
            ICCM_BASE + p.mark_off,
            ",".join(f"0x{r.val:08x}" for r in marks) or "-",
            p.mark_val,
        )
        for off, pat, r in zip(p.dccm_offs, p.pattern, pats + [None] * len(p.pattern)):
            self.logger.info(
                "CTL-CORE-PATH: mem=dccm addr=0x%08x value=%s exp=0x%08x",
                DCCM_BASE + off,
                "X" if r is None else f"0x{r.val:08x}",
                pat,
            )
        if not ctl:
            self.failures.append("CTL-CORE-PATH: marker or DCCM pattern differs (precondition)")
            self.logger.error("CTL-CORE-PATH FAIL: precondition failed")
        windows = [
            self._win("CORE_B", "CORE_M"),
            self._win("CORE_M", "CORE_E"),
        ]
        lsu = [self._win("LSUL_B", "LSUL_E"), self._win("LSUS_B", "LSUS_E")]
        seen = sum(len(self._beats("PR-XBAR-TCM", w)) for w in windows + lsu)
        ctl_dma = len(self._beats("PR-XBAR-TCM", self._win("DMA1_B", "DMA1_E"), ("aw", "w")))
        self._grade(
            "CHK-CORE-PATH-XBAR",
            ctl and seen == 0 and ctl_dma >= 1,
            f"core_windows={len(windows)} lsu_iccm_windows={len(lsu)} xbar_tcm_seen={seen} "
            f"control_dma_xbar_tcm_seen={ctl_dma}",
        )

    def _grade_iccm(self) -> None:
        p = self.plan
        traps = self._recs("LSUL_B", "LSUL_E", "TRAP_CAUSE")
        straps = self._recs("LSUS_B", "LSUS_E", "TRAP_CAUSE")
        iload = self._recs("LSUL_B", "LSUL_E", "ILOAD")
        iread = self._recs("DMA2_B", "DMA2_E", "IREAD")
        dma_st = [r.val for r in self.mbx.records() if r.off == OFF["DMA_ST"]]
        pair0 = self._recs("PAIR_B", "PAIR_E", "PAIR0")
        pair1 = self._recs("PAIR_B", "PAIR_E", "PAIR1")
        load_val = iload[0].val if iload else None
        load_ne_w = int(bool(traps) or (load_val is not None and load_val != p.w_val))
        macro = iread[0].val if iread else None
        dccm_rw = int(
            len(pair0) == 1
            and len(pair1) == 1
            and pair0[0].val == p.k_val
            and pair1[0].val == p.v2_val
        )
        self.logger.info(
            "OBS-LSU-ICCM LOG load_mcause=%s store_mcause=%s load_value=%s dma_status=%s",
            ",".join(f"0x{r.val:x}" for r in traps) or "-",
            ",".join(f"0x{r.val:x}" for r in straps) or "-",
            "X" if load_val is None else f"0x{load_val:08x}",
            ",".join(f"0x{v:08x}" for v in dma_st),
        )
        self._grade(
            "CHK-LSU-ICCM",
            load_ne_w == 1 and macro == p.w_val and dccm_rw == 1,
            f"store=0x{p.v_val:08x} macro=0x{(macro if macro is not None else 0):08x} "
            f"load_ne_W={load_ne_w} control_dccm_rw={dccm_rw} W=0x{p.w_val:08x} "
            f"load_trap={int(bool(traps))}",
        )
        tcm = "PR-TCM"
        we_st = sum(
            1
            for b in self._beats(tcm, self._win("LSUS_B", "LSUS_E"), ("iccm",))
            if b.wren is None or b.wren != 0
        )
        we_ctl = sum(
            1
            for b in self._beats(tcm, self._win("DMA3_B", "DMA3_E"), ("iccm",))
            if b.wren is not None and b.wren != 0
        )
        dccm_we = sum(
            1
            for b in self._beats(tcm, self._win("PAIR_B", "PAIR_E"), ("dccm",))
            if b.wren is not None and b.wren != 0
        )
        self.logger.info("OBS-DCCM-WE LOG pair_store_dccm_we=%d", dccm_we)
        self._grade(
            "CHK-LSU-ICCM-WE",
            we_st == 0 and we_ctl >= 1,
            f"iccm_we={we_st} control_dma_iccm_we={we_ctl}",
        )
