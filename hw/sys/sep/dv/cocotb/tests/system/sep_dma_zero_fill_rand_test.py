# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure DMA zero fill (OPCODE 4): the image, the beats, the erase window, errors and abort.

RANDOMIZED (SepSeededRng from the run seed). The leaf programs the secure DMA
over the CPU-LSU splice (no CPU) and keeps every buffer in SEP SRAM
(``memory_map.adoc``). A zero fill writes zeros to the destination without
reading the source, writes only inside the enabled memory range (checked on
every beat), and is rejected in hardware handshake mode (``dma.hjson``,
CONTROL.OPCODE; ``hw/sys/sep/doc/dma.adoc``, Zero Fill). The expected image and
beats come from ``env/sep_dma_model.DmaZeroFill``.

* Leg Z: one fill per destination mode {INCREMENT, INCREMENT and WRAP, fixed}
  and TRANSFER_WIDTH encoding {0, 1, 2}: a drawn chunk size and chunk count
  (two to four chunks for INCREMENT and for WRAP; one chunk of at least two
  beats for the fixed destination), a drawn start offset inside the 64-bit
  beat, and a drawn total whose last beat can be narrower than the width. So
  the beat addresses of each mode differ from those of the other two modes.
  A copy of non-zero words runs just before each fill, so the data register
  holds a non-zero word when the fill starts.
* Leg W: the enabled memory range around a drawn block, with DMA_DONE and
  DMA_ERROR enabled in INTR_ENABLE: a fill of the whole range; fills that start
  below BASE (by words at width 4, by one byte at width 1), that run past LIMIT
  in one chunk, and that cross LIMIT in a later chunk; a fill whose narrow last
  beat ends on an unaligned LIMIT; a copy outside the range.
* Leg E: OPCODE 5, then a fill in hardware handshake mode with the SPI trigger
  held high by SPI CONTROL.TX_WATERMARK 1 and an empty TX FIFO
  (``hw/sys/sep/doc/spi.adoc``, DMA Trigger).
* Leg A: a fill aborted at a drawn fraction of the clean time of the same fill,
  then a recovery fill.
* Leg S: a fill with SRC_ADDR_SPACE_ID drawn outside the ADDR_SPACE_ID
  encodings {0x7, 0xA, 0x9} and DST_ADDR_SPACE_ID 0x7, then the same fill with
  SRC_ADDR_SPACE_ID 0x7 (``hw/sys/sep/doc/dma.adoc``, Zero Fill: the source
  registers are validated as for a copy).
* Leg X: one fill to the SEP SRAM through the local alias window
  (``hw/sys/sep/doc/fabric.adoc``, local alias; ``hw/sys/sep/doc/memory_map.adoc``)
  in a drawn destination mode and width, shaped as a Leg Z cell. The DMA
  checks each fill write against BASE and LIMIT before it issues it, and the
  local-alias remapper follows the engine (``hw/sys/sep/doc/dma.adoc``, Zero
  Fill and data path), so BASE and LIMIT are programmed in the alias form around
  the alias destination. The tap is after the remap, so the expected beats and
  image are those of the same fill at the direct address. The SEP SRAM range is
  restored after it.
* Leg B: a width-1 fill whose destination is BASE = LIMIT, total 2 to 4 bytes.
  ERROR_CODE.BASE_LIMIT_ERROR names an "invalid value" of the pair without a
  rule for BASE = LIMIT, so the outcome is logged only.
* Leg L, last because the lock holds until reset: RANGE_REGWEN written False,
  a write that would widen LIMIT, then a fill that runs past the locked LIMIT.

Probes: register and SRAM frontdoor over ``s_axi``; ``dma_axi_req_probe_o`` and
``dma_status_probe_o`` through ``env/sep_dma_tap.py``; ``dma_busy_probe_o``;
bits 8 and 10 of ``sep_internal_interrupts_probe_o`` (PIC sources 9 and 11);
``spi_lsio_trigger_probe_o``. No inject. Each fill or copy window fails
(``DMA-TAP-WINDOW FAIL``) unless the tap sampled every clock from GO to
BUSY=0, so an empty AR or AW list is proof of no traffic.

Checkers (log shape ``CHK-<ID> PASS|FAIL seed=<n> ...``):
  CHK-DMA-ZERO-IMAGE     per Leg Z cell: every word of the destination span
                         equals the model (cleared bytes 0, every other byte
                         unchanged); DONE=1, ERROR=0, ERROR_CODE=0.
  CHK-DMA-ZERO-BEAT      per Leg Z cell: no AR handshake; one AW per model
                         beat with AxLEN 0, AxADDR[31:2] and the WSTRB lanes
                         of that beat; one OKAY B per AW. The start address
                         of each beat (AxADDR and the lowest WSTRB lane)
                         follows the destination mode (``secure_dma.adoc``,
                         DST_CONFIG): fixed, every beat at the destination;
                         INCREMENT, beat k at the destination + k * width;
                         WRAP, back to the destination at each chunk end.
                         Controls (else CTRL-MISSING): the 4-byte-wide copy
                         before the fill records one AR handshake per source
                         word, at the source word addresses, through the same
                         tap; DST_CONFIG and TRANSFER_WIDTH, read after
                         programming and before GO, read back the values
                         written (``CTRL-DMA-ZERO-BEAT``); the drawn shape
                         gives each mode a beat-address list that differs from
                         those of the other two modes.
  CHK-DMA-ZERO-RESIDUE   per Leg Z cell: the cleared bytes read 0 although the
                         last word of the copy before the fill is non-zero.
                         Control: the copy destination, zeroed before the
                         copy, reads back equal to the non-zero source words,
                         else CTRL-MISSING.
  CHK-DMA-ZERO-WIN-OK    the fill of the whole range completes, clears the
                         range and leaves the guards. Control
                         (``CTRL-DMA-ZERO-WIN-OK``, else CTRL-MISSING): BASE
                         and LIMIT read back the values written, before GO.
  CHK-DMA-ZERO-WIN-ERR   per out-of-range fill: ERROR=1 with ERROR_CODE equal
                         to DST_ADDR_ERROR alone; no AR; one AW per in-range
                         model beat with AxLEN 0, AxADDR[31:2] and the WSTRB
                         lanes of that beat, and no other AW or W; one OKAY B
                         per AW; the in-range beats cleared and every other
                         byte unchanged.
  CHK-DMA-ZERO-WIN-EXACT the fill whose narrow last beat ends on an unaligned
                         LIMIT completes and leaves the bytes after LIMIT.
                         Control (``CTRL-DMA-ZERO-WIN-EXACT``, else
                         CTRL-MISSING): BASE and LIMIT read back the values
                         written, before GO.
  CHK-DMA-ZERO-COPY-CTRL a copy whose destination is outside the range
                         completes with the data copied (control: the range
                         bounds a fill, not a copy).
  CHK-DMA-ZERO-IRQ       PIC sources 9 and 11 are low before the fill; PIC
                         source 9 rises for the completed fill of the whole
                         range and PIC source 11 does not; PIC source 11 rises
                         for the fill past LIMIT and PIC source 9 does not.
  CHK-DMA-ZERO-OPC       OPCODE 5 sets ERROR with ERROR_CODE equal to
                         OPCODE_ERROR alone and moves no beat; after the W1C of
                         ERROR a fill completes.
  CHK-DMA-ZERO-HS        a fill in handshake mode sets ERROR with ERROR_CODE
                         equal to OPCODE_ERROR alone, moves no beat and leaves
                         the destination. Control: the trigger probe reads 1
                         when GO is written.
  CHK-DMA-ZERO-ABORT     ABORTED reads 1; the destination is whole zero words
                         followed by the sentinel words, at least one of each,
                         and reads the same again after a quarter of the clean
                         time; ABORTED clears by W1C; the recovery fill clears
                         the whole destination.
  CHK-DMA-ZERO-SRC-ASID  the Leg S fill sets ERROR with DONE=0 and ERROR_CODE
                         equal to ASID_ERROR alone; no AR, AW or W from GO to
                         BUSY=0; the destination and its guards unchanged.
                         Positive probe in the same line: the same fill with
                         SRC_ADDR_SPACE_ID 0x7 then completes with ERROR_CODE
                         0, one AW per model beat and the model image, else
                         CTRL-MISSING.
  CHK-DMA-ZERO-WIN-LOCK  RANGE_REGWEN reads other than True after it is written
                         False and LIMIT keeps its value through a later write
                         of LIMIT + 64 (its response is logged as
                         ``OBS-DMA-ZERO-LOCK-RESP``, not graded);
                         a fill past LIMIT then ends in DST_ADDR_ERROR with
                         the AW, W and B shape of CHK-DMA-ZERO-WIN-ERR for
                         the beats up to LIMIT and no beat beyond it.

  CHK-DMA-ALIAS-FORM     the Leg X fill: DONE=1, ERROR=0, ERROR_CODE=0; no AR;
                         one AW per model beat at the direct address with
                         AxLEN 0, AxADDR[31:2] and the WSTRB lanes of that
                         beat; one OKAY B per AW; the destination region
                         equals the direct-form model. Controls (else
                         CTRL-MISSING): SEP_LOCAL_BASE_ADDR reads its reset
                         value, and BASE, LIMIT and DST_ADDR_LO, read before
                         GO, read back the alias-form values written.

Logged only: ``OBS-DMA-ZERO-ABORT``, the AR and AW handshakes after the ABORTED
rise (``sep_dma_abort_recovery_rand_test`` grades that contract);
``OBS-DMA-ZF-BASELIM``, STATUS, ERROR_CODE, the AW list (address, WSTRB) and the
words around BASE after the Leg B fill; ``OBS-DMA-ZERO-LOCK-RESP``, the response
of the Leg L write of LIMIT + 64 under the lock (no specification text names
the response of a write to a locked register).

Run mode: no_cpu, target ``lsu_stub_all_live``, ``+skip_fuse_sense``; Verilator
and VCS. Graded-window owner code from ``tb/sep_fcov_owner_codes.svh``. The
window opens one clock before the initial GO of each graded zero fill and
closes when that fill ends. The set-up, the copies, the OPCODE 5 start, the
reference fill and the recovery fill of Leg A and the control fill of Leg S run
with the window closed. After every check of a graded fill passed, the leaf
raises ``dma_zero_pass`` (``env/sep_fcov_gate.set_dma_zero_pass``) for two
clocks; the sampler samples the cells it held for that fill only then.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import SepBitWatch
from env.sep_dma_model import BUS_BYTES, DmaZeroFill, ZeroBeat, bytes_to_words, words_to_bytes
from env.sep_dma_tap import DmaTapEvents, SepDmaTap
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_dma_zero_pass
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL, SPI_CONTROLLER, sym
from seq_lib.sep_dma_ops import (
    _D,
    ADDR_SPACE_ID,
    DST_ADDR_HI,
    DST_ADDR_LO,
    DST_CONFIG,
    ERROR_CODE,
    ERROR_CODE_MASK,
    HANDSHAKE_INTR_ENABLE,
    INTR_ENABLE,
    OP_COPY,
    OP_ZERO,
    RANGE_BASE,
    RANGE_LIMIT,
    RANGE_REGWEN,
    SRC_ADDR_HI,
    ST_ABORTED,
    ST_DONE,
    STATUS,
    TRANSFER_WIDTH,
    DmaStatus,
    SepDmaOps,
    SepMemWords,
    addr_cfg,
    asid_word,
    transfer_width_word,
)
from seq_lib.sep_spi_host_csr_seq import CONTROL as SPI_CONTROL

TEST = "sep_dma_zero_fill_rand_test"

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
SRAM_LIMIT = SRAM_BASE + SRAM_SIZE - 1
# The local alias window maps SEP_LOCAL_BASE_ADDR + o to the SEP map base + o.
SEP_MAP_BASE = sym("SEP_TOP_REG_MAP_BASE_ADDR")
LOCAL_BASE_REG = SEP_CPU_CTRL.addr("SEP_LOCAL_BASE_ADDR")
LOCAL_BASE_MASK = SEP_CPU_CTRL.mask32("SEP_LOCAL_BASE_ADDR")
LOCAL_ALIAS = SEP_CPU_CTRL.reset("SEP_LOCAL_BASE_ADDR")
ASID = 0x7
# The first OPCODE above ZERO.
OP_INVALID = 0x5

WIDTH = {0: 1, 1: 2, 2: 4}
# Destination mode -> (DST_CONFIG.INCREMENT, DST_CONFIG.WRAP).
MODES = {"inc": (True, False), "wrap": (True, True), "fixed": (False, False)}

DST_ERR = _D.field_mask("ERROR_CODE", "dst_addr_error")
OPC_ERR = _D.field_mask("ERROR_CODE", "opcode_error")
ASID_ERR = _D.field_mask("ERROR_CODE", "asid_error")
ASID_FIELDS = _D.mask32("ADDR_SPACE_ID")
_SRC_ASID_MASK = _D.field_mask("ADDR_SPACE_ID", "src_asid")
_SRC_ASID_LSB = _D.field_lsb("ADDR_SPACE_ID", "src_asid")
# ADDR_SPACE_ID encodings OT_ADDR 0x7, SOC_ADDR 0xa, SYS_ADDR 0x9
# (vendor/lowRISC/opentitan/upstream/hw/ip/dma/data/dma.hjson:249-259).
ASID_ENCODINGS = (0x7, 0xA, 0x9)
SRC_ASID_INVALID = tuple(
    a for a in range((_SRC_ASID_MASK >> _SRC_ASID_LSB) + 1) if a not in ASID_ENCODINGS
)
INTR_EN_DONE = _D.field_mask("INTR_ENABLE", "dma_done")
INTR_EN_ERROR = _D.field_mask("INTR_ENABLE", "dma_error")
HS_RESET = _D.reset32("HANDSHAKE_INTR_ENABLE")
HS_TRIGGER0 = 1 << _D.field_lsb("HANDSHAKE_INTR_ENABLE", "mask")
SPI_TX_WM = SPI_CONTROLLER.field_mask("CONTROL", "tx_watermark")
SPI_TX_WM_LSB = SPI_CONTROLLER.field_lsb("CONTROL", "tx_watermark")
REGWEN_MASK = _D.field_mask("RANGE_REGWEN", "regwen")
REGWEN_LSB = _D.field_lsb("RANGE_REGWEN", "regwen")
# RANGE_REGWEN is MuBi4 with reset True; False is its bitwise complement.
REGWEN_TRUE = (_D.reset32("RANGE_REGWEN") & REGWEN_MASK) >> REGWEN_LSB
REGWEN_FALSE = ~REGWEN_TRUE & (REGWEN_MASK >> REGWEN_LSB)

# PIC source n is bit n-1 of sep_internal_interrupts_probe_o.
PIC_DONE_BIT = 8
PIC_ERROR_BIT = 10

GUARD = 8  # bytes kept on each side of a destination
COPY_BYTES = 32  # the 4-byte-wide copy before each Leg Z fill: eight AR beats
ERR_POLL_BOUND = 400  # STATUS reads in a wait for ERROR or ABORTED
TRIGGER_BOUND = 200  # clocks in a wait for the SPI trigger
IRQ_SETTLE = 50  # clocks of line sampling after DONE or ERROR
BUSY_RISE_BOUND = 2_000
ABORT_REDRAWS = 3
LABEL_CLOCKS = 2  # clocks dma_zero_pass stays 1


def nonzero_word(rng: SepSeededRng) -> int:
    """A drawn 32-bit word with no zero byte."""
    return rng.getrandbits(32) | 0x0101_0101


def span(addr: int, nbytes: int) -> tuple[int, int]:
    """First address and word count of the aligned words that cover ``nbytes`` from ``addr``."""
    lo = addr & ~3
    hi = (addr + nbytes + 3) & ~3
    return lo, (hi - lo) // 4


class Alloc:
    """Disjoint 8-aligned SRAM blocks at drawn gaps, handed out in order."""

    def __init__(self, rng: SepSeededRng) -> None:
        self.rng = rng
        self.next = SRAM_BASE + 8 * rng.randrange(0, 64)

    def take(self, nbytes: int) -> int:
        addr = self.next
        self.next = (addr + nbytes + 7) & ~7
        self.next += 8 * self.rng.randrange(0, 16)
        if self.next > SRAM_LIMIT + 1:
            raise ValueError("the drawn blocks do not fit the SRAM")
        return addr


@dataclass
class Region:
    """A word span with its drawn initial words."""

    addr: int
    words: list[int]

    @property
    def nbytes(self) -> int:
        return 4 * len(self.words)

    def image(self) -> dict[int, int]:
        return words_to_bytes(self.addr, self.words)


@dataclass
class ZCell:
    mode: str
    enc: int
    fill: DmaZeroFill
    region: Region
    copy_src: Region
    copy_dst: int


@dataclass
class WDraw:
    """The Leg W block: range [base, limit] with guards outside it."""

    region: Region
    base: int
    limit: int
    below_words: int
    below_total: int
    above_words: int
    above_extra: int
    cross_chunk: int
    cross_extra: int
    exact_trim: int
    ctrl_src: Region
    ctrl_dst: Region


def draw_region(rng: SepSeededRng, alloc: Alloc, nbytes: int) -> Region:
    addr = alloc.take(nbytes)
    return Region(addr, [nonzero_word(rng) for _ in range(-(-nbytes // 4))])


def alias(addr: int) -> int:
    """The local-alias form of a SEP map address."""
    return addr - SEP_MAP_BASE + LOCAL_ALIAS


def mode_addrs(mode: str, base: int, w: int, chunk: int, n_beats: int) -> list[int]:
    """Beat start addresses the destination mode states (``secure_dma.adoc``, DST_CONFIG)."""
    if mode == "fixed":
        return [base] * n_beats
    if mode == "wrap":
        return [base + (k % (chunk // w)) * w for k in range(n_beats)]
    return [base + k * w for k in range(n_beats)]


def beat_start(aw_addr: int | None, strb: int | None) -> int | None:
    """Start address of a write beat: the bus beat of AxADDR plus its lowest WSTRB lane."""
    if aw_addr is None or not strb:
        return None
    return (aw_addr & ~(BUS_BYTES - 1)) + (strb & -strb).bit_length() - 1


def draw_zero_fill(
    rng: SepSeededRng, alloc: Alloc, mode: str, enc: int
) -> tuple[DmaZeroFill, Region]:
    """A fill of a drawn shape in ``mode`` and width ``enc``, inside a guarded region."""
    w = WIDTH[enc]
    inc, wrap = MODES[mode]
    if mode == "fixed":
        chunk = w * rng.randrange(2, 9)
        total = rng.randrange(w + 1, chunk + 1)
    else:
        n = rng.randrange(2, 5)
        chunk = w * rng.randrange(4, 33)
        total = (n - 1) * chunk + rng.randrange(1, chunk + 1)
    off = w * rng.randrange(0, 8 // w)
    probe = DmaZeroFill(off, total, chunk, enc, inc, wrap)
    reach = max(b.addr + b.nbytes for b in probe.beats())
    region = draw_region(rng, alloc, GUARD + reach + GUARD)
    return DmaZeroFill(region.addr + GUARD + off, total, chunk, enc, inc, wrap), region


class Plan:
    """Every value of the leaf, drawn from the seed before the first DUT access."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.lines: list[str] = []
        alloc = Alloc(rng)
        self._leg_z(rng, alloc)
        self._leg_w(rng, alloc)
        self._leg_e(rng, alloc)
        self._leg_a(rng, alloc)
        self._leg_l(rng, alloc)
        self._leg_s(rng, alloc)
        self._leg_x(rng, alloc)
        self._leg_b(rng, alloc)

    def _leg_z(self, rng: SepSeededRng, alloc: Alloc) -> None:
        cells = [(m, e) for m in MODES for e in WIDTH]
        rng.shuffle(cells)
        self.cells: list[ZCell] = []
        for mode, enc in cells:
            fill, region = draw_zero_fill(rng, alloc, mode, enc)
            copy_src = draw_region(rng, alloc, COPY_BYTES)
            copy_dst = alloc.take(COPY_BYTES)
            self.cells.append(ZCell(mode, enc, fill, region, copy_src, copy_dst))
            self.lines.append(
                f"DRAW leg=Z mode={mode} enc={enc} total={fill.total} chunk={fill.chunk} "
                f"n={fill.n_chunks} dst=0x{fill.dst_base:08x} region=0x{region.addr:08x}+"
                f"{region.nbytes} copy_last=0x{copy_src.words[-1]:08x}"
            )

    def _leg_w(self, rng: SepSeededRng, alloc: Alloc) -> None:
        size = 4 * rng.randrange(16, 65)
        guard = 4 * rng.randrange(2, 9)
        region = draw_region(rng, alloc, guard + size + guard)
        base = region.addr + guard
        self.w = WDraw(
            region=region,
            base=base,
            limit=base + size - 1,
            below_words=rng.randrange(1, guard // 4 + 1),
            below_total=4 * rng.randrange(1, 9),
            above_words=rng.randrange(1, min(8, size // 4) + 1),
            above_extra=4 * rng.randrange(1, 5),
            cross_chunk=4 * rng.randrange(2, 9),
            cross_extra=4 * rng.randrange(1, 5),
            exact_trim=rng.randrange(1, 4),
            ctrl_src=draw_region(rng, alloc, 16),
            ctrl_dst=draw_region(rng, alloc, 16),
        )
        d = self.w
        self.lines.append(
            f"DRAW leg=W base=0x{d.base:08x} limit=0x{d.limit:08x} guard={guard} "
            f"below_words={d.below_words} below_total={d.below_total} "
            f"above_words={d.above_words} above_extra={d.above_extra} "
            f"cross_chunk={d.cross_chunk} cross_extra={d.cross_extra} exact_trim={d.exact_trim}"
        )

    def _leg_e(self, rng: SepSeededRng, alloc: Alloc) -> None:
        self.e_region = draw_region(rng, alloc, 64)
        self.e_total = 4 * rng.randrange(2, 9)
        self.lines.append(
            f"DRAW leg=E region=0x{self.e_region.addr:08x} total={self.e_total} "
            f"opcode=0x{OP_INVALID:x}"
        )

    def _leg_a(self, rng: SepSeededRng, alloc: Alloc) -> None:
        total = 4 * rng.randrange(1024, 2049)
        self.a_region = draw_region(rng, alloc, total)
        self.a_fracs = [rng.randrange(20, 81) for _ in range(ABORT_REDRAWS + 1)]
        self.lines.append(
            f"DRAW leg=A dst=0x{self.a_region.addr:08x} total={total} "
            f"fracs={','.join(map(str, self.a_fracs))}"
        )

    def _leg_l(self, rng: SepSeededRng, alloc: Alloc) -> None:
        size = 4 * rng.randrange(8, 33)
        guard = 4 * rng.randrange(2, 5)
        self.l_region = draw_region(rng, alloc, guard + size + guard)
        self.l_base = self.l_region.addr + guard
        self.l_limit = self.l_base + size - 1
        self.l_words = rng.randrange(1, min(8, size // 4) + 1)
        self.l_extra = 4 * rng.randrange(1, 5)
        self.lines.append(
            f"DRAW leg=L base=0x{self.l_base:08x} limit=0x{self.l_limit:08x} "
            f"words={self.l_words} extra={self.l_extra}"
        )

    def _leg_s(self, rng: SepSeededRng, alloc: Alloc) -> None:
        self.s_total = 4 * rng.randrange(2, 9)
        self.s_region = draw_region(rng, alloc, GUARD + self.s_total + GUARD)
        self.s_dst = self.s_region.addr + GUARD
        self.s_asid = rng.choice(SRC_ASID_INVALID)
        self.lines.append(
            f"DRAW leg=S dst=0x{self.s_dst:08x} total={self.s_total} src_asid=0x{self.s_asid:x} "
            f"dst_asid=0x{ASID:x}"
        )

    def _leg_x(self, rng: SepSeededRng, alloc: Alloc) -> None:
        self.x_mode = rng.choice(tuple(MODES))
        self.x_enc = rng.choice(tuple(WIDTH))
        self.x_fill, self.x_region = draw_zero_fill(rng, alloc, self.x_mode, self.x_enc)
        f = self.x_fill
        self.lines.append(
            f"DRAW leg=X mode={self.x_mode} enc={self.x_enc} total={f.total} chunk={f.chunk} "
            f"n={f.n_chunks} dst=0x{f.dst_base:08x} dst_alias=0x{alias(f.dst_base):08x} "
            f"region=0x{self.x_region.addr:08x}+{self.x_region.nbytes}"
        )

    def _leg_b(self, rng: SepSeededRng, alloc: Alloc) -> None:
        self.b_region = draw_region(rng, alloc, 16)
        self.b_dst = self.b_region.addr + 4 + rng.randrange(0, 8)
        self.b_total = rng.randrange(2, 5)
        self.lines.append(
            f"DRAW leg=B base=limit=dst=0x{self.b_dst:08x} total={self.b_total} enc=0 "
            f"region=0x{self.b_region.addr:08x}+{self.b_region.nbytes}"
        )


class _EdgeCount:
    """Counts clock edges, so a tap window can prove it sampled every clock."""

    def __init__(self, clk) -> None:
        self.n = 0
        self._task = cocotb.start_soon(self._run(clk))

    async def _run(self, clk) -> None:
        while True:
            await RisingEdge(clk)
            self.n += 1

    async def stop(self) -> None:
        self._task.cancel()


@dataclass
class FillRun:
    """What one fill or copy showed: the last STATUS, ERROR_CODE and the tap window GO..BUSY=0."""

    status: DmaStatus
    error_code: int
    ev: DmaTapEvents
    go_writes: int
    dst_rb: int | None = None
    cfg_rb: tuple[int, int] | None = None


@pyuvm.test()
class sep_dma_zero_fill_rand_test(sep_base_test):
    """Secure DMA zero fill: image and beats per mode and width, erase window, errors, abort."""

    required_evidence = (
        "CHK-DMA-ZERO-IMAGE",
        "CHK-DMA-ZERO-BEAT",
        "CHK-DMA-ZERO-RESIDUE",
        "CHK-DMA-ZERO-WIN-OK",
        "CHK-DMA-ZERO-WIN-ERR",
        "CHK-DMA-ZERO-WIN-EXACT",
        "CHK-DMA-ZERO-COPY-CTRL",
        "CHK-DMA-ZERO-IRQ",
        "CHK-DMA-ZERO-OPC",
        "CHK-DMA-ZERO-HS",
        "CHK-DMA-ZERO-ABORT",
        "CHK-DMA-ZERO-SRC-ASID",
        "CHK-DMA-ZERO-WIN-LOCK",
        "CHK-DMA-ALIAS-FORM",
    )

    # ---- log helpers ------------------------------------------------------
    def _pass(self, chk: str, ok: bool, values: str) -> None:
        line = f"{chk} {'PASS' if ok else 'FAIL'} seed={self.seed} {values}"
        if not ok:
            close_graded_window(self.logger)
            self.logger.error(line)
            raise AssertionError(line)
        self.logger.info(line)
        self.k += 1

    def _ctrl_missing(self, chk: str, why: str) -> None:
        line = f"CTRL-MISSING {chk} seed={self.seed} {why}"
        close_graded_window(self.logger)
        self.logger.error(line)
        raise AssertionError(line)

    async def _range_rb(self, chk: str, base: int, limit: int) -> str:
        """Read BASE and LIMIT back before GO; CTRL-MISSING unless they equal the values written."""
        rb = (await self.ops.rd(RANGE_BASE), await self.ops.rd(RANGE_LIMIT))
        line = (
            f"base_wr=0x{base:08x} base_rb=0x{rb[0]:08x} "
            f"limit_wr=0x{limit:08x} limit_rb=0x{rb[1]:08x}"
        )
        if rb != (base, limit):
            self._ctrl_missing(chk, f"range readback: {line}")
        self.logger.info("CTRL-%s PASS seed=%d %s", chk[len("CHK-") :], self.seed, line)
        return f"base_rb=0x{rb[0]:08x} limit_rb=0x{rb[1]:08x}"

    # ---- scenario ---------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.k = 0
        plan = Plan(self.seed)
        self.logger.info("PLAN %s seed=%d legZ_cells=%d", TEST, self.seed, len(plan.cells))
        for line in plan.lines:
            self.logger.info(line)

        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        dut = cocotb.top
        self.tap = SepDmaTap(dut).start()
        self.edges = _EdgeCount(dut.clk_i)
        self.busy = SepBitWatch(dut.dma_busy_probe_o, name="dma_busy_probe_o").start()
        self.irq = SepBitWatch(
            dut.sep_internal_interrupts_probe_o,
            {"done": PIC_DONE_BIT, "error": PIC_ERROR_BIT},
            name="pic_src9_11",
        ).start()
        self.trigger = SepBitWatch(dut.spi_lsio_trigger_probe_o, name="spi_lsio_trigger").start()
        self.ops = SepDmaOps(self)
        self.mem = SepMemWords(self)
        set_dma_zero_pass(False, self.logger)
        try:
            await self._setup()
            await self._leg_z(plan)
            await self._leg_w(plan)
            await self._leg_e(plan)
            await self._leg_a(plan)
            await self._leg_s(plan)
            await self._leg_x(plan)
            await self._leg_b(plan)
            await self._leg_l(plan)
        finally:
            close_graded_window(self.logger)
            set_dma_zero_pass(False)
            for watch in (self.tap, self.busy, self.irq, self.trigger, self.edges):
                await watch.stop()
        self.result_pass(TEST, self.seed, self.k)

    async def _setup(self) -> None:
        ops = self.ops
        await ops.program_range(SRAM_BASE, SRAM_LIMIT, valid=True)
        await ops.set_asid(ASID, ASID)
        await ops.wr(SRC_ADDR_HI, 0)
        await ops.wr(DST_ADDR_HI, 0)
        await ops.clean_state()
        await ops.wr(INTR_ENABLE, 0)
        self.logger.info(
            "SETUP range=0x%08x..0x%08x valid=1 addr_space_id=0x%02x intr_enable=0",
            SRAM_BASE,
            SRAM_LIMIT,
            asid_word(ASID, ASID),
        )

    # ---- graded window and pass label --------------------------------------
    async def _open(self) -> None:
        """Open the window one clk_i edge before the GO it counts."""
        await RisingEdge(cocotb.top.clk_i)
        open_graded_window(TEST, self.logger)
        await RisingEdge(cocotb.top.clk_i)

    async def _close(self) -> None:
        """Close the window when the graded fill has ended, before any clean-up."""
        await RisingEdge(cocotb.top.clk_i)
        close_graded_window(self.logger)

    async def _release(self) -> None:
        """Raise dma_zero_pass for LABEL_CLOCKS clocks; only after every check of one fill passed."""
        await RisingEdge(cocotb.top.clk_i)
        set_dma_zero_pass(True, self.logger)
        await ClockCycles(cocotb.top.clk_i, LABEL_CLOCKS)
        set_dma_zero_pass(False, self.logger)
        await RisingEdge(cocotb.top.clk_i)

    # ---- shared pieces ----------------------------------------------------
    async def _idle(self) -> None:
        """W1C ERROR, ABORTED, DONE and CHUNK_DONE, then wait for BUSY=0."""
        await self.ops.clean_state()
        await self.ops.poll_status(lambda s: not s.busy, ERR_POLL_BOUND, "BUSY=0")

    async def _run(
        self,
        *,
        opcode: int,
        dst: int,
        total: int,
        chunk: int,
        width_enc: int = 2,
        src: int = 0,
        dst_inc: bool = True,
        dst_wrap: bool = False,
        hs: int = 0,
        stop_on_error: bool = True,
        graded: bool = False,
        read_dst: bool = False,
        read_cfg: bool = False,
    ) -> FillRun:
        """Program one transfer, GO, and wait for DONE or ERROR (re-GO between chunks).

        The tap window runs from GO to BUSY=0, so it holds every beat the DMA
        issues. The DMA leaves its error state only after a W1C of
        STATUS.ERROR, so a stop on ERROR or ABORTED runs ``_idle`` (W1C, then
        a bounded wait for BUSY=0 that fails on expiry) before the window
        closes. ``status`` and ``error_code`` are read before that W1C.
        ``graded`` opens the graded window after the transfer registers are
        written and closes it after the ERROR_CODE read, before the W1C.
        ``read_dst`` reads DST_ADDR_LO back after programming and before GO,
        since a fixed-address fill moves it. ``read_cfg`` reads DST_CONFIG and
        TRANSFER_WIDTH back at the same point.
        """
        ops = self.ops
        await ops.program_transfer(
            src=src,
            dst=dst,
            total=total,
            chunk=chunk,
            width_enc=width_enc,
            dst_inc=dst_inc,
            dst_wrap=dst_wrap,
        )
        dst_rb = await ops.rd(DST_ADDR_LO) if read_dst else None
        cfg_rb = (await ops.rd(DST_CONFIG), await ops.rd(TRANSFER_WIDTH)) if read_cfg else None
        mark = self.tap.mark()
        e0 = self.edges.n
        if graded:
            await self._open()
        await ops.go(opcode=opcode, hs=hs)
        stop = (lambda s: bool(s.error or s.aborted)) if stop_on_error else (lambda s: False)
        res = await ops.run_to_done(2 * total, busy=self.busy, stop_on=stop)
        ec = await ops.rd(ERROR_CODE)
        if graded:
            await self._close()
        if res.status.error or res.status.aborted:
            await self._idle()
        elif res.status.busy:
            await ops.poll_status(lambda s: not s.busy, ERR_POLL_BOUND, "BUSY=0 after DONE")
        self._tap_window_sampled(mark.clk, e0)
        return FillRun(res.status, ec, self.tap.since(mark), res.go_writes, dst_rb, cfg_rb)

    def _tap_window_sampled(self, tap0: int, e0: int) -> None:
        """Fails unless the tap sampled every clock of the window.

        An empty AR or AW list is proof of no traffic only when the tap ran
        through the whole window; one clock of slack covers the edge on which
        the window opens or closes.
        """
        sampled = self.tap.clk - tap0
        edges = self.edges.n - e0
        if sampled == 0 or sampled + 1 < edges:
            line = f"DMA-TAP-WINDOW FAIL seed={self.seed} tap_samples={sampled} clocks={edges}"
            self.logger.error(line)
            raise AssertionError(line)

    def _irq_levels(self) -> tuple[int | None, int | None]:
        """PIC source 9 and 11 levels at the last sample."""
        return self.irq.level("done"), self.irq.level("error")

    async def _wait_status(self, mask: int, what: str) -> DmaStatus:
        return await self.ops.poll_status(lambda s: bool(s.raw & mask), ERR_POLL_BOUND, what)

    async def _read_region(self, region: Region) -> list[int]:
        return await self.mem.read(region.addr, len(region.words))

    def _expect_words(self, region: Region, fill: DmaZeroFill, beats: list[ZeroBeat]) -> list[int]:
        img = fill.dst_image(region.image(), beats)
        return bytes_to_words(img, region.addr, len(region.words))

    @staticmethod
    def _diff(got: list[int], exp: list[int], base: int) -> str:
        bad = [(i, g, e) for i, (g, e) in enumerate(zip(got, exp)) if g != e]
        if not bad:
            return "mismatches=0"
        i, g, e = bad[0]
        return f"mismatches={len(bad)} first=0x{base + 4 * i:08x} got=0x{g:08x} expect=0x{e:08x}"

    def _beat_problems(self, ev: DmaTapEvents, beats: list[ZeroBeat]) -> list[str]:
        """Differences between the tap window and the model beats of a fill."""
        out = []
        if ev.ar:
            out.append(f"ar={len(ev.ar)}")
        if len(ev.aw) != len(beats) or len(ev.w) != len(beats):
            out.append(f"aw={len(ev.aw)} w={len(ev.w)} expect={len(beats)}")
        for i, (aw, wb, beat) in enumerate(zip(ev.aw, ev.w, beats)):
            if aw.len != 0 or (aw.addr or 0) >> 2 != beat.addr >> 2 or wb.strb != beat.wstrb:
                out.append(
                    f"beat{i}: aw=0x{aw.addr or 0:08x} len={aw.len} strb=0x{wb.strb or 0:02x} "
                    f"expect aw=0x{beat.addr & ~3:08x} strb=0x{beat.wstrb:02x}"
                )
                break
        if len(ev.b) != len(ev.aw) or any(b.resp != 0 for b in ev.b):
            out.append(f"b={len(ev.b)} resp={[b.resp for b in ev.b]}")
        return out

    def _cfg_rb(self, tag: str, run: FillRun, inc: bool, wrap: bool, enc: int) -> None:
        """CTRL-MISSING unless DST_CONFIG and TRANSFER_WIDTH, read before GO, hold the values written."""
        wr = (addr_cfg(inc, wrap), transfer_width_word(enc))
        rb = run.cfg_rb or (-1, -1)
        rb = (rb[0] & _D.mask32("DST_CONFIG"), rb[1] & _D.mask32("TRANSFER_WIDTH"))
        line = (
            f"{tag} dst_config_wr=0x{wr[0]:x} dst_config_rb=0x{rb[0]:x} "
            f"transfer_width_wr=0x{wr[1]:x} transfer_width_rb=0x{rb[1]:x}"
        )
        if rb != wr:
            self._ctrl_missing("CHK-DMA-ZERO-BEAT", f"config readback: {line}")
        self.logger.info("CTRL-DMA-ZERO-BEAT PASS seed=%d %s", self.seed, line)

    def _mode_rule(
        self, tag: str, mode: str, f: DmaZeroFill, ev: DmaTapEvents, n_beats: int
    ) -> tuple[bool, str]:
        """Grade the observed beat start addresses against the rule of ``mode``.

        CTRL-MISSING when the drawn shape gives another mode the same address
        list, since the check could then not tell the modes apart.
        """
        exp = mode_addrs(mode, f.dst_base, f.w, f.chunk, n_beats)
        same = [
            m
            for m in MODES
            if m != mode and mode_addrs(m, f.dst_base, f.w, f.chunk, n_beats) == exp
        ]
        if same:
            self._ctrl_missing("CHK-DMA-ZERO-BEAT", f"{tag} mode rule equals {same} for this shape")
        obs = [beat_start(aw.addr, wb.strb) for aw, wb in zip(ev.aw, ev.w)]
        bad = next((k for k, (o, e) in enumerate(zip(obs, exp)) if o != e), None)
        if bad is None and len(obs) != len(exp):
            bad = min(len(obs), len(exp))

        def fmt(v: int | None) -> str:
            return "none" if v is None else f"0x{v:08x}"

        k = f.chunk // f.w
        line = (
            f"mode_rule={mode} distinct_addrs={len(set(obs))} addr0={fmt(obs[0] if obs else None)}"
        )
        if mode != "fixed" and len(exp) > k:
            line += f" beat{k}={fmt(obs[k] if len(obs) > k else None)} expect={fmt(exp[k])}"
        if bad is None:
            return True, f"{line} addrs=rule"
        got = obs[bad] if bad < len(obs) else None
        want = exp[bad] if bad < len(exp) else None
        return False, f"{line} first_bad=beat{bad} got={fmt(got)} expect={fmt(want)}"

    # ---- Leg Z: image and beats per mode and width -------------------------
    async def _leg_z(self, plan: Plan) -> None:
        for c in plan.cells:
            f = c.fill
            tag = (
                f"mode={c.mode} enc={c.enc} total={f.total} chunk={f.chunk} dst=0x{f.dst_base:08x}"
            )
            await self.mem.fill(c.region.addr, c.region.words)
            await self.mem.fill(c.copy_src.addr, c.copy_src.words)
            await self.mem.fill(c.copy_dst, [0] * (COPY_BYTES // 4))
            cp = await self._run(
                opcode=OP_COPY,
                src=c.copy_src.addr,
                dst=c.copy_dst,
                total=COPY_BYTES,
                chunk=COPY_BYTES,
            )
            if not cp.status.done or cp.status.error:
                self._ctrl_missing("CHK-DMA-ZERO-RESIDUE", f"{tag} copy {cp.status.fmt()}")
            cp_ar = [b.addr for b in cp.ev.ar]
            exp_ar = [c.copy_src.addr + 4 * i for i in range(COPY_BYTES // 4)]
            if cp_ar != exp_ar:
                self._ctrl_missing(
                    "CHK-DMA-ZERO-BEAT",
                    f"{tag} copy ar={len(cp_ar)} expect={len(exp_ar)} "
                    f"addrs={[f'0x{a or 0:08x}' for a in cp_ar[:4]]}",
                )
            cp_got = await self.mem.read(c.copy_dst, COPY_BYTES // 4)
            if cp_got != c.copy_src.words:
                self._ctrl_missing(
                    "CHK-DMA-ZERO-RESIDUE",
                    f"{tag} copy_dst {self._diff(cp_got, c.copy_src.words, c.copy_dst)}",
                )
            inc, wrap = MODES[c.mode]
            run = await self._run(
                opcode=OP_ZERO,
                dst=f.dst_base,
                total=f.total,
                chunk=f.chunk,
                width_enc=c.enc,
                dst_inc=inc,
                dst_wrap=wrap,
                graded=True,
                read_cfg=True,
            )
            self._cfg_rb(tag, run, inc, wrap, c.enc)
            beats = f.beats()
            got = await self._read_region(c.region)
            exp = self._expect_words(c.region, f, beats)
            st = run.status
            ok = got == exp and st.done and not st.error and run.error_code & ERROR_CODE_MASK == 0
            self._pass(
                "CHK-DMA-ZERO-IMAGE",
                ok,
                f"{tag} {st.fmt()} error_code=0x{run.error_code:x} go_writes={run.go_writes} "
                f"{self._diff(got, exp, c.region.addr)}",
            )
            probs = self._beat_problems(run.ev, beats)
            mode_ok, mode_line = self._mode_rule(tag, c.mode, f, run.ev, len(beats))
            self._pass(
                "CHK-DMA-ZERO-BEAT",
                not probs and mode_ok,
                f"{tag} ar={len(run.ev.ar)} copy_ar={len(cp_ar)} aw={len(run.ev.aw)} "
                f"beats={len(beats)} {mode_line} "
                f"{' '.join(probs) or 'shape=model'}",
            )
            cleared = sorted({beat.addr + b for beat in beats for b in range(beat.nbytes)})
            img = words_to_bytes(c.region.addr, got)
            self._pass(
                "CHK-DMA-ZERO-RESIDUE",
                all(img[a] == 0 for a in cleared),
                f"{tag} copy_last=0x{c.copy_src.words[-1]:08x} "
                f"copy_dst_last=0x{cp_got[-1]:08x} cleared_bytes={len(cleared)}",
            )
            await self._release()
            await self._idle()

    # ---- Leg W: the erase window ------------------------------------------
    async def _window_err(
        self, d: WDraw, case: str, fill: DmaZeroFill, base: int, limit: int, irq: bool = False
    ) -> None:
        await self.ops.program_range(base, limit, valid=True)
        await self.mem.fill(d.region.addr, d.region.words)
        m_irq = self.irq.mark()
        lvl0 = self._irq_levels()
        run = await self._run(
            opcode=OP_ZERO,
            dst=fill.dst_base,
            total=fill.total,
            chunk=fill.chunk,
            width_enc=fill.width_enc,
            graded=True,
        )
        await ClockCycles(cocotb.top.clk_i, IRQ_SETTLE)
        beats = fill.beats_in_range(base, limit)
        got = await self._read_region(d.region)
        exp = self._expect_words(d.region, fill, beats)
        st = run.status
        ec = run.error_code & ERROR_CODE_MASK
        probs = self._beat_problems(run.ev, beats)
        ok = st.error and not st.done and ec == DST_ERR and got == exp and not probs
        self._pass(
            "CHK-DMA-ZERO-WIN-ERR",
            ok,
            f"case={case} base=0x{base:08x} limit=0x{limit:08x} dst=0x{fill.dst_base:08x} "
            f"total={fill.total} chunk={fill.chunk} {st.fmt()} error_code=0x{ec:x} "
            f"aw={len(run.ev.aw)} in_range_beats={len(beats)} "
            f"{' '.join(probs) or 'shape=model'} {self._diff(got, exp, d.region.addr)}",
        )
        if irq:
            done_r = self.irq.rises_since(m_irq, "done")
            err_r = self.irq.rises_since(m_irq, "error")
            self._pass(
                "CHK-DMA-ZERO-IRQ",
                lvl0 == (0, 0) and err_r >= 1 and done_r == 0,
                f"case={case} pic_src9_at_mark={lvl0[0]} pic_src11_at_mark={lvl0[1]} "
                f"pic_src11_rises={err_r} pic_src9_rises={done_r}",
            )
        await self._release()
        await self._idle()

    async def _leg_w(self, plan: Plan) -> None:
        d = plan.w
        ops = self.ops
        await ops.wr(INTR_ENABLE, INTR_EN_DONE | INTR_EN_ERROR)
        size = d.limit - d.base + 1

        # The whole range.
        await ops.program_range(d.base, d.limit, valid=True)
        rb = await self._range_rb("CHK-DMA-ZERO-WIN-OK", d.base, d.limit)
        await self.mem.fill(d.region.addr, d.region.words)
        fill = DmaZeroFill(d.base, size, size)
        m_irq = self.irq.mark()
        lvl0 = self._irq_levels()
        run = await self._run(opcode=OP_ZERO, dst=d.base, total=size, chunk=size, graded=True)
        await ClockCycles(cocotb.top.clk_i, IRQ_SETTLE)
        got = await self._read_region(d.region)
        exp = self._expect_words(d.region, fill, fill.beats())
        st = run.status
        self._pass(
            "CHK-DMA-ZERO-WIN-OK",
            st.done and not st.error and got == exp,
            f"{rb} {st.fmt()} {self._diff(got, exp, d.region.addr)}",
        )
        done_r = self.irq.rises_since(m_irq, "done")
        err_r = self.irq.rises_since(m_irq, "error")
        self._pass(
            "CHK-DMA-ZERO-IRQ",
            lvl0 == (0, 0) and done_r >= 1 and err_r == 0,
            f"case=in_range pic_src9_at_mark={lvl0[0]} pic_src11_at_mark={lvl0[1]} "
            f"pic_src9_rises={done_r} pic_src11_rises={err_r}",
        )
        await self._release()
        await self._idle()

        # Starts below BASE.
        below = d.base - 4 * d.below_words
        await self._window_err(
            d, "below", DmaZeroFill(below, d.below_total, d.below_total), d.base, d.limit
        )
        # One byte below an unaligned BASE, at width 1.
        await self._window_err(d, "below_byte", DmaZeroFill(d.base, 4, 4, 0), d.base + 1, d.limit)
        # Runs past LIMIT in one chunk.
        start = d.limit + 1 - 4 * d.above_words
        total = 4 * d.above_words + d.above_extra
        await self._window_err(
            d, "above", DmaZeroFill(start, total, total), d.base, d.limit, irq=True
        )
        # Crosses LIMIT in a later chunk.
        total = size + d.cross_extra
        await self._window_err(
            d, "cross_chunk", DmaZeroFill(d.base, total, d.cross_chunk), d.base, d.limit
        )

        # A narrow last beat that ends on an unaligned LIMIT.
        limit = d.limit - d.exact_trim
        await ops.program_range(d.base, limit, valid=True)
        rb = await self._range_rb("CHK-DMA-ZERO-WIN-EXACT", d.base, limit)
        await self.mem.fill(d.region.addr, d.region.words)
        total = size - d.exact_trim
        fill = DmaZeroFill(d.base, total, total)
        run = await self._run(opcode=OP_ZERO, dst=d.base, total=total, chunk=total, graded=True)
        got = await self._read_region(d.region)
        exp = self._expect_words(d.region, fill, fill.beats())
        st = run.status
        self._pass(
            "CHK-DMA-ZERO-WIN-EXACT",
            st.done and not st.error and got == exp,
            f"{rb} total={total} last_beat={fill.beats()[-1].nbytes} {st.fmt()} "
            f"{self._diff(got, exp, d.region.addr)}",
        )
        await self._release()
        await self._idle()

        # Control: a copy whose destination is outside the range completes.
        await ops.program_range(d.base, d.limit, valid=True)
        await self.mem.fill(d.ctrl_src.addr, d.ctrl_src.words)
        await self.mem.fill(d.ctrl_dst.addr, [0] * len(d.ctrl_dst.words))
        run = await self._run(
            opcode=OP_COPY, src=d.ctrl_src.addr, dst=d.ctrl_dst.addr, total=16, chunk=16
        )
        got = await self._read_region(d.ctrl_dst)
        st = run.status
        self._pass(
            "CHK-DMA-ZERO-COPY-CTRL",
            st.done and not st.error and got == d.ctrl_src.words,
            f"dst=0x{d.ctrl_dst.addr:08x} base=0x{d.base:08x} limit=0x{d.limit:08x} {st.fmt()} "
            f"{self._diff(got, d.ctrl_src.words, d.ctrl_dst.addr)}",
        )
        await self._idle()
        await ops.wr(INTR_ENABLE, 0)
        await ops.program_range(SRAM_BASE, SRAM_LIMIT, valid=True)

    # ---- Leg E: invalid opcode and handshake mode --------------------------
    def _opcode_error(self, chk: str, run: FillRun, ok: bool, extra: str) -> None:
        """OPCODE_ERROR alone, no beat, and the caller's own condition ``ok``."""
        st = run.status
        ec = run.error_code & ERROR_CODE_MASK
        self._pass(
            chk,
            ok and st.error and ec == OPC_ERR and not run.ev.ar and not run.ev.aw,
            f"{extra} {st.fmt()} error_code=0x{ec:x} ar={len(run.ev.ar)} aw={len(run.ev.aw)}",
        )

    async def _leg_e(self, plan: Plan) -> None:
        ops = self.ops
        r = plan.e_region
        total = plan.e_total
        fill = DmaZeroFill(r.addr, total, total)

        # OPCODE 5, then a fill after the W1C of ERROR.
        await self.mem.fill(r.addr, r.words)
        run = await self._run(opcode=OP_INVALID, dst=r.addr, total=total, chunk=total)
        got = await self._read_region(r)
        self._opcode_error(
            "CHK-DMA-ZERO-OPC",
            run,
            got == r.words,
            f"opcode=0x{OP_INVALID:x} {self._diff(got, r.words, r.addr)}",
        )
        await self._idle()
        run = await self._run(opcode=OP_ZERO, dst=r.addr, total=total, chunk=total, graded=True)
        got = await self._read_region(r)
        exp = self._expect_words(r, fill, fill.beats())
        self._pass(
            "CHK-DMA-ZERO-OPC",
            run.status.done and not run.status.error and got == exp,
            f"recovery {run.status.fmt()} {self._diff(got, exp, r.addr)}",
        )
        await self._release()
        await self._idle()

        # Handshake mode with the SPI trigger held high.
        await self.mem.fill(r.addr, r.words)
        spi_ctrl = await ops.rd(SPI_CONTROL)
        await ops.wr(SPI_CONTROL, (spi_ctrl & ~SPI_TX_WM) | (1 << SPI_TX_WM_LSB))
        await ops.wr(HANDSHAKE_INTR_ENABLE, HS_TRIGGER0)
        try:
            await self.trigger.wait_level(1, TRIGGER_BOUND)
        except AssertionError:
            self._ctrl_missing("CHK-DMA-ZERO-HS", "the SPI trigger did not rise")
        trig_at_go = self.trigger.level()
        run = await self._run(
            opcode=OP_ZERO, dst=r.addr, total=total, chunk=total, hs=1, graded=True
        )
        got = await self._read_region(r)
        if trig_at_go != 1:
            self._ctrl_missing("CHK-DMA-ZERO-HS", f"trigger_at_go={trig_at_go}")
        self._opcode_error(
            "CHK-DMA-ZERO-HS",
            run,
            got == r.words,
            f"trigger_at_go={trig_at_go} {self._diff(got, r.words, r.addr)}",
        )
        await self._release()
        await self._idle()
        await ops.wr(HANDSHAKE_INTR_ENABLE, HS_RESET)
        await ops.wr(SPI_CONTROL, spi_ctrl)

    # ---- Leg A: abort --------------------------------------------------------
    async def _leg_a(self, plan: Plan) -> None:
        ops = self.ops
        r = plan.a_region
        total = r.nbytes
        sentinel = r.words

        # Reference fill: its clean time sets the abort delay only.
        await self.mem.fill(r.addr, sentinel)
        mark = self.tap.mark()
        run = await self._run(opcode=OP_ZERO, dst=r.addr, total=total, chunk=total)
        t_clean = self.tap.clk - mark.clk
        if not run.status.done:
            self._ctrl_missing("CHK-DMA-ZERO-ABORT", f"reference fill {run.status.fmt()}")
        await self._idle()

        for attempt, frac in enumerate(plan.a_fracs):
            await self.mem.fill(r.addr, sentinel)
            await ops.program_transfer(src=0, dst=r.addr, total=total, chunk=total)
            m_busy = self.busy.mark()
            await self._open()
            await ops.go(opcode=OP_ZERO)
            await self.busy.wait_rise(m_busy, BUSY_RISE_BOUND)
            await ClockCycles(cocotb.top.clk_i, t_clean * frac // 100)
            busy_at_abort = self.busy.level()
            await ops.abort()
            st = await self._wait_status(ST_ABORTED | ST_DONE, "ABORTED or DONE")
            await self._close()
            if busy_at_abort and st.aborted:
                break
            self.logger.info(
                "INFO-DMA-ZERO-ABORT-REDRAW attempt=%d frac=%d busy_at_abort=%s %s",
                attempt,
                frac,
                busy_at_abort,
                st.fmt(),
            )
            await self._idle()
        else:
            self._ctrl_missing("CHK-DMA-ZERO-ABORT", "no abort landed while the fill was busy")

        m_after = self.tap.mark()
        img1 = await self._read_region(r)
        await ClockCycles(cocotb.top.clk_i, max(1, t_clean // 4))
        img2 = await self._read_region(r)
        after = self.tap.since(m_after)
        z = next((i for i, w in enumerate(img1) if w != 0), len(img1))
        prefix_ok = all(w == 0 for w in img1[:z]) and img1[z:] == sentinel[z:]
        self.logger.info(
            "OBS-DMA-ZERO-ABORT ar_after=%d aw_after=%d zero_words=%d",
            len(after.ar),
            len(after.aw),
            z,
        )
        await ops.wr(STATUS, ST_ABORTED)
        st_clr = await ops.read_status()
        await self._idle()
        rec = await self._run(opcode=OP_ZERO, dst=r.addr, total=total, chunk=total)
        img3 = await self._read_region(r)
        ok = (
            st.aborted
            and prefix_ok
            and 0 < z < len(img1)
            and img1 == img2
            and not st_clr.aborted
            and rec.status.done
            and not rec.status.error
            and all(w == 0 for w in img3)
        )
        self._pass(
            "CHK-DMA-ZERO-ABORT",
            ok,
            f"frac={frac} t_clean={t_clean} {st.fmt()} zero_words={z}/{len(img1)} "
            f"prefix_ok={int(prefix_ok)} quiet={int(img1 == img2)} "
            f"aborted_after_w1c={st_clr.aborted} recovery={rec.status.fmt()} "
            f"recovery_zero={int(all(w == 0 for w in img3))}",
        )
        await self._release()
        await self._idle()

    # ---- Leg S: the source address space of a fill is validated ------------
    async def _leg_s(self, plan: Plan) -> None:
        """A fill with an invalid SRC_ADDR_SPACE_ID ends in ASID_ERROR alone and writes nothing.

        Goldens: ``hw/sys/sep/doc/dma.adoc:107-109`` (a fill validates the
        source registers as for a copy);
        ``vendor/lowRISC/opentitan/upstream/hw/ip/dma/data/dma.hjson:711-713``
        (ERROR_CODE.ASID_ERROR: a source or destination ASID with an invalid
        value); ``vendor/lowRISC/opentitan/upstream/hw/ip/dma/doc/
        programmers_guide.md:102-103`` (the configuration is checked before a
        transfer starts, and ERROR_CODE holds every detected error). The
        control fill differs only in SRC_ADDR_SPACE_ID 0x7: it completes with
        ERROR_CODE 0, so no other part of the configuration is invalid.
        """
        ops = self.ops
        r = plan.s_region
        total = plan.s_total
        fill = DmaZeroFill(plan.s_dst, total, total)
        beats = fill.beats()
        src_asid = plan.s_asid
        await self.mem.fill(r.addr, r.words)
        await ops.set_asid(src_asid, ASID)
        asid_rb = await ops.rd(ADDR_SPACE_ID) & ASID_FIELDS
        if asid_rb != asid_word(src_asid, ASID):
            self._ctrl_missing(
                "CHK-DMA-ZERO-SRC-ASID",
                f"addr_space_id=0x{asid_rb:02x} expect=0x{asid_word(src_asid, ASID):02x}",
            )
        run = await self._run(opcode=OP_ZERO, dst=plan.s_dst, total=total, chunk=total, graded=True)
        got = await self._read_region(r)

        # Control: the same fill with SRC_ADDR_SPACE_ID 0x7 writes the model beats.
        await ops.set_asid(ASID, ASID)
        twin = await self._run(opcode=OP_ZERO, dst=plan.s_dst, total=total, chunk=total)
        twin_got = await self._read_region(r)
        twin_exp = self._expect_words(r, fill, beats)
        twin_ec = twin.error_code & ERROR_CODE_MASK
        twin_probs = self._beat_problems(twin.ev, beats)
        if not (
            twin.status.done
            and not twin.status.error
            and twin_ec == 0
            and not twin_probs
            and twin_got == twin_exp
        ):
            self._ctrl_missing(
                "CHK-DMA-ZERO-SRC-ASID",
                f"twin src_asid=0x{ASID:x} {twin.status.fmt()} error_code=0x{twin_ec:x} "
                f"{' '.join(twin_probs) or 'shape=model'} "
                f"{self._diff(twin_got, twin_exp, r.addr)}",
            )

        st = run.status
        ec = run.error_code & ERROR_CODE_MASK
        ok = (
            st.error
            and not st.done
            and ec == ASID_ERR
            and not run.ev.ar
            and not run.ev.aw
            and not run.ev.w
            and got == r.words
            and len(twin.ev.aw) == len(beats) > 0
        )
        self._pass(
            "CHK-DMA-ZERO-SRC-ASID",
            ok,
            f"src_asid=0x{src_asid:x} dst_asid=0x{ASID:x} dst=0x{plan.s_dst:08x} total={total} "
            f"{st.fmt()} error_code=0x{ec:x} expect=0x{ASID_ERR:x} ar={len(run.ev.ar)} "
            f"aw={len(run.ev.aw)} w={len(run.ev.w)} {self._diff(got, r.words, r.addr)} "
            f"twin_src_asid=0x{ASID:x} twin_aw={len(twin.ev.aw)} twin_beats={len(beats)} "
            f"twin_done={twin.status.done} twin_error_code=0x{twin_ec:x}",
        )
        await self._release()
        await self._idle()

    # ---- Leg X: a fill through the local alias window -----------------------
    async def _leg_x(self, plan: Plan) -> None:
        ops = self.ops
        f = plan.x_fill
        r = plan.x_region
        inc, wrap = MODES[plan.x_mode]
        a_base, a_limit, a_dst = alias(SRAM_BASE), alias(SRAM_LIMIT), alias(f.dst_base)
        tag = (
            f"mode={plan.x_mode} enc={plan.x_enc} total={f.total} chunk={f.chunk} "
            f"direct=0x{f.dst_base:08x}"
        )
        local_rb = await ops.rd(LOCAL_BASE_REG) & LOCAL_BASE_MASK
        await ops.program_range(a_base, a_limit, valid=True)
        range_rb = (await ops.rd(RANGE_BASE), await ops.rd(RANGE_LIMIT))
        await self.mem.fill(r.addr, r.words)
        run = await self._run(
            opcode=OP_ZERO,
            dst=a_dst,
            total=f.total,
            chunk=f.chunk,
            width_enc=plan.x_enc,
            dst_inc=inc,
            dst_wrap=wrap,
            graded=True,
            read_dst=True,
        )
        dst_rb = run.dst_rb
        if (
            local_rb != LOCAL_ALIAS & LOCAL_BASE_MASK
            or range_rb != (a_base, a_limit)
            or dst_rb != a_dst
        ):
            self._ctrl_missing(
                "CHK-DMA-ALIAS-FORM",
                f"{tag} sep_local_base=0x{local_rb:08x} range=0x{range_rb[0]:08x}..0x"
                f"{range_rb[1]:08x} expect=0x{a_base:08x}..0x{a_limit:08x} "
                f"dst_addr_lo=0x{dst_rb:08x} expect=0x{a_dst:08x}",
            )
        beats = f.beats()
        got = await self._read_region(r)
        exp = self._expect_words(r, f, beats)
        st = run.status
        ec = run.error_code & ERROR_CODE_MASK
        probs = self._beat_problems(run.ev, beats)
        self._pass(
            "CHK-DMA-ALIAS-FORM",
            st.done and not st.error and ec == 0 and got == exp and not probs,
            f"{tag} sep_local_base=0x{local_rb:08x} dst_addr_lo_rb=0x{dst_rb:08x} "
            f"range_rb=0x{range_rb[0]:08x}..0x{range_rb[1]:08x} {st.fmt()} error_code=0x{ec:x} "
            f"aw={len(run.ev.aw)} beats={len(beats)} "
            f"aw0=0x{(run.ev.aw[0].addr or 0) if run.ev.aw else 0:08x} "
            f"{' '.join(probs) or 'shape=model'} {self._diff(got, exp, r.addr)}",
        )
        await self._release()
        await self._idle()
        await ops.program_range(SRAM_BASE, SRAM_LIMIT, valid=True)

    # ---- Leg B: a fill at BASE = LIMIT, logged only ------------------------
    async def _leg_b(self, plan: Plan) -> None:
        ops = self.ops
        r = plan.b_region
        dst = plan.b_dst
        await ops.program_range(dst, dst, valid=True)
        range_rb = (await ops.rd(RANGE_BASE), await ops.rd(RANGE_LIMIT))
        await self.mem.fill(r.addr, r.words)
        run = await self._run(
            opcode=OP_ZERO, dst=dst, total=plan.b_total, chunk=plan.b_total, width_enc=0
        )
        got = await self._read_region(r)
        self.logger.info(
            "OBS-DMA-ZF-BASELIM seed=%d base=limit=dst=0x%08x total=%d enc=0 range_readback="
            "0x%08x..0x%08x %s error_code=0x%x ar=%d aw=[%s] b=[%s] region=0x%08x before=[%s] "
            "after=[%s]",
            self.seed,
            dst,
            plan.b_total,
            range_rb[0],
            range_rb[1],
            run.status.fmt(),
            run.error_code & ERROR_CODE_MASK,
            len(run.ev.ar),
            ",".join(
                f"0x{aw.addr or 0:08x}/0x{wb.strb or 0:02x}" for aw, wb in zip(run.ev.aw, run.ev.w)
            ),
            ",".join(str(b.resp) for b in run.ev.b),
            r.addr,
            ",".join(f"0x{w:08x}" for w in r.words),
            ",".join(f"0x{w:08x}" for w in got),
        )
        await self._idle()
        await ops.program_range(SRAM_BASE, SRAM_LIMIT, valid=True)

    # ---- Leg L: the locked range -------------------------------------------
    async def _leg_l(self, plan: Plan) -> None:
        ops = self.ops
        r = plan.l_region
        await ops.program_range(plan.l_base, plan.l_limit, valid=True)
        await ops.wr(RANGE_REGWEN, REGWEN_FALSE << REGWEN_LSB)
        regwen = (await ops.rd(RANGE_REGWEN) & REGWEN_MASK) >> REGWEN_LSB
        limit_wr = plan.l_limit + 64
        seq = await ops.access(SepAxiOp.WRITE, RANGE_LIMIT, limit_wr, ungraded=True)
        limit_resp = int(seq.resp_code)
        limit_rb = await ops.rd(RANGE_LIMIT)
        self.logger.info(
            "OBS-DMA-ZERO-LOCK-RESP seed=%d limit_wr=0x%08x limit_wr_resp=%d",
            self.seed,
            limit_wr,
            limit_resp,
        )
        lock_line = (
            f"regwen=0x{regwen:x} limit_wr=0x{limit_wr:08x} limit_wr_resp={limit_resp} "
            f"limit_readback=0x{limit_rb:08x}"
        )
        if regwen == REGWEN_TRUE or limit_rb != plan.l_limit:
            self._pass(
                "CHK-DMA-ZERO-WIN-LOCK",
                False,
                f"{lock_line} expect_limit=0x{plan.l_limit:08x}",
            )
        start = plan.l_limit + 1 - 4 * plan.l_words
        total = 4 * plan.l_words + plan.l_extra
        fill = DmaZeroFill(start, total, total)
        await self.mem.fill(r.addr, r.words)
        run = await self._run(opcode=OP_ZERO, dst=start, total=total, chunk=total, graded=True)
        beats = fill.beats_in_range(plan.l_base, plan.l_limit)
        got = await self._read_region(r)
        exp = self._expect_words(r, fill, beats)
        st = run.status
        ec = run.error_code & ERROR_CODE_MASK
        cmp = field_compare(limit_rb, plan.l_limit, _D.mask32("ENABLED_MEMORY_RANGE_LIMIT"))
        probs = self._beat_problems(run.ev, beats)
        self._pass(
            "CHK-DMA-ZERO-WIN-LOCK",
            cmp.ok
            and st.error
            and ec == DST_ERR
            and got == exp
            and not probs
            and len(beats) == plan.l_words,
            f"{lock_line} {st.fmt()} "
            f"error_code=0x{ec:x} aw={len(run.ev.aw)} in_range_beats={len(beats)} "
            f"{' '.join(probs) or 'shape=model'} {self._diff(got, exp, r.addr)}",
        )
        await self._release()
        await self._idle()
