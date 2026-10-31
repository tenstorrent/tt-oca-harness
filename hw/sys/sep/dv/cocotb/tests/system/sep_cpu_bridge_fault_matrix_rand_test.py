# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Peripheral bridge and DMA fault latches: set, clear matrix, masks, re-trigger and races.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``, Verilator and
VCS. The X-free part of CHK-CTRL is graded on VCS, where a read that returns
an X bit fails at the AXI master; Verilator logs ``x_free=na``.

Contract (``hw/sys/sep/doc/interrupts.adoc``, sources 41 to 43;
``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc``,
``PERIPH_BUS_ERR_STATUS``, ``PERIPH_BUS_ERR_CLEAR``, ``DMA_BUS_ERR_STATUS``,
``DMA_BUS_ERR_CLEAR``; ``hw/sys/sep/doc/crypto.adoc``, "Single-Beat Access
Only"; ``vendor/lowRISC/opentitan/overlay/regs/secure_dma/regs/gen/adoc/secure_dma.adoc``,
``ERROR_CODE``, ``STATUS``):

* a CPU access to an in-extent hole of a register bridge answers SLVERR and
  latches the block bit of ``PERIPH_BUS_ERR_STATUS`` (aes 0, hmac 1, kmac 2,
  otbn 3, csrng 4, edn 5, wdt 6); source 43 (vector bit 42) is the OR of the
  seven bits;
* a partial write (a byte strobe that misses a byte the register owns) to an
  AES or watchdog register answers SLVERR and latches that block's bit alone
  (``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc:63-68``); the register
  value after it is logged as ``OBS-PARTIAL-KEPT`` and not graded;
* each of sources 41, 42 and 43 rises with no other vector bit changing in
  that clock, except the other two of the three
  (``hw/sys/sep/doc/interrupts.adoc:22-23`` "Bit ``i`` of that vector is PIC
  source ``i + 1``"; ``:33-34`` "Slots 1–43 are individually assigned");
* each ``PERIPH_BUS_ERR_CLEAR`` bit clears only its own block; both clear
  registers read 0;
* ``DMA_BUS_ERR_CLEAR.clr`` clears both DMA latches for a written 1 only;
* a non-OKAY response to a DMA source read sets ``ERROR_CODE.BUS_ERROR`` and
  ``STATUS.ERROR``, latches ``host_path_err`` alone and raises source 42
  (vector bit 41);
* a fault in the same cycle as the clear of its own latch still latches.

Hooks: the error inject ``smn_outbound_rd_slverr_i`` of the outbound responder
(``tb/sep_outbound_mbx.sv``) answers every source read of a DMA copy with
SLVERR; the outbound port taps ``PR-OUT`` and ``PR-OUT-RSP`` count the source
reads and their SLVERR responses; the read-only tap
``sep_cpu_ctrl_err_pulse_probe_o`` ([8:0] fault pulses, [17:9] clear pulses,
order aes, hmac, kmac, otbn, csrng, edn, wdt, dma reg_path, dma host_path) is
the anchor of the same-cycle coincidence. The races drive the clear write and
the faulting access concurrently on the CPU-LSU master and sweep the offset
between them: each trial measures the clock of both pulses and moves the
offset by their distance, inside a bounded range and number of trials.

The read-only tap ``sep_internal_interrupts_probe_o`` is watched on every
clock (``env/sep_bit_watch.pic_vector_watch``) for the exclusivity of each rise
of vector bits 40, 41 and 42.

Randomization (``SepSeededRng`` from the run seed): the block order of hmac,
kmac and otbn, the sweep order, the hole offset of each block, the
read-or-write choice of each re-fault, the clear order of bits 0 to 6, the 1
to 3 clear masks (each with at least two set bits, one of them the bit of an
unlatched block), the re-trigger blocks, the DMA source address inside the
fixed outbound window and the copy size; then the order of the AES and
watchdog partial writes and, for each, the byte range of the strobe (1 to 3
contiguous lanes of the register word that miss a byte the register owns) and
the non-zero data of each strobed byte. Both partial-write legs run in every
seed.

The watchdog clock runs at ``WDT_CLK_RATIO`` core periods so that the
full-strobe write of the watchdog register, which crosses the register clock
domain crossing, completes well inside the AXI timeout. The watchdog stays
disabled (``WDOG_CTRL.enable`` reset 0).

Checkers:
  CHK-CTRL        status 0 after reset and after legal reads; vector 40..42 0.
  CHK-PARTIAL-WR  a partial write to ``AES.CTRL_AUX_REGWEN`` and to
                  ``WDT_TIMER.WDOG_BARK_THOLD`` answers SLVERR, raises the
                  fault pulse of that block, gives PERIPH_BUS_ERR_STATUS = that
                  block's bit alone and vector bit 42 = 1. The register reads
                  its RDL reset value before the write
                  (``integration/rdl/sep/aes.rdl:135`` ``CTRL_AUX_REGWEN[0:0] =
                  0x1``; ``integration/rdl/sep/aon_timer.rdl:86``
                  ``threshold[31:0] = 0x0``). No specification sentence states
                  the register value after the refused write, so the read after
                  it is logged as ``OBS-PARTIAL-KEPT`` and not graded. Sources:
                  ``sep_cpu_ctrl.adoc:63-68`` "a partial write: a byte strobe
                  that misses a byte the register owns ... also received
                  SLVERR"; ``hw/sys/sep/doc/crypto.adoc:155-161`` (AES bridge
                  bit); ``hw/sys/sep/doc/watchdog.adoc:19`` (watchdog bridge);
                  ``hw/sys/sep/doc/interrupts.adoc:242-245`` (source 43 is the
                  OR of the AES and watchdog bits). Control: a full-strobe
                  write of the RDL reset value to the same register before the
                  leg answers OKAY and latches nothing (``CTRL-FULL-STROBE``).
  CHK-PARTIAL-CLR a write of that block's PERIPH_BUS_ERR_CLEAR bit returns the
                  status to 0 and vector bit 42 to 0.
  CHK-SRC41-EXCL, CHK-SRC42-EXCL, CHK-SRC43-EXCL
                  at every rise of vector bit 40, 41 or 42 in the run, every
                  other vector bit keeps its value of the clock before; the
                  six bits with an unstated idle level and the other two of
                  the three bridge-fault bits are not compared; each bit rises
                  at least once.
  CHK-RESP        a hole write answers SLVERR.
  CHK-LATCH       PERIPH_BUS_ERR_STATUS equals the faulted set.
  CHK-OR          vector bit 42 equals (status != 0).
  CHK-CLR-MATRIX  a clear bit clears only its own block (seven bits + drain).
  CTRL-NONVAC     each matrix and mask step starts with at least two bits.
  CHK-MASK        a mask clear gives the faulted set AND NOT mask.
  CHK-AGAIN       a cleared block re-latches; a re-fault keeps the other bits.
                  The status after the clear and after each re-fault equals
                  the stimulus model, and vector bit 42 is 1 after the
                  re-latch.
  CHK-CLR-READ0   both clear registers read 0 with both status registers set.
  CHK-DMA-CLR     write 0 keeps, write 1 clears both, no cross-set. In
                  ``cell=both`` the DMA register-path fault answers SLVERR and,
                  before the clear, vector bits 40 and 41 are both 1.
  CHK-HOST        a SLVERR DMA source read latches host_path_err alone.
  CHK-DMA-HOST-HOLD
                  after the host-path fault, a write of 1 to DMA STATUS.ERROR
                  reads ERROR = 0 and leaves host_path_err = 1 and source 42
                  (vector bit 41) high. Sources:
                  ``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc:53-55``
                  "Secure DMA bridge fault status. Each bit is latched in
                  hardware and held until the corresponding DMA_BUS_ERR_CLEAR
                  write. These bits also drive dedicated PIC sources.";
                  ``hw/sys/sep/doc/interrupts.adoc:233-234`` source 42 "DMA
                  host-path integrity/bus fault";
                  ``hw/sys/sep/doc/dma.adoc:131-132`` "Status completion and
                  error bits are write-one-to-clear". Control: the next cell
                  (``cell=host_only`` of CHK-DMA-CLR) writes 1 to
                  DMA_BUS_ERR_CLEAR and needs host_path_err = 0 and source 42
                  low (``sep_cpu_ctrl.adoc:60`` "Writing 1 emits a single-cycle
                  clear pulse to both latches").
  CHK-RACE        a same-cycle fault and clear leaves the latch set. The
                  whole status register is graded: for a peripheral latch,
                  PERIPH_BUS_ERR_STATUS equals the other latched bits of the
                  stimulus model plus the raced bit; for the DMA host path,
                  DMA_BUS_ERR_STATUS equals host_path_err alone and vector bit
                  40 is 0.
  CHK-BRIDGE-HOLE-SI
                  an SI 32-bit read of a drawn unbacked HMAC word, through an
                  inbound entry that allows it, answers SLVERR with 0xFFFFFFFF
                  (``hw/sys/sep/regs/gen/adoc/memory_map.adoc:52``, HMAC row,
                  Hole in Extent "SLVERR, 0xFFFFFFFF / SLVERR"; the column is
                  the answer at the inbound AXI port,
                  ``hw/sys/sep/doc/memory_map.adoc:66-69``). The read runs with
                  the owner window closed.

FCOV: the owner window is open over each graded instance. The pass label
``bfault_pass`` (``env/sep_fcov_gate.set_bfault_pass``) is written 0 at the
start of each graded instance and 1 after its checks pass; the sampler holds
every legal outcome of this leaf's points until that rise. The race trials run
with the window closed; only the graded read after a same-cycle coincidence
opens it. The exclusive rises of sources 41 to 43 in the window
(``cp_src_exclusive_other`` bins s41 to s43) are held until the end of the
run: CHK-SRC41/42/43-EXCL grade every rise of the run there, and after each
check passes the leaf sets the bit of its source in ``exo_pass``
(``env/sep_fcov_gate.set_exo_pass``), which samples the held rises of that
source.

Observed only (``OBS-DMA-HOST-CLR``): STATUS.ERROR and ERROR_CODE.BUS_ERROR
after a write of 1 to DMA_BUS_ERR_CLEAR while both are set. No sentence states
whether DMA_BUS_ERR_CLEAR changes the DMA report, so the leaf logs the values
and grades nothing.

The expected latch set of CHK-CLR-MATRIX and CHK-MASK, before and after each
clear, is the set of faults the leaf drove minus the bits it cleared, never a
status read.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import pic_vector_watch
from env.sep_decode_resp import sep_map_row
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import (
    close_graded_window,
    exo_pass_bit,
    open_graded_window,
    set_bfault_pass,
    set_exo_pass,
)
from env.sep_field_compare import field_compare
from env.sep_filter_model import FilterEntry
from env.sep_pic_map import vec_bit, vec_mask
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AES, HMAC, KMAC, OTBN, SEP_CPU_CTRL, WDT_TIMER, register_fields, sym
from sep_reg_meta import sep_reg as _sep_reg
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_dma_ops import (
    _D,
    ST_BUSY,
    ST_ERROR,
    SepDmaOps,
    control_word,
)
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_irq_aggregator_seq import (
    DMA_CLEAR_ADDR,
    DMA_HOST_PATH_BIT,
    DMA_REG_PATH_BIT,
    DMA_STATUS_ADDR,
    IRQ_DMA_HOST_PATH,
    IRQ_DMA_REG_PATH,
    IRQ_PERIPH_OR,
    PERIPH_CLEAR_ADDR,
    PERIPH_STATUS_ADDR,
    dma_reg_unmapped_addr,
    hmac_reg_unmapped_addr,
    kmac_reg_unmapped_addr,
    otbn_reg_unmapped_addr,
)

TEST = "sep_cpu_bridge_fault_matrix_rand_test"
RESP_OKAY, RESP_SLVERR, RESP_DECERR = 0, 2, 3
# Hole in Extent cell of the HMAC row: "SLVERR, 0xFFFFFFFF / SLVERR"
# (hw/sys/sep/regs/gen/adoc/memory_map.adoc:52).
SI_HOLE_RDATA = 0xFFFF_FFFF
RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

BLOCKS = ("hmac", "kmac", "otbn")
PERIPH_BITS = ("aes", "hmac", "kmac", "otbn", "csrng", "edn", "wdt")
BIT = {n: SEP_CPU_CTRL.field_mask("PERIPH_BUS_ERR_STATUS", n) for n in PERIPH_BITS}
PERIPH_MASK = SEP_CPU_CTRL.mask32("PERIPH_BUS_ERR_STATUS")
DMA_MASK = SEP_CPU_CTRL.mask32("DMA_BUS_ERR_STATUS")
PERIPH_CLR_MASK = SEP_CPU_CTRL.mask32("PERIPH_BUS_ERR_CLEAR")
DMA_CLR_MASK = SEP_CPU_CTRL.mask32("DMA_BUS_ERR_CLEAR")
UNLATCHABLE = [i for i, n in enumerate(PERIPH_BITS) if n not in BLOCKS]
# In-extent hole range of each block: from the first word after its CSR block to
# the start of its next region (seq_lib/sep_irq_aggregator_seq.py).
HOLE_RANGE = {
    "hmac": (hmac_reg_unmapped_addr(), sym("HMAC_MSG_FIFO_MEM_BASE_ADDR")),
    "kmac": (kmac_reg_unmapped_addr(), sym("KMAC_STATE_MEM_BASE_ADDR")),
    "otbn": (otbn_reg_unmapped_addr(), sym("OTBN_IMEM_MEM_BASE_ADDR")),
}
LEGAL = {"hmac": HMAC.addr("CFG"), "kmac": KMAC.addr("STATUS"), "otbn": OTBN.addr("STATUS")}
# sep_cpu_ctrl_err_pulse_probe_o bit of each latch: fault pulse, clear pulse.
PROBE_ORDER = PERIPH_BITS + ("dma_reg", "dma_host")
PROBE_SET = {n: i for i, n in enumerate(PROBE_ORDER)}
PROBE_CLR = {n: i + len(PROBE_ORDER) for i, n in enumerate(PROBE_ORDER)}
VEC_MASK = (1 << IRQ_DMA_REG_PATH) | (1 << IRQ_DMA_HOST_PATH) | (1 << IRQ_PERIPH_OR)

BUS_ERROR = _D.field_mask("ERROR_CODE", "bus_error")
ASID_RESET = _D.reset32("ADDR_SPACE_ID")
SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
# Fixed outbound source window inside the SMU aperture at its reset values,
# above 0x8000_1000 and away from the responder console and verdict words.
SMU_BASE = SEP_CPU_CTRL.reset("SMU_GLOBAL_BASE_ADDR")
WIN_LO = SMU_BASE + 0x0001_0000
WIN_HI = WIN_LO + 0xFFFF
OUT_PAIR = (2, 3)
DST = SRAM_BASE + 0x0002_0000
MAX_COPY = 256

ERR_POLL_BOUND = 400  # STATUS reads in a wait for ERROR
RACE_TRIALS = 16  # trials of one same-cycle sweep
RACE_RANGE = 64  # largest offset magnitude, clocks
VEC_SETTLE = 4  # clocks before a vector sample
VIP_NS = 20_000
LABEL_CLK = 2  # clocks after a pass-label write before the next bus access

# Partial-write legs: one register in each of the two bridge blocks that no
# hole leg reaches. The owned bytes come from the generated field masks; the
# golden of the register value is its RDL reset.
PARTIAL_REG = {"aes": (AES, "CTRL_AUX_REGWEN"), "wdt": (WDT_TIMER, "WDOG_BARK_THOLD")}
PARTIAL_BLOCKS = tuple(PARTIAL_REG)
# Watchdog clock in core periods for this leaf (sim-timing knob, as in the
# watchdog register leaves): the full-strobe write of WDOG_BARK_THOLD crosses
# the register clock domain crossing and completes in a few watchdog clocks.
WDT_CLK_RATIO = 8

# Register blocks outside the seven PERIPH_BUS_ERR_STATUS bits, by generated
# block name. Their unbacked word is a drawn in-extent hole where the generated
# memory map gives the window one, else the first word past the extent.
OTHER_BLOCKS = (
    ("esrc", "ENTROPY_SOURCE"),
    ("spi", "SPI_CONTROLLER"),
    ("km", "KM_MAILBOX_SEP"),
    ("otp", "EFUSE_INTERFACE_CTRL"),
    ("lc", "SEP_LIFECYCLE_CTRL"),
    ("abr", "ABR"),
)


def _unbacked_words(block: str) -> tuple[str, list[int]]:
    """("hole", in-extent words no register or memory backs) or ("past", [first past word])."""
    row = sep_map_row(sym(f"{block}_REG_MAP_BASE_ADDR"))
    top = row.base + row.extent
    if row.hole is None:
        return "past", [top]
    mems = [
        int(v)
        for k, v in vars(_sep_reg).items()
        if k.endswith("_MEM_BASE_ADDR") and row.base <= int(v) < top
    ]
    top = min([top, *mems])
    backed: set[int] = set()
    for a in range(row.base, top, 4):
        try:
            width, _ = register_fields(a)
        except KeyError:
            continue
        backed.update(a + 4 * k for k in range(max(1, width // 32)))
    return "hole", [a for a in range(row.base, top, 4) if a not in backed]


# Exclusivity of the three bridge-fault sources: own vector bit and the bits
# that may move in the same clock (the other two of the three).
EXCL_SRC = (41, 42, 43)
EXCL_SAME = {s: vec_mask([o for o in EXCL_SRC if o != s]) for s in EXCL_SRC}


def _owned_bytes(mask: int) -> int:
    """Lane mask (bit k = byte k of the word) of the bytes holding a field bit."""
    return sum(1 << k for k in range(4) if (mask >> (8 * k)) & 0xFF)


def _partial_ranges(mask: int) -> list[tuple[int, int]]:
    """(offset, bytes) of every 1-3 lane contiguous strobe that misses an owned byte."""
    owned = _owned_bytes(mask)
    out = []
    for off in range(4):
        for n in range(1, 4):
            lanes = ((1 << n) - 1) << off
            if off + n <= 4 and owned & ~lanes:
                out.append((off, n))
    return out


class _Cfg:
    """Seed-drawn plan of the leaf."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.block_order = list(BLOCKS)
        rng.shuffle(self.block_order)
        self.sweep_order = list(BLOCKS)
        rng.shuffle(self.sweep_order)
        self.hole = {}
        for b in BLOCKS:
            lo, hi = HOLE_RANGE[b]
            self.hole[b] = lo + 4 * rng.randrange((hi - lo) // 4)
        self.refault_ops = ["rd" if rng.getrandbits(1) else "wr" for _ in range(96)]
        self.clear_order = list(range(len(PERIPH_BITS)))
        rng.shuffle(self.clear_order)
        self.masks = []
        for _ in range(rng.randrange(1, 4)):
            while True:
                mk = rng.randrange(1, 1 << len(PERIPH_BITS))
                if bin(mk).count("1") >= 2 and any(mk >> i & 1 for i in UNLATCHABLE):
                    break
            self.masks.append(mk)
        self.retrig_clear = rng.choice(BLOCKS)
        self.retrig_set = rng.choice([b for b in BLOCKS if b != self.retrig_clear])
        self.dma_size = 4 * rng.randrange(1, MAX_COPY // 4 + 1)
        span = (WIN_HI + 1 - WIN_LO - self.dma_size) // 4
        self.dma_src = WIN_LO + 4 * rng.randrange(span + 1)
        # Partial-write legs (drawn after every earlier draw): the block order,
        # then per block the strobe byte range and the non-zero strobed bytes.
        self.partial_order = list(PARTIAL_BLOCKS)
        rng.shuffle(self.partial_order)
        self.partial: dict[str, tuple[int, int, int]] = {}
        for b in PARTIAL_BLOCKS:
            blk, reg = PARTIAL_REG[b]
            cands = _partial_ranges(blk.mask32(reg))
            off, n = cands[rng.randrange(len(cands))]
            data = 0
            for k in range(n):
                data |= rng.randrange(1, 0x100) << (8 * k)
            self.partial[b] = (off, n, data)
        # Unbacked word of each other register block, then the SI HMAC hole.
        self.other: dict[str, tuple[str, int]] = {}
        for name, block in OTHER_BLOCKS:
            kind, words = _unbacked_words(block)
            self.other[name] = (kind, words[rng.randrange(len(words))])
        lo, hi = HOLE_RANGE["hmac"]
        self.si_hole = lo + 4 * rng.randrange((hi - lo) // 4)

    def draw_lines(self) -> list[str]:
        return [
            f"block_order={','.join(self.block_order)} sweep_order={','.join(self.sweep_order)}",
            "holes=" + ",".join(f"{b}:0x{self.hole[b]:08x}" for b in BLOCKS),
            "clear_order=" + ",".join(PERIPH_BITS[i] for i in self.clear_order),
            "masks=" + ",".join(f"0x{m:02x}" for m in self.masks),
            f"retrigger clear={self.retrig_clear} still_set={self.retrig_set}",
            f"dma_src=0x{self.dma_src:08x} dma_size={self.dma_size}",
            "refault_ops=" + "".join("r" if o == "rd" else "w" for o in self.refault_ops),
            "partial_order="
            + ",".join(self.partial_order)
            + " partial="
            + ",".join(f"{b}:off{o}/bytes{n}/data0x{d:x}" for b, (o, n, d) in self.partial.items()),
            "other="
            + ",".join(f"{b}:{k}:0x{a:08x}" for b, (k, a) in self.other.items())
            + f" si_hole=0x{self.si_hole:08x}",
        ]


class _PulseRec:
    """Clock-indexed record of the nonzero samples of the fault/clear pulse tap."""

    def __init__(self) -> None:
        self.clk = 0
        self.recs: list[tuple[int, int]] = []
        self._task = None

    def start(self) -> "_PulseRec":
        self._task = cocotb.start_soon(self._run())
        return self

    async def _run(self) -> None:
        dut = cocotb.top
        sig = dut.sep_cpu_ctrl_err_pulse_probe_o
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            self.clk += 1
            v = sig.value
            if not v.is_resolvable:
                raise AssertionError(f"PULSE-TAP-XZ FAIL: err pulse probe={v} clk={self.clk}")
            if int(v):
                self.recs.append((self.clk, int(v)))

    def mark(self) -> int:
        return len(self.recs)

    def clocks(self, mark: int, bit: int) -> list[int]:
        return [c for c, v in self.recs[mark:] if v >> bit & 1]

    async def stop(self) -> None:
        if self._task is not None:
            self._task.kill()
            self._task = None


@pyuvm.test()
class sep_cpu_bridge_fault_matrix_rand_test(sep_base_test):
    """Bridge-fault latches: multi-block set, clear matrix, masks, re-trigger, DMA host path, races."""

    # Stimulus model of PERIPH_BUS_ERR_STATUS: the faulted blocks not yet cleared.
    latched: int

    required_evidence = (
        "CHK-CTRL",
        "CHK-PARTIAL-WR",
        "CHK-PARTIAL-CLR",
        "CHK-SRC41-EXCL",
        "CHK-SRC42-EXCL",
        "CHK-SRC43-EXCL",
        "CHK-RESP",
        "CHK-LATCH",
        "CHK-OR",
        "CHK-CLR-MATRIX",
        "CHK-MASK",
        "CHK-AGAIN",
        "CHK-CLR-READ0",
        "CHK-DMA-CLR",
        "CHK-HOST",
        "CHK-DMA-HOST-HOLD",
        "CHK-RACE",
    )

    # ---- log helpers -----------------------------------------------------------
    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.c.seed, line)
        self.n_checks += 1
        self.counts[chk] = self.counts.get(chk, 0) + 1

    def _fail(self, chk: str, line: str) -> None:
        """Close the owner window first, so no held outcome of this run samples, then raise."""
        close_graded_window(self.logger)
        msg = f"{chk} FAIL seed={self.c.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _ctrl_missing(self, line: str) -> None:
        close_graded_window(self.logger)
        msg = f"CTRL-MISSING seed={self.c.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _expected_counts(self) -> dict[str, int]:
        """Number of PASS lines each checker logs for this seed's draws."""
        c = self.c
        n_blk, n_bits, n_masks = len(BLOCKS), len(PERIPH_BITS), len(c.masks)
        exp = {
            "CHK-CTRL": 1,
            "CHK-PARTIAL-WR": len(PARTIAL_BLOCKS),
            "CHK-PARTIAL-CLR": len(PARTIAL_BLOCKS),
            "CHK-RESP": self.wr_faults,
            "CHK-LATCH": n_blk,
            "CHK-OR": n_blk,
            "CHK-BRIDGE-HOLE-SI": 1,
            "CHK-CLR-READ0": 1,
            "CHK-DMA-CLR": 4,
            "CTRL-NONVAC": n_bits + n_masks,
            "CHK-CLR-MATRIX": n_bits + n_blk,
            "CHK-MASK": n_masks,
            "CHK-AGAIN": 2,
            "CHK-HOST": 1,
            "CHK-DMA-HOST-HOLD": 1,
            "CHK-RACE": n_blk + 1,
        }
        exp.update({f"CHK-SRC{src}-EXCL": 1 for src in EXCL_SRC})
        return exp

    # ---- FCOV pass label -----------------------------------------------------------
    async def _arm(self) -> None:
        """Start a graded instance: bfault_pass 0 drops every held outcome."""
        set_bfault_pass(False, self.logger)
        await ClockCycles(cocotb.top.clk_i, LABEL_CLK)

    async def _release(self) -> None:
        """The checks of this instance passed: bfault_pass 1 samples the held outcomes."""
        set_bfault_pass(True, self.logger)
        await ClockCycles(cocotb.top.clk_i, LABEL_CLK)

    async def _open(self) -> None:
        """Open the owner window right before a graded step and start an instance."""
        open_graded_window(TEST, self.logger)
        await self._arm()

    # ---- accesses ----------------------------------------------------------------
    async def _acc(
        self, op: SepAxiOp, addr: int, data: int = 0, nbytes: int = 4
    ) -> tuple[int, int]:
        """One single-beat access of ``nbytes`` bytes from ``addr`` (inside one word)."""
        kw = {"op": op, "addr": addr, "length": nbytes, "size": 2}
        if op is SepAxiOp.READ:
            kw["allow_ungraded_read_resp"] = True
        else:
            kw["wdata"] = data & ((1 << (8 * nbytes)) - 1)
            kw["allow_unverified_write_resp"] = True
        seq = SepAxiAccessSeq("fault_acc", **kw)
        await self.start_seq(seq)
        if seq.timed_out:
            raise AssertionError(f"CPU-LSU access 0x{addr:08x} timed out")
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF

    async def _rd_ok(self, addr: int) -> int:
        resp, v = await self._acc(SepAxiOp.READ, addr)
        if resp != RESP_OKAY:
            raise AssertionError(f"read 0x{addr:08x} answered {RESP_NAME.get(resp, resp)}")
        return v

    async def _wr_ok(self, addr: int, v: int) -> str:
        """Write ``v``; a response other than OKAY raises. Returns the response name."""
        resp, _ = await self._acc(SepAxiOp.WRITE, addr, v)
        if resp != RESP_OKAY:
            raise AssertionError(f"write 0x{addr:08x} answered {RESP_NAME.get(resp, resp)}")
        return RESP_NAME[resp]

    async def _periph(self) -> int:
        return await self._rd_ok(PERIPH_STATUS_ADDR)

    async def _dma(self) -> int:
        return await self._rd_ok(DMA_STATUS_ADDR)

    async def _vec(self) -> int:
        await ClockCycles(cocotb.top.clk_i, VEC_SETTLE)
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        v = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, VEC_MASK)
        await NextTimeStep()
        return v

    @staticmethod
    def _b(vec: int, idx: int) -> int:
        return (vec >> idx) & 1

    def _next_op(self) -> str:
        op = self.c.refault_ops[self.op_i % len(self.c.refault_ops)]
        self.op_i += 1
        return op

    async def _fault(self, b: str, op: str) -> int:
        """One access to the hole of ``b``; grades the response; updates the model."""
        addr = self.c.hole[b]
        if op == "wr":
            self.wr_faults += 1
            resp, _ = await self._acc(SepAxiOp.WRITE, addr, 0xA5A5_0000 | (addr & 0xFFFF))
            line = f"block={b} op=wr addr=0x{addr:08x} resp={RESP_NAME.get(resp, resp)}"
            if resp != RESP_SLVERR:
                self._fail("CHK-RESP", line)
            self._pass("CHK-RESP", line)
        else:
            resp, _ = await self._acc(SepAxiOp.READ, addr)
            line = (
                f"seed={self.c.seed} block={b} op=rd addr=0x{addr:08x} "
                f"resp={RESP_NAME.get(resp, resp)}"
            )
            if resp != RESP_SLVERR:
                close_graded_window(self.logger)
                msg = f"CTRL-RESP FAIL {line} expect=SLVERR"
                self.logger.error(msg)
                raise AssertionError(msg)
            self.logger.info("CTRL-RESP LOG %s", line)
        self.latched |= BIT[b]
        return resp

    async def _restore_full(self) -> None:
        for b in self.c.block_order:
            if not self.latched & BIT[b]:
                await self._fault(b, self._next_op())

    def _set_names(self, v: int) -> str:
        return ",".join(n for n in PERIPH_BITS if v & BIT[n]) or "none"

    # ---- legs --------------------------------------------------------------------
    async def _leg_ctrl(self) -> None:
        sim = str(getattr(cocotb, "SIM_NAME", "") or "").lower()
        x_free = "na" if "verilator" in sim else "1"
        p = await self._periph()
        d = await self._dma()
        vec = await self._vec()
        reads = []
        for b in self.c.block_order:
            resp, v = await self._acc(SepAxiOp.READ, LEGAL[b])
            reads.append((b, resp, v))
        p2 = await self._periph()
        d2 = await self._dma()
        vec2 = await self._vec()
        line = (
            f"legal_reads={len(reads)} status=0x{p2 & PERIPH_MASK:x} dma_status=0x{d2 & DMA_MASK:x} "
            f"reset_status=0x{p & PERIPH_MASK:x}/0x{d & DMA_MASK:x} vec40_42="
            f"{self._b(vec2, 40)}{self._b(vec2, 41)}{self._b(vec2, 42)} x_free={x_free} "
            + " ".join(f"{b}:{RESP_NAME.get(r, r)}" for b, r, _ in reads)
        )
        fcs = [
            field_compare(p, SEP_CPU_CTRL.reset32("PERIPH_BUS_ERR_STATUS"), PERIPH_MASK),
            field_compare(d, SEP_CPU_CTRL.reset32("DMA_BUS_ERR_STATUS"), DMA_MASK),
            field_compare(p2, 0, PERIPH_MASK),
            field_compare(d2, 0, DMA_MASK),
        ]
        ok = (
            all(f.ok for f in fcs)
            and (vec & VEC_MASK) == 0
            and (vec2 & VEC_MASK) == 0
            and all(r == RESP_OKAY for _, r, _ in reads)
        )
        if not ok:
            self._fail("CHK-CTRL", line)
        self._pass("CHK-CTRL", line)
        await self._release()

    async def _partial(self, b: str) -> None:
        """Partial write to the register of ``b``: SLVERR, own bit alone; value after it logged."""
        c = self.c
        blk, reg = PARTIAL_REG[b]
        addr = blk.addr(reg)
        fmask = blk.mask32(reg)
        rst = blk.reset32(reg)
        off, n, data = c.partial[b]
        lanes = ((1 << n) - 1) << off
        # Entry read and the full-strobe twin, outside the owner window.
        close_graded_window(self.logger)
        pre = await self._rd_ok(addr)
        st0 = await self._periph()
        resp_c, _ = await self._acc(SepAxiOp.WRITE, addr, rst)
        st1 = await self._periph()
        vec_c = await self._vec()
        ctl = (
            f"block={b} reg={reg} addr=0x{addr:08x} wdata=0x{rst:x} strobe=0xf "
            f"resp={RESP_NAME.get(resp_c, resp_c)} status_before=0x{st0 & PERIPH_MASK:02x} "
            f"status_after=0x{st1 & PERIPH_MASK:02x} vec42={self._b(vec_c, 42)}"
        )
        self.logger.info("CTRL-FULL-STROBE LOG seed=%d %s", c.seed, ctl)
        if resp_c != RESP_OKAY or st0 & PERIPH_MASK or st1 & PERIPH_MASK or self._b(vec_c, 42):
            self._ctrl_missing(f"CTRL-FULL-STROBE {ctl} expect=OKAY,status=0,vec42=0")
        # The graded partial write.
        await self._open()
        mk = self.pulses.mark()
        exp_resp = RESP_SLVERR
        resp, _ = await self._acc(SepAxiOp.WRITE, addr + off, data, nbytes=n)
        st = await self._periph()
        vec = await self._vec()
        post = await self._rd_ok(addr)
        pulses = self.pulses.clocks(mk, PROBE_SET[b])
        f_st = field_compare(st, BIT[b], PERIPH_MASK)
        f_pre = field_compare(pre, rst, fmask)
        f_post = field_compare(post, rst, fmask)
        line = (
            f"block={b} reg={reg} addr=0x{addr + off:08x} lanes=0x{lanes:x} "
            f"owned=0x{_owned_bytes(fmask):x} wdata=0x{data:x} resp={RESP_NAME.get(resp, resp)} "
            f"expect={RESP_NAME[exp_resp]} fault_pulse_clks={pulses} "
            f"status=0x{st & PERIPH_MASK:02x} exp_status=0x{BIT[b]:02x} vec42={self._b(vec, 42)} "
            f"pre=0x{pre:08x} rdl_reset=0x{rst:x} field_mask=0x{fmask:x} "
            f"status[{f_st.fields()}] pre[{f_pre.fields()}]"
        )
        ok = (
            resp == exp_resp and len(pulses) >= 1 and f_st.ok and self._b(vec, 42) == 1 and f_pre.ok
        )
        if not ok:
            self._fail("CHK-PARTIAL-WR", line)
        self._pass("CHK-PARTIAL-WR", line)
        # No specification sentence states the register value after a refused
        # partial write: the read after it is logged only.
        self.logger.info(
            "OBS-PARTIAL-KEPT LOG seed=%d block=%s reg=%s pre=0x%08x post=0x%08x "
            "rdl_reset=0x%x field_mask=0x%x post_fields_equal_reset=%d",
            c.seed,
            b,
            reg,
            pre,
            post,
            rst,
            fmask,
            int(f_post.ok),
        )
        if fmask != 0xFFFF_FFFF:
            self.logger.info(
                "OBS-PARTIAL-RSVD LOG seed=%d block=%s reg=%s pre_raw=0x%08x post_raw=0x%08x "
                "reason=bits_outside_the_rdl_fields_have_no_stated_value",
                c.seed,
                b,
                reg,
                pre,
                post,
            )
        self.latched |= BIT[b]
        text, ok = await self._clear_write(BIT[b])
        line = f"block={b} clear=0x{BIT[b]:02x} {text}"
        if not ok:
            self._fail("CHK-PARTIAL-CLR", line)
        self._pass("CHK-PARTIAL-CLR", line)
        await self._release()

    async def _leg_partial(self) -> None:
        for b in self.c.partial_order:
            await self._partial(b)

    async def _leg_excl(self) -> None:
        """CHK-SRC41/42/43-EXCL over every rise of the run since the watcher mark.

        After each check passes, the bit of its source joins ``exo_pass``,
        which releases the held ``cp_src_exclusive_other`` rises of that
        source; the label returns to 0 after the last check.
        """
        released = 0
        for src in EXCL_SRC:
            key = f"s{src}"
            same = EXCL_SAME[src]
            try:
                rises = self.vw.rises_since(self.vw_mark, key)
                smears = self.vw.smears_since(self.vw_mark, key, same_clock=same)
            except AssertionError as exc:
                # VecWatchNoRiseError (no rise of the own bit), an idle or dead watcher.
                self._fail(f"CHK-SRC{src}-EXCL", f"src={src} vec_bit={vec_bit(src)} {exc}")
            line = (
                f"src={src} vec_bit={vec_bit(src)} rises={len(rises)} "
                f"rise_clks={[r.clk for r in rises][:8]} smears={len(smears)} "
                f"first_smear={[(k, hex(m)) for k, m in smears[:2]]} same_clock=0x{same:x}"
            )
            if smears or not rises:
                self._fail(f"CHK-SRC{src}-EXCL", line)
            self._pass(f"CHK-SRC{src}-EXCL", line)
            released |= exo_pass_bit(src)
            set_exo_pass(released, self.logger)
            await ClockCycles(cocotb.top.clk_i, LABEL_CLK)
        set_exo_pass(0, self.logger)

    async def _leg_latch(self) -> None:
        resps = []
        for b in self.c.block_order:
            await self._arm()
            resps.append(await self._fault(b, "wr"))
            st = await self._periph()
            vec = await self._vec()
            fc = field_compare(st, self.latched, PERIPH_MASK)
            line = (
                f"set={self._set_names(self.latched)} status=0x{st & PERIPH_MASK:02x} "
                f"vec42={self._b(vec, 42)} resp="
                + ",".join(RESP_NAME[r] for r in resps)
                + f" [{fc.fields()}]"
            )
            if not fc.ok or self._b(vec, 42) != 1:
                self._fail("CHK-LATCH", line)
            self._pass("CHK-LATCH", line)
            orl = f"vec42={self._b(vec, 42)} status=0x{st & PERIPH_MASK:02x}"
            if self._b(vec, 42) != int(bool(st & PERIPH_MASK)):
                self._fail("CHK-OR", orl)
            self._pass("CHK-OR", orl)
            await self._release()

    async def _obs_hole(self, init: str, block: str, addr: int, access) -> tuple[int, int]:
        """OBS-BRIDGE-HOLE: one unbacked-word read and the fault latch state around it.

        No line states whether a fault in a block outside the seven
        PERIPH_BUS_ERR_STATUS bits, or a fault from the SI, latches a bit. The
        line logs the response, the read data, the status, vector bit 42 and
        the fault pulses; a bit the access set is cleared again so the stimulus
        model holds. Returns the response and the read data.
        """
        before = await self._periph()
        mark = self.pulses.mark()
        resp, rdata = await access()
        st = await self._periph()
        vec = await self._vec()
        pulse = 0
        for _clk, v in self.pulses.recs[mark:]:
            pulse |= v
        self.logger.info(
            "OBS-BRIDGE-HOLE init=%s block=%s addr=0x%08x resp=%s rdata=0x%08x "
            "periph_status=0x%x vec42=%d err_pulse=0x%x",
            init,
            block,
            addr,
            RESP_NAME.get(resp, resp),
            rdata,
            st & PERIPH_MASK,
            self._b(vec, 42),
            pulse,
        )
        new = st & PERIPH_MASK & ~before
        if new:
            await self._wr_ok(PERIPH_CLEAR_ADDR, new)
        return resp, rdata

    async def _leg_other_holes(self) -> None:
        close_graded_window(self.logger)
        mon = self.env.axi_monitor
        for name, (_kind, addr) in self.c.other.items():

            async def _lsu(addr: int = addr) -> tuple[int, int]:
                mon.arm_expected_decerr(1)
                resp, rdata = await self._acc(SepAxiOp.READ, addr)
                if resp != RESP_DECERR:
                    mon.release_expected_decerr(1)
                return resp, rdata

            await self._obs_hole("lsu", name, addr, _lsu)
        ibank = SepFilterBank(self, "in")
        await ibank.program(
            0,
            FilterEntry(
                start=self.c.si_hole,
                end=self.c.si_hole + 3,
                enabled=True,
                read_allowed=True,
                allow_ns=True,
            ),
        )

        async def _si() -> tuple[int, int]:
            ext = self.env.ext_axi_monitor
            ext.open_error_rdata_window()
            seq = SepAxiAccessSeq(
                "si_hmac_hole",
                op=SepAxiOp.READ,
                addr=self.c.si_hole,
                length=4,
                size=2,
                allow_ungraded_read_resp=True,
            )
            try:
                await self.start_ext_seq(seq)
            finally:
                ext.close_error_rdata_window()
            if seq.timed_out:
                raise AssertionError(f"SI read 0x{self.c.si_hole:08x} timed out")
            return seq.resp_code, seq.rdata & 0xFFFF_FFFF

        resp, rdata = await self._obs_hole("si", "hmac", self.c.si_hole, _si)
        line = (
            f"init=si block=hmac addr=0x{self.c.si_hole:08x} resp={RESP_NAME.get(resp, resp)} "
            f"rdata=0x{rdata:08x} expect=SLVERR/0x{SI_HOLE_RDATA:08x}"
        )
        if (resp, rdata) != (RESP_SLVERR, SI_HOLE_RDATA):
            self._fail("CHK-BRIDGE-HOLE-SI", line)
        self._pass("CHK-BRIDGE-HOLE-SI", line)
        await ibank.restore_reset(0)

    async def _dma_reg_fault(self) -> tuple[int, int]:
        resp, _ = await self._acc(SepAxiOp.READ, dma_reg_unmapped_addr())
        self.logger.info(
            "CTRL-RESP LOG seed=%d block=dma_reg op=rd addr=0x%08x resp=%s",
            self.c.seed,
            dma_reg_unmapped_addr(),
            RESP_NAME.get(resp, resp),
        )
        return resp, await self._dma()

    async def _leg_dma_reg(self) -> None:
        close_graded_window(self.logger)
        resp, d = await self._dma_reg_fault()
        vec = await self._vec()
        self.ctrl_reg_path_err = int(bool(d & DMA_REG_PATH_BIT))
        self.logger.info(
            "CTRL-LATCH LOG seed=%d block=dma_reg resp=%s dma_status=0x%x vec40=%d",
            self.c.seed,
            RESP_NAME.get(resp, resp),
            d & DMA_MASK,
            self._b(vec, 40),
        )
        if resp != RESP_SLVERR or (d & DMA_MASK) != DMA_REG_PATH_BIT or self._b(vec, 40) != 1:
            self._ctrl_missing(
                f"CTRL-LATCH dma_reg set-up resp={resp} dma_status=0x{d:x} vec40={self._b(vec, 40)}"
            )
        # Precondition read of PERIPH_BUS_ERR_STATUS, outside the owner window.
        p = await self._periph()
        await self._open()
        pc = await self._acc(SepAxiOp.READ, PERIPH_CLEAR_ADDR)
        dc = await self._acc(SepAxiOp.READ, DMA_CLEAR_ADDR)
        f1 = field_compare(pc[1], 0, PERIPH_CLR_MASK)
        f2 = field_compare(dc[1], 0, DMA_CLR_MASK)
        line = (
            f"periph_status=0x{p & PERIPH_MASK:x} periph_clear=0x{pc[1] & PERIPH_CLR_MASK:x} "
            f"dma_status=0x{d & DMA_MASK:x} dma_clear=0x{dc[1] & DMA_CLR_MASK:x} "
            f"resp={RESP_NAME.get(pc[0])}/{RESP_NAME.get(dc[0])} periph_clear[{f1.fields()}] "
            f"dma_clear[{f2.fields()}]"
        )
        if (
            not (p & PERIPH_MASK)
            or not (d & DMA_MASK)
            or not f1.ok
            or not f2.ok
            or pc[0] != RESP_OKAY
            or dc[0] != RESP_OKAY
        ):
            self._fail("CHK-CLR-READ0", line)
        self._pass("CHK-CLR-READ0", line)
        await self._release()
        # Register-path write of 0, then the write of 1 (the control).
        await self._arm()
        r0 = await self._wr_ok(DMA_CLEAR_ADDR, 0)
        d0 = await self._dma()
        v0 = await self._vec()
        line = (
            f"write0=still_set write0_resp={r0} reg_path_err={int(bool(d0 & DMA_REG_PATH_BIT))} "
            f"vec40={self._b(v0, 40)} dma_status=0x{d0 & DMA_MASK:x}"
        )
        if (d0 & DMA_MASK) != DMA_REG_PATH_BIT or self._b(v0, 40) != 1:
            self._fail("CHK-DMA-CLR", line)
        self._pass("CHK-DMA-CLR", line)
        await self._release()
        close_graded_window(self.logger)
        await self._wr_ok(DMA_CLEAR_ADDR, 1)
        d1 = await self._dma()
        v1 = await self._vec()
        self.logger.info(
            "CTRL-DMA-CLR LOG seed=%d write1=reg_path_clear reg_path_err=%d vec40=%d",
            self.c.seed,
            int(bool(d1 & DMA_REG_PATH_BIT)),
            self._b(v1, 40),
        )
        if d1 & DMA_REG_PATH_BIT or self._b(v1, 40):
            self._ctrl_missing(f"CTRL-DMA-CLR write of 1 did not clear: dma_status=0x{d1:x}")
        line = (
            f"cell=reg_clear host_path_err={int(bool(d1 & DMA_HOST_PATH_BIT))} "
            f"vec41={self._b(v1, 41)}"
        )
        if d1 & DMA_HOST_PATH_BIT or self._b(v1, 41):
            self._fail("CHK-DMA-CLR", line)
        self._pass("CHK-DMA-CLR", line)

    async def _clear_write(self, bits: int) -> tuple[str, bool]:
        """Write ``bits`` to the clear register and grade against the stimulus model.

        The expected latch set before the write is the model set of the faults
        this leaf drove (``self.latched``) and after it that set minus ``bits``;
        neither comes from a status read. Returns (compare text, ok).
        """
        exp_before = self.latched & PERIPH_MASK
        before = await self._periph()
        resp = await self._wr_ok(PERIPH_CLEAR_ADDR, bits)
        self.latched &= ~bits
        exp_after = self.latched & PERIPH_MASK
        after = await self._periph()
        vec = await self._vec()
        fb = field_compare(before, exp_before, PERIPH_MASK)
        fc = field_compare(after, exp_after, PERIPH_MASK)
        text = (
            f"before=0x{before & PERIPH_MASK:02x} exp_before=0x{exp_before:02x} "
            f"write=0x{bits:02x} resp={resp} after=0x{after & PERIPH_MASK:02x} exp_after=0x{exp_after:02x} "
            f"vec42={self._b(vec, 42)} [{fc.fields()}]"
        )
        ok = fb.ok and fc.ok and self._b(vec, 42) == int(bool(exp_after))
        return text, ok

    async def _clear_step(self, chk: str, bits: int, tag: str) -> None:
        exp_before = self.latched & PERIPH_MASK
        nb = bin(exp_before).count("1")
        nv = f"step={tag} latched_before=0x{exp_before:02x} bits={nb}"
        if nb < 2:
            self._fail("CTRL-NONVAC", nv)
        self._pass("CTRL-NONVAC", nv)
        text, ok = await self._clear_write(bits)
        line = f"{tag} {text}"
        if not ok:
            self._fail(chk, line)
        self._pass(chk, line)

    async def _leg_matrix(self) -> None:
        open_graded_window(TEST, self.logger)
        for i in self.c.clear_order:
            await self._arm()
            await self._restore_full()
            twin = "latched" if PERIPH_BITS[i] in BLOCKS else "unlatched_twin=latched_bits"
            await self._clear_step("CHK-CLR-MATRIX", 1 << i, f"cleared={PERIPH_BITS[i]} {twin}")
            await self._release()
        # Drain to zero, one latched bit at a time in the clear order. The
        # restore faults are graded by CHK-RESP and by the first drain step's
        # comparison of the status before the clear with the model.
        await self._arm()
        await self._restore_full()
        order = [i for i in self.c.clear_order if PERIPH_BITS[i] in BLOCKS]
        for k, i in enumerate(order):
            if k:
                await self._arm()
            text, ok = await self._clear_write(1 << i)
            line = f"drain={k + 1}/{len(order)} cleared={PERIPH_BITS[i]} {text}"
            if not ok:
                self._fail("CHK-CLR-MATRIX", line)
            self._pass("CHK-CLR-MATRIX", line)
            await self._release()

    async def _leg_masks(self) -> None:
        for k, mk in enumerate(self.c.masks):
            await self._arm()
            await self._restore_full()
            await self._clear_step("CHK-MASK", mk, f"step={k + 1} mask=0x{mk:02x}")
            await self._release()

    async def _leg_again(self) -> None:
        c = self.c
        await self._arm()
        await self._restore_full()
        b = c.retrig_clear
        await self._wr_ok(PERIPH_CLEAR_ADDR, BIT[b])
        self.latched &= ~BIT[b]
        exp_mid = self.latched & PERIPH_MASK
        mid = await self._periph()
        await self._fault(b, self._next_op())
        after = await self._periph()
        vec = await self._vec()
        others = after & ~BIT[b] & PERIPH_MASK
        exp_others = self.latched & ~BIT[b]
        line = (
            f"block={b} relatched={int(bool(after & BIT[b]))} others_kept=0x{others:02x} "
            f"cleared_status=0x{mid & PERIPH_MASK:02x} exp_cleared=0x{exp_mid:02x} "
            f"after=0x{after & PERIPH_MASK:02x} vec42={self._b(vec, 42)}"
        )
        if (
            (mid & PERIPH_MASK) != exp_mid
            or not after & BIT[b]
            or others != exp_others
            or self._b(vec, 42) != 1
        ):
            self._fail("CHK-AGAIN", line)
        self._pass("CHK-AGAIN", line)
        await self._release()
        b2 = c.retrig_set
        # Precondition read; the arm after it drops its outcomes.
        before = await self._periph()
        await self._arm()
        exp_after = self.latched & PERIPH_MASK
        await self._fault(b2, self._next_op())
        after = await self._periph()
        line = (
            f"block={b2} still_set=1 before=0x{before & PERIPH_MASK:02x} "
            f"after=0x{after & PERIPH_MASK:02x} exp_after=0x{exp_after:02x} "
            f"others_kept=0x{after & ~BIT[b2] & PERIPH_MASK:02x}"
        )
        if (
            not before & BIT[b2]
            or (after & PERIPH_MASK) != (before & PERIPH_MASK)
            or (after & PERIPH_MASK) != exp_after
        ):
            self._fail("CHK-AGAIN", line)
        self._pass("CHK-AGAIN", line)
        await self._release()

    # ---- DMA host path -------------------------------------------------------------
    async def _idle_check(self, tag: str, bus_err: int | None = None) -> None:
        """CTRL-DMA-IDLE: STATUS.BUSY and STATUS.ERROR clear, and DMA_BUS_ERR_STATUS
        clear when ``bus_err`` is given."""
        st = await self.dma.read_status()
        line = (
            f"seed={self.c.seed} {tag}: status=0x{st.raw:x} busy={int(bool(st.raw & ST_BUSY))} "
            f"error={int(bool(st.raw & ST_ERROR))}"
        )
        if bus_err is not None:
            line += f" bus_err_status=0x{bus_err & DMA_MASK:02x}"
        if st.raw & (ST_BUSY | ST_ERROR) or (bus_err or 0) & DMA_MASK:
            self._ctrl_missing(f"DMA-IDLE {line}")
        self.logger.info("CTRL-DMA-IDLE seen %s", line)

    async def _w1c_error(self) -> None:
        await self.dma.wr(_D.addr("STATUS"), ST_ERROR)

    async def _failing_copy(self, size: int) -> tuple[object, int, int]:
        """A copy from the outbound window whose source reads answer SLVERR."""
        dut = cocotb.top
        await self.dma.program_transfer(src=self.c.dma_src, dst=DST, total=size, chunk=size)
        m_ar = self.out.mark()
        m_r = self.out_rsp.mark()
        dut.smn_outbound_rd_slverr_i.value = 1
        await self.dma.go()
        st = None
        for _ in range(ERR_POLL_BOUND):
            st = await self.dma.read_status()
            if st.error or st.done:
                break
        dut.smn_outbound_rd_slverr_i.value = 0
        ars = len(self.out.since(m_ar, "ar"))
        slv = sum(1 for b in self.out_rsp.since(m_r, "r") if b.resp == RESP_SLVERR)
        return st, ars, slv

    async def _leg_host(self) -> None:
        c = self.c
        close_graded_window(self.logger)
        await self._wr_ok(DMA_CLEAR_ADDR, 1)
        bus_err = await self._dma()
        for idx, ns in zip(OUT_PAIR, (False, True)):
            await self.obank.program(
                idx,
                FilterEntry(
                    start=WIN_LO,
                    end=WIN_HI,
                    enabled=True,
                    read_allowed=True,
                    write_allowed=False,
                    allow_ns=ns,
                    allow_burst=True,
                    src_id=0,
                ),
            )
        await self.dma.program_range(0x0, 0xFFFF_FFFF, valid=True)
        await self.dma.wr(_D.addr("ADDR_SPACE_ID"), ASID_RESET)
        await self._idle_check("before host copy", bus_err)
        await self._open()
        st, ars, slv = await self._failing_copy(c.dma_size)
        ecode = await self.dma.rd(_D.addr("ERROR_CODE"))
        d = await self._dma()
        vec = await self._vec()
        line = (
            f"side=src slverr_reads={slv} src_reads={ars} error={st.error} "
            f"bus_error={int(bool(ecode & BUS_ERROR))} bus_err_status=0x{d & DMA_MASK:02x} "
            f"vec41={self._b(vec, 41)} vec40={self._b(vec, 40)} "
            f"ctrl_reg_path_err={self.ctrl_reg_path_err} done={st.done} "
            f"error_code=0x{ecode:x} size={c.dma_size} src=0x{c.dma_src:08x}"
        )
        ok = (
            slv >= 1
            and st.error == 1
            and ecode & BUS_ERROR
            and (d & DMA_MASK) == DMA_HOST_PATH_BIT
            and self._b(vec, 41) == 1
            and self._b(vec, 40) == 0
            and self.ctrl_reg_path_err == 1
        )
        if not ok:
            self._fail("CHK-HOST", line)
        self._pass("CHK-HOST", line)
        await self._release()

        # A write of 1 to STATUS.ERROR leaves the host-path latch and source 42.
        await self._arm()
        await self._w1c_error()
        st_w = await self.dma.read_status()
        d = await self._dma()
        vec = await self._vec()
        line = (
            f"after=status_error_w1c error={st_w.error} "
            f"host_path_err={int(bool(d & DMA_HOST_PATH_BIT))} "
            f"bus_err_status=0x{d & DMA_MASK:02x} vec41={self._b(vec, 41)}"
        )
        if st_w.error != 0 or not d & DMA_HOST_PATH_BIT or self._b(vec, 41) != 1:
            self._fail("CHK-DMA-HOST-HOLD", line)
        self._pass("CHK-DMA-HOST-HOLD", line)
        await self._release()

        # Host-path clear cells; cell=host_only is the control of CHK-DMA-HOST-HOLD.
        before = d & DMA_MASK
        await self._arm()
        r0 = await self._wr_ok(DMA_CLEAR_ADDR, 0)
        a0 = await self._dma()
        await self._wr_ok(DMA_CLEAR_ADDR, 1)
        a1 = await self._dma()
        v1 = await self._vec()
        line = (
            f"cell=host_only before=0x{before:x} write0_resp={r0} after_write0=0x{a0 & DMA_MASK:x} "
            f"after_write1=0x{a1 & DMA_MASK:x} vec40={self._b(v1, 40)} vec41={self._b(v1, 41)}"
        )
        if (
            before != DMA_HOST_PATH_BIT
            or (a0 & DMA_MASK) != DMA_HOST_PATH_BIT
            or a1 & DMA_MASK
            or self._b(v1, 40)
            or self._b(v1, 41)
        ):
            self._fail("CHK-DMA-CLR", line)
        self._pass("CHK-DMA-CLR", line)
        await self._release()
        close_graded_window(self.logger)
        await self._w1c_error()
        await self._idle_check("before second host copy")
        # cell=both: a second host-path fault and a register-path fault, then the
        # write of 0 and the write of 1.
        await self._open()
        st2, _, slv2 = await self._failing_copy(c.dma_size)
        if not st2.error or not slv2:
            self._fail("CHK-DMA-CLR", f"cell=both set-up copy: {st2.fmt()} slverr_reads={slv2}")
        resp_r, d_r = await self._dma_reg_fault()
        before = d_r & DMA_MASK
        vb = await self._vec()
        r0 = await self._wr_ok(DMA_CLEAR_ADDR, 0)
        a0 = await self._dma()
        await self._wr_ok(DMA_CLEAR_ADDR, 1)
        a1 = await self._dma()
        v1 = await self._vec()
        line = (
            f"cell=both reg_fault_resp={RESP_NAME.get(resp_r, resp_r)} before=0x{before:x} "
            f"before_vec40={self._b(vb, 40)} before_vec41={self._b(vb, 41)} "
            f"write0_resp={r0} after_write0=0x{a0 & DMA_MASK:x} "
            f"after_write1=0x{a1 & DMA_MASK:x} vec40={self._b(v1, 40)} vec41={self._b(v1, 41)}"
        )
        both = DMA_HOST_PATH_BIT | DMA_REG_PATH_BIT
        if (
            resp_r != RESP_SLVERR
            or before != both
            or self._b(vb, 40) != 1
            or self._b(vb, 41) != 1
            or (a0 & DMA_MASK) != both
            or a1 & DMA_MASK
            or self._b(v1, 40)
            or self._b(v1, 41)
        ):
            self._fail("CHK-DMA-CLR", line)
        self._pass("CHK-DMA-CLR", line)
        await self._release()
        close_graded_window(self.logger)
        st_c = await self.dma.read_status()
        ecode_c = await self.dma.rd(_D.addr("ERROR_CODE"))
        self.logger.info(
            "OBS-DMA-HOST-CLR LOG seed=%d after=dma_bus_err_clear error=%d bus_error=%d "
            "reason=no_sentence_states_whether_dma_bus_err_clear_changes_the_dma_report",
            self.c.seed,
            st_c.error,
            int(bool(ecode_c & BUS_ERROR)),
        )
        await self._w1c_error()

    # ---- same-cycle races -------------------------------------------------------------
    def _vip(self):
        return self.env.axi_agent.driver.axi

    async def _vip_wr(self, addr: int, data: int, axi_id: int = 0) -> int:
        r = await self._vip().write_bytes_result(
            addr,
            (data & 0xFFFF_FFFF).to_bytes(4, "little"),
            size=2,
            id=axi_id,
            check_response=False,
            timeout_ns=VIP_NS,
        )
        return r.resp

    async def _vip_rd(self, addr: int, axi_id: int = 0) -> int:
        r = await self._vip().read_bytes_result(
            addr, 4, size=2, id=axi_id, check_response=False, timeout_ns=VIP_NS
        )
        return r.resp

    async def _pair(self, first, second, gap: int) -> tuple:
        """Start ``first``; ``gap`` clocks later start ``second``; await both."""
        t1 = cocotb.start_soon(first)
        if gap:
            await ClockCycles(cocotb.top.clk_i, gap)
        t2 = cocotb.start_soon(second)
        return await t1, await t2

    def _next_offset(self, tried: set, d: int, delta: int) -> int | None:
        est = d + delta
        for cand in (est, est + 1, est - 1, est + 2, est - 2):
            if abs(cand) <= RACE_RANGE and cand not in tried:
                return cand
        for cand in range(-RACE_RANGE, RACE_RANGE + 1):
            if cand not in tried:
                return cand
        return None

    async def _race_periph(self, b: str) -> None:
        sb, cb = PROBE_SET[b], PROBE_CLR[b]
        tried: set = set()
        d = 0
        hole = self.c.hole[b]
        # The trials run with the owner window closed; only the graded read
        # after a coincidence opens it. Only the clear and the faults of ``b``
        # touch PERIPH_BUS_ERR_STATUS, so every other bit keeps its model value.
        close_graded_window(self.logger)
        exp_others = self.latched & ~BIT[b] & PERIPH_MASK
        for trial in range(1, RACE_TRIALS + 1):
            if not self.latched & BIT[b] or not (await self._periph()) & BIT[b]:
                await self._fault(b, "wr")
            tried.add(d)
            mk = self.pulses.mark()
            wr = self._vip_wr(PERIPH_CLEAR_ADDR, BIT[b])
            rd = self._vip_rd(hole)
            if d >= 0:
                wresp, rresp = await self._pair(wr, rd, d)
            else:
                rresp, wresp = await self._pair(rd, wr, -d)
            await ClockCycles(cocotb.top.clk_i, 4)
            sets, clrs = self.pulses.clocks(mk, sb), self.pulses.clocks(mk, cb)
            coin = sorted(set(sets) & set(clrs))
            self.logger.info(
                "INFO-RACE-TRIAL LOG seed=%d kind=periph block=%s trial=%d offset=%d fault_clks=%s "
                "clear_clks=%s wr=%s rd=%s",
                self.c.seed,
                b,
                trial,
                d,
                sets,
                clrs,
                RESP_NAME.get(wresp),
                RESP_NAME.get(rresp),
            )
            if rresp != RESP_SLVERR or wresp != RESP_OKAY:
                self._fail("CHK-RACE", f"kind=periph block={b} wr={wresp} rd={rresp}")
            if coin:
                await self._open()
                st = await self._periph()
                vec = await self._vec()
                later = [s for s in self.pulses.clocks(mk, sb) if s > coin[0]]
                exp = exp_others | BIT[b]
                line = (
                    f"kind=periph block={b} coincident=1 later_faults={len(later)} "
                    f"status_after=0x{st & PERIPH_MASK:02x} exp_status=0x{exp:02x} "
                    f"vec42={self._b(vec, 42)} offset={d} trials={trial} clk={coin[0]}"
                )
                if later or (st & PERIPH_MASK) != exp or self._b(vec, 42) != 1:
                    self._fail("CHK-RACE", line)
                self._pass("CHK-RACE", line)
                await self._release()
                close_graded_window(self.logger)
                self.latched = exp
                return
            st = await self._periph()
            # The race outcome of ``b`` in a trial without a coincidence depends on
            # the order of the two pulses; the other bits stay at the model.
            self.latched = exp_others | (st & BIT[b])
            if not sets or not clrs:
                self._fail(
                    "CHK-RACE", f"kind=periph block={b} missing pulse sets={sets} clrs={clrs}"
                )
            nd = self._next_offset(tried, d, clrs[0] - sets[0])
            if nd is None:
                break
            d = nd
        self._fail("CHK-RACE", f"kind=periph block={b} coincident=0 after {len(tried)} trials")

    async def _race_dma(self) -> None:
        dut = cocotb.top
        sb, cb = PROBE_SET["dma_host"], PROBE_CLR["dma_host"]
        tried: set = set()
        d = 0
        src = self.c.dma_src
        # The trials run with the owner window closed; only the graded read
        # after a coincidence opens it.
        close_graded_window(self.logger)
        for trial in range(1, RACE_TRIALS + 1):
            tried.add(d)
            await self._w1c_error()
            await self._idle_check(f"race trial {trial} latch")
            st, _, _ = await self._failing_copy(4)
            if not st.error:
                self._fail("CHK-RACE", f"kind=dma latch copy did not error: {st.fmt()}")
            await self._w1c_error()
            await self._idle_check(f"race trial {trial} second copy")
            await self.dma.program_transfer(src=src, dst=DST, total=4, chunk=4)
            mk = self.pulses.mark()
            dut.smn_outbound_rd_slverr_i.value = 1
            go = self._vip_wr(_D.addr("CONTROL"), self._go_word)
            clr = self._vip_wr(DMA_CLEAR_ADDR, 1, axi_id=1)
            await self._pair(go, clr, d)
            for _ in range(ERR_POLL_BOUND):
                s2 = await self.dma.read_status()
                if s2.error or s2.done:
                    break
            dut.smn_outbound_rd_slverr_i.value = 0
            await ClockCycles(dut.clk_i, 4)
            sets, clrs = self.pulses.clocks(mk, sb), self.pulses.clocks(mk, cb)
            coin = sorted(set(sets) & set(clrs))
            self.logger.info(
                "INFO-RACE-TRIAL LOG seed=%d kind=dma trial=%d offset=%d fault_clks=%s clear_clks=%s "
                "error=%d",
                self.c.seed,
                trial,
                d,
                sets,
                clrs,
                s2.error,
            )
            if coin:
                await self._open()
                dst_ = await self._dma()
                vec = await self._vec()
                later = [s for s in self.pulses.clocks(mk, sb) if s > coin[0]]
                line = (
                    f"kind=dma coincident=1 later_faults={len(later)} "
                    f"status_after=0x{dst_ & DMA_MASK:02x} exp_status=0x{DMA_HOST_PATH_BIT:02x} "
                    f"vec41={self._b(vec, 41)} vec40={self._b(vec, 40)} offset={d} "
                    f"trials={trial} clk={coin[0]}"
                )
                if (
                    later
                    or (dst_ & DMA_MASK) != DMA_HOST_PATH_BIT
                    or self._b(vec, 41) != 1
                    or self._b(vec, 40) != 0
                ):
                    self._fail("CHK-RACE", line)
                self._pass("CHK-RACE", line)
                await self._release()
                close_graded_window(self.logger)
                await self._w1c_error()
                return
            if not sets or not clrs:
                self._fail("CHK-RACE", f"kind=dma missing pulse sets={sets} clrs={clrs}")
            nd = self._next_offset(tried, d, sets[0] - clrs[0])
            if nd is None or nd < 0:
                nd = next((x for x in range(RACE_RANGE + 1) if x not in tried), None)
            if nd is None:
                break
            d = nd
        self._fail("CHK-RACE", f"kind=dma coincident=0 after {len(tried)} trials")

    # ---- scenario ----------------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.c = c = _Cfg(seed)
        self.n_checks = 0
        self.counts: dict[str, int] = {}
        self.wr_faults = 0
        self.op_i = 0
        self.latched = 0
        self.ctrl_reg_path_err = 0
        self.logger.info("INFO-SEED seed=%d", seed)
        for d in c.draw_lines():
            self.logger.info("INFO-DRAW %s", d)
        self.cfg.wdt_clk_period_ns = WDT_CLK_RATIO * self.cfg.sys_clk_period_ns
        self.logger.info(
            "INFO-WDT-CLK clk_wdt=%s ns (%dx core)",
            self.cfg.wdt_clk_period_ns,
            WDT_CLK_RATIO,
        )
        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        self.dma = SepDmaOps(self)
        self.obank = SepFilterBank(self, "out")
        self.out = SepFabricTap("PR-OUT").start()
        self.out_rsp = SepFabricTap("PR-OUT-RSP").start()
        self.pulses = _PulseRec().start()
        self.vw = pic_vector_watch({f"s{s}": vec_bit(s) for s in EXCL_SRC}).start()
        self.vw_mark = self.vw.mark()
        self._go_word = control_word(go=1, initial=1)

        await self._open()
        await self._leg_ctrl()
        await self._leg_partial()
        await self._leg_latch()
        await self._leg_other_holes()
        await self._leg_dma_reg()
        await self._leg_matrix()
        await self._leg_masks()
        await self._leg_again()
        await self._leg_host()
        for b in c.sweep_order:
            await self._race_periph(b)
        await self._race_dma()
        await self._leg_excl()
        exp = self._expected_counts()
        diff = {k: (self.counts.get(k, 0), n) for k, n in exp.items() if self.counts.get(k, 0) != n}
        diff.update({k: (n, 0) for k, n in self.counts.items() if k not in exp})
        if diff:
            self._ctrl_missing(f"CTRL-CHK-COUNTS got/expected={diff}")
        self.logger.info(
            "CTRL-CHK-COUNTS seen seed=%d names=%d lines=%d wr_faults=%d",
            seed,
            len(exp),
            sum(exp.values()),
            self.wr_faults,
        )
        close_graded_window(self.logger)
        await self.vw.stop()
        await self.pulses.stop()
        await self.out.stop()
        await self.out_rsp.stop()
        self.result_pass(TEST, seed, self.n_checks, f" counts={self.counts}")
