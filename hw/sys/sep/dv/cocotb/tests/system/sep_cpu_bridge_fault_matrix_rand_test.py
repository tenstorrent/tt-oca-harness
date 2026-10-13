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

Randomization (``SepSeededRng`` from the run seed): the block order of hmac,
kmac and otbn, the sweep order, the hole offset of each block, the
read-or-write choice of each re-fault, the clear order of bits 0 to 6, the 1
to 3 clear masks (each with at least two set bits, one of them the bit of an
unlatched block), the re-trigger blocks, the DMA source address inside the
fixed outbound window and the copy size.

Checkers:
  CHK-CTRL        status 0 after reset and after legal reads; vector 40..42 0.
  CHK-RESP        a hole write answers SLVERR.
  CHK-LATCH       PERIPH_BUS_ERR_STATUS equals the faulted set.
  CHK-OR          vector bit 42 equals (status != 0).
  CHK-CLR-MATRIX  a clear bit clears only its own block (seven bits + drain).
  CHK-NONVAC      each matrix and mask step starts with at least two bits.
  CHK-MASK        a mask clear gives the faulted set AND NOT mask.
  CHK-AGAIN       a cleared block re-latches; a re-fault keeps the other bits.
  CHK-CLR-READ0   both clear registers read 0 with both status registers set.
  CHK-DMA-CLR     write 0 keeps, write 1 clears both, no cross-set.
  CHK-HOST        a SLVERR DMA source read latches host_path_err alone.
  CHK-RACE        a same-cycle fault and clear leaves the latch set.

The expected latch set of CHK-CLR-MATRIX and CHK-MASK, before and after each
clear, is the set of faults the leaf drove minus the bits it cleared, never a
status read.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_filter_model import FilterEntry
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import HMAC, KMAC, OTBN, SEP_CPU_CTRL, sym
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
RESP_OKAY, RESP_SLVERR = 0, 2
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

    def draw_lines(self) -> list[str]:
        return [
            f"block_order={','.join(self.block_order)} sweep_order={','.join(self.sweep_order)}",
            "holes=" + ",".join(f"{b}:0x{self.hole[b]:08x}" for b in BLOCKS),
            "clear_order=" + ",".join(PERIPH_BITS[i] for i in self.clear_order),
            "masks=" + ",".join(f"0x{m:02x}" for m in self.masks),
            f"retrigger clear={self.retrig_clear} still_set={self.retrig_set}",
            f"dma_src=0x{self.dma_src:08x} dma_size={self.dma_size}",
            "refault_ops=" + "".join("r" if o == "rd" else "w" for o in self.refault_ops),
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
        "CHK-RESP",
        "CHK-LATCH",
        "CHK-OR",
        "CHK-CLR-MATRIX",
        "CHK-NONVAC",
        "CHK-MASK",
        "CHK-AGAIN",
        "CHK-CLR-READ0",
        "CHK-DMA-CLR",
        "CHK-HOST",
        "CHK-RACE",
    )

    # ---- log helpers -----------------------------------------------------------
    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.c.seed, line)
        self.n_checks += 1
        self.counts[chk] = self.counts.get(chk, 0) + 1

    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.c.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _ctrl_missing(self, line: str) -> None:
        msg = f"CTRL-MISSING seed={self.c.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    # ---- accesses ----------------------------------------------------------------
    async def _acc(self, op: SepAxiOp, addr: int, data: int = 0) -> tuple[int, int]:
        kw = {"op": op, "addr": addr, "length": 4, "size": 2}
        if op is SepAxiOp.READ:
            kw["allow_ungraded_read_resp"] = True
        else:
            kw["wdata"] = data & 0xFFFF_FFFF
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

    async def _wr_ok(self, addr: int, v: int) -> None:
        resp, _ = await self._acc(SepAxiOp.WRITE, addr, v)
        if resp != RESP_OKAY:
            raise AssertionError(f"write 0x{addr:08x} answered {RESP_NAME.get(resp, resp)}")

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
                msg = f"CTL-RESP FAIL {line} expect=SLVERR"
                self.logger.error(msg)
                raise AssertionError(msg)
            self.logger.info("CTL-RESP LOG %s", line)
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
            field_compare(p, 0, PERIPH_MASK),
            field_compare(d, 0, DMA_MASK),
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

    async def _leg_latch(self) -> None:
        resps = []
        for b in self.c.block_order:
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

    async def _dma_reg_fault(self) -> tuple[int, int]:
        resp, _ = await self._acc(SepAxiOp.READ, dma_reg_unmapped_addr())
        self.logger.info(
            "CTL-RESP LOG seed=%d block=dma_reg op=rd addr=0x%08x resp=%s",
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
            "CTL-LATCH LOG seed=%d block=dma_reg resp=%s dma_status=0x%x vec40=%d",
            self.c.seed,
            RESP_NAME.get(resp, resp),
            d & DMA_MASK,
            self._b(vec, 40),
        )
        if resp != RESP_SLVERR or (d & DMA_MASK) != DMA_REG_PATH_BIT or self._b(vec, 40) != 1:
            self._ctrl_missing(
                f"CTL-LATCH dma_reg set-up resp={resp} dma_status=0x{d:x} vec40={self._b(vec, 40)}"
            )
        open_graded_window(TEST, self.logger)
        p = await self._periph()
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
        # Register-path write of 0, then the write of 1 (the control).
        await self._wr_ok(DMA_CLEAR_ADDR, 0)
        d0 = await self._dma()
        v0 = await self._vec()
        line = (
            f"write0=still_set reg_path_err={int(bool(d0 & DMA_REG_PATH_BIT))} "
            f"vec40={self._b(v0, 40)} dma_status=0x{d0 & DMA_MASK:x}"
        )
        if (d0 & DMA_MASK) != DMA_REG_PATH_BIT or self._b(v0, 40) != 1:
            self._fail("CHK-DMA-CLR", line)
        self._pass("CHK-DMA-CLR", line)
        close_graded_window(self.logger)
        await self._wr_ok(DMA_CLEAR_ADDR, 1)
        d1 = await self._dma()
        v1 = await self._vec()
        self.logger.info(
            "CTL-DMA-CLR LOG seed=%d write1=reg_path_clear reg_path_err=%d vec40=%d",
            self.c.seed,
            int(bool(d1 & DMA_REG_PATH_BIT)),
            self._b(v1, 40),
        )
        if d1 & DMA_REG_PATH_BIT or self._b(v1, 40):
            self._ctrl_missing(f"CTL-DMA-CLR write of 1 did not clear: dma_status=0x{d1:x}")
        open_graded_window(TEST, self.logger)
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
        await self._wr_ok(PERIPH_CLEAR_ADDR, bits)
        self.latched &= ~bits
        exp_after = self.latched & PERIPH_MASK
        after = await self._periph()
        vec = await self._vec()
        fb = field_compare(before, exp_before, PERIPH_MASK)
        fc = field_compare(after, exp_after, PERIPH_MASK)
        text = (
            f"before=0x{before & PERIPH_MASK:02x} exp_before=0x{exp_before:02x} "
            f"after=0x{after & PERIPH_MASK:02x} exp_after=0x{exp_after:02x} "
            f"vec42={self._b(vec, 42)} [{fc.fields()}]"
        )
        ok = fb.ok and fc.ok and self._b(vec, 42) == int(bool(exp_after))
        return text, ok

    async def _clear_step(self, chk: str, bits: int, tag: str) -> None:
        exp_before = self.latched & PERIPH_MASK
        nb = bin(exp_before).count("1")
        nv = f"step={tag} latched_before=0x{exp_before:02x} bits={nb}"
        if nb < 2:
            self._fail("CHK-NONVAC", nv)
        self._pass("CHK-NONVAC", nv)
        text, ok = await self._clear_write(bits)
        line = f"{tag} {text}"
        if not ok:
            self._fail(chk, line)
        self._pass(chk, line)

    async def _leg_matrix(self) -> None:
        for i in self.c.clear_order:
            await self._restore_full()
            twin = "latched" if PERIPH_BITS[i] in BLOCKS else "unlatched_twin=latched_bits"
            await self._clear_step("CHK-CLR-MATRIX", 1 << i, f"cleared={PERIPH_BITS[i]} {twin}")
        # Drain to zero, one latched bit at a time in the clear order.
        await self._restore_full()
        order = [i for i in self.c.clear_order if PERIPH_BITS[i] in BLOCKS]
        for k, i in enumerate(order):
            text, ok = await self._clear_write(1 << i)
            line = f"drain={k + 1}/{len(order)} cleared={PERIPH_BITS[i]} {text}"
            if not ok:
                self._fail("CHK-CLR-MATRIX", line)
            self._pass("CHK-CLR-MATRIX", line)

    async def _leg_masks(self) -> None:
        for k, mk in enumerate(self.c.masks):
            await self._restore_full()
            await self._clear_step("CHK-MASK", mk, f"step={k + 1} mask=0x{mk:02x}")

    async def _leg_again(self) -> None:
        c = self.c
        await self._restore_full()
        b = c.retrig_clear
        await self._wr_ok(PERIPH_CLEAR_ADDR, BIT[b])
        self.latched &= ~BIT[b]
        mid = await self._periph()
        await self._fault(b, self._next_op())
        after = await self._periph()
        others = after & ~BIT[b] & PERIPH_MASK
        exp_others = self.latched & ~BIT[b]
        line = (
            f"block={b} relatched={int(bool(after & BIT[b]))} others_kept=0x{others:02x} "
            f"cleared_status=0x{mid & PERIPH_MASK:02x} after=0x{after & PERIPH_MASK:02x}"
        )
        if mid & BIT[b] or not after & BIT[b] or others != exp_others:
            self._fail("CHK-AGAIN", line)
        self._pass("CHK-AGAIN", line)
        b2 = c.retrig_set
        before = await self._periph()
        await self._fault(b2, self._next_op())
        after = await self._periph()
        line = (
            f"block={b2} still_set=1 before=0x{before & PERIPH_MASK:02x} "
            f"after=0x{after & PERIPH_MASK:02x} others_kept=0x{after & ~BIT[b2] & PERIPH_MASK:02x}"
        )
        if not before & BIT[b2] or (after & PERIPH_MASK) != (before & PERIPH_MASK):
            self._fail("CHK-AGAIN", line)
        self._pass("CHK-AGAIN", line)

    # ---- DMA host path -------------------------------------------------------------
    async def _idle_check(self, tag: str) -> None:
        st = await self.dma.read_status()
        if st.raw & (ST_BUSY | ST_ERROR):
            self._ctrl_missing(f"DMA idle check {tag}: {st.fmt()}")

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
        await self._wr_ok(DMA_CLEAR_ADDR, 1)
        d = await self._dma()
        if d & DMA_MASK:
            self._ctrl_missing(f"DMA_BUS_ERR_STATUS=0x{d:x} after clear before the copy")
        close_graded_window(self.logger)
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
        await self._idle_check("before host copy")
        open_graded_window(TEST, self.logger)
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

        # Host-path clear cells.
        before = d & DMA_MASK
        await self._wr_ok(DMA_CLEAR_ADDR, 0)
        a0 = await self._dma()
        await self._wr_ok(DMA_CLEAR_ADDR, 1)
        a1 = await self._dma()
        v1 = await self._vec()
        line = (
            f"cell=host_only before=0x{before:x} after_write0=0x{a0 & DMA_MASK:x} "
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
        await self._w1c_error()
        await self._idle_check("before second host copy")
        st2, _, slv2 = await self._failing_copy(c.dma_size)
        if not st2.error or not slv2:
            self._fail("CHK-DMA-CLR", f"cell=both set-up copy: {st2.fmt()} slverr_reads={slv2}")
        await self._dma_reg_fault()
        before = (await self._dma()) & DMA_MASK
        await self._wr_ok(DMA_CLEAR_ADDR, 0)
        a0 = await self._dma()
        await self._wr_ok(DMA_CLEAR_ADDR, 1)
        a1 = await self._dma()
        v1 = await self._vec()
        line = (
            f"cell=both before=0x{before:x} after_write0=0x{a0 & DMA_MASK:x} "
            f"after_write1=0x{a1 & DMA_MASK:x} vec40={self._b(v1, 40)} vec41={self._b(v1, 41)}"
        )
        both = DMA_HOST_PATH_BIT | DMA_REG_PATH_BIT
        if (
            before != both
            or (a0 & DMA_MASK) != both
            or a1 & DMA_MASK
            or self._b(v1, 40)
            or self._b(v1, 41)
        ):
            self._fail("CHK-DMA-CLR", line)
        self._pass("CHK-DMA-CLR", line)
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
                "RACE-TRIAL LOG seed=%d kind=periph block=%s trial=%d offset=%d fault_clks=%s "
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
                st = await self._periph()
                vec = await self._vec()
                later = [s for s in self.pulses.clocks(mk, sb) if s > coin[0]]
                self.latched = st & PERIPH_MASK
                line = (
                    f"kind=periph block={b} coincident=1 later_faults={len(later)} "
                    f"status_after=0x{st & PERIPH_MASK:02x} vec42={self._b(vec, 42)} "
                    f"offset={d} trials={trial} clk={coin[0]}"
                )
                if later or not st & BIT[b] or self._b(vec, 42) != 1:
                    self._fail("CHK-RACE", line)
                self._pass("CHK-RACE", line)
                return
            st = await self._periph()
            self.latched = st & PERIPH_MASK
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
                "RACE-TRIAL LOG seed=%d kind=dma trial=%d offset=%d fault_clks=%s clear_clks=%s "
                "error=%d",
                self.c.seed,
                trial,
                d,
                sets,
                clrs,
                s2.error,
            )
            if coin:
                dst_ = await self._dma()
                vec = await self._vec()
                later = [s for s in self.pulses.clocks(mk, sb) if s > coin[0]]
                line = (
                    f"kind=dma coincident=1 later_faults={len(later)} "
                    f"status_after=0x{dst_ & DMA_MASK:02x} vec41={self._b(vec, 41)} offset={d} "
                    f"trials={trial} clk={coin[0]}"
                )
                if later or not dst_ & DMA_HOST_PATH_BIT or self._b(vec, 41) != 1:
                    self._fail("CHK-RACE", line)
                self._pass("CHK-RACE", line)
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
        self.op_i = 0
        self.latched = 0
        self.ctrl_reg_path_err = 0
        self.logger.info("SEED seed=%d", seed)
        for d in c.draw_lines():
            self.logger.info("DRAW %s", d)
        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        self.dma = SepDmaOps(self)
        self.obank = SepFilterBank(self, "out")
        self.out = SepFabricTap("PR-OUT").start()
        self.out_rsp = SepFabricTap("PR-OUT-RSP").start()
        self.pulses = _PulseRec().start()
        self._go_word = control_word(go=1, initial=1)

        open_graded_window(TEST, self.logger)
        await self._leg_ctrl()
        await self._leg_latch()
        await self._leg_dma_reg()
        await self._leg_matrix()
        await self._leg_masks()
        await self._leg_again()
        await self._leg_host()
        for b in c.sweep_order:
            await self._race_periph(b)
        await self._race_dma()
        close_graded_window(self.logger)
        await self.pulses.stop()
        await self.out.stop()
        await self.out_rsp.stop()
        self.logger.info(
            "RESULT %s seed=%d PASS checks=%d counts=%s", TEST, seed, self.n_checks, self.counts
        )
