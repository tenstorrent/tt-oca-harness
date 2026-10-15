# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each covered IP interrupt sets only its own aggregator bit, and bridge faults set [40]/[42].

OCAH provenance: ``sep_irq_ip_to_aggregator_test`` and
``sep_irq_ip_to_aggregator_test_seq`` check each IP interrupt's aggregator-bit
mapping.

no_cpu: with the CPU held off, the host injects each covered IP interrupt via its real
INTR_TEST register and proves it propagates to the mapped bit of the
sep_internal_interrupts aggregate vector that feeds the VeeR PIC -- exercising the IP
`intr_o` -> aggregator wiring (sep.sv, `sep_internal_interrupts` aggregation block),
not merely that the IP raised its own status bit. HMAC error is Event-type (W1C). DMA done /
chunk / error are Status-type (INTR_TEST=0 deasserts). HMAC/KMAC fifo_empty
Status bits are idle-true and are not walked.

The aggregate vector has no frontdoor CSR mirror and the PIC is on the CPU bus
(unreachable with the CPU held off), so the test observes it through the tb_top
`sep_internal_interrupts_probe_o` observation-only XMR mirror. The IP-local INTR_STATE
RW1C contract is checked frontdoor over AXI.

Per source (CSRNG bits 23..26, EDN bits 27..28, HMAC error bit 19, DMA done /
chunk / error bits 8..10), the 3-phase check:
  CHK-BASE  clear INTR_TEST + W1C INTR_STATE -> aggregate bit reads 0
            (non-vacuity: a stuck-high aggregate bit fails here).
  CHK-SET   INTR_ENABLE + INTR_TEST -> aggregate bit reads 1 and INTR_STATE bit 1
            (proves INTR_TEST -> intr_o -> sep_internal_interrupts[idx]); a
            stuck-low / mis-wired aggregate bit fails here.
  CHK-ISO   while this source is asserted, the other mapped bits stay 0
            (one-hot aggregation -- catches an OR-network smear).
  CHK-CLR   Event: INTR_TEST=0 alone leaves the aggregate bit at 1 for
            _STICKY_HOLD clocks AND INTR_STATE bit 1 (the state is sticky); then
            W1C INTR_STATE -> aggregate bit returns 0 AND INTR_STATE bit 0.
            Status: INTR_TEST=0 -> the same two zeros (INTR_STATE is read-only).
            The slowest Status release must land inside _STICKY_HOLD, so the
            hold is long enough for a level-following state to drop in it.

Then one through-adapter SLVERR on the Secure DMA register hole and one on
each HMAC / KMAC / OTBN CSR gap:
  CHK-BUSERR-BASE   both STATUS words and aggregator [40]/[42] read 0
  CHK-BUSERR-DMA    DMA hole read is SLVERR; exclusive reg_path_err; [40]=1
  CHK-BUSERR-PERIPH each hole read is SLVERR; exclusive hmac / kmac / otbn; [42]=1
  CHK-BUSERR-CLR    each matching CLEAR write returns STATUS and the aggregator bit to 0
  CHK-BUSERR-DMA-WR a write to the DMA hole is BRESP SLVERR; exclusive
                    reg_path_err; [40]=1, then cleared (CHK-BUSERR-DMA-WR-CLR)

A beat past an adapter window is DECERR and never sets err_o. AES, CSRNG,
EDN and WDT windows are packed to the last register. This leaf does not
start a DMA transfer, so it does not prove host_path_err / bit 41.
Lockstep punch-through has no frontdoor.

INTR_TEST sets INTR_STATE regardless of IP functional state, so no entropy bring-
up is needed: +skip_fuse_sense, no_cpu.

Crypto interrupt-line leg (RANDCFG, after the body above). Ten sources: HMAC done and
error, KMAC done and error, the four CSRNG sources and the two EDN sources; vector bit
N-1 carries PIC source N (hw/sys/sep/doc/interrupts.adoc:23, :117-161). Each line is
INTR_STATE AND INTR_ENABLE, INTR_TEST sets a state bit, and the state bits clear on a
write of one (the INTR_* rows of
vendor/lowRISC/opentitan/overlay/regs/<ip>/regs/gen/adoc/<ip>.adoc). Every trial starts
with a block reset (SW_RESET_N bit 3 for HMAC, 4 for KMAC, 5 for CSRNG and EDN) and reads
INTR_STATE and INTR_ENABLE as 0. The seed draws the block order, the source order, the
order of the cells after the cell (1, 1), the masks and the flip order.
  CHK-INTR-BITWALK  each (state, enable) cell: the line equals state AND enable, no other
                    line of the block moves, and a write-one clear drops state and line
  CHK-INTR-FLIP     with the state set, the line follows each enable toggle both ways
  CHK-INTR-LINE     after INTR_TEST of mask T, INTR_STATE reads T and each line equals
                    state AND enable over a hold of 4 times t_rise
  CHK-INTR-CLEAR    a write-one clear of mask C leaves T AND NOT C and the lines follow
The leg grades only the cells the body above and the simultaneous fan-in test do not
walk; the other cells run as controls (CTRL-INTR-OPEN). t_rise is the clocks from the
INTR_TEST write response of the cell (1, 1) to the line high, logged per source.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import BitWatchTimeout, SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import pic
from sep_base_test import sep_base_test
from sep_reg_meta import CSRNG, EDN, HMAC, KMAC
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_irq_aggregator_seq import (
    DMA_CLEAR_ADDR,
    DMA_CLR_BIT,
    DMA_REG_PATH_BIT,
    DMA_STATUS_ADDR,
    IRQ_DMA_HOST_PATH,
    IRQ_DMA_REG_PATH,
    IRQ_PERIPH_OR,
    IRQ_TABLE,
    PERIPH_CLEAR_ADDR,
    PERIPH_STATUS_ADDR,
    IrqSrc,
    SepIrqIp,
    agg_from_pic,
    dma_reg_unmapped_addr,
    periph_holes,
)
from seq_lib.sep_irq_fanin_seq import FANIN_SOURCES
from seq_lib.sep_sw_reset_seq import SepSwReset

# Clocks an Event source must keep its aggregate bit at 1 after INTR_TEST=0
# and before the W1C. Every Status source in this bench must drop inside it.
_STICKY_HOLD = 32


# Crypto interrupt-line leg. The ten driven sources of HMAC, KMAC, CSRNG and EDN; vector bit
# = PIC source - 1 (hw/sys/sep/doc/interrupts.adoc:23, rows :117-161). The fifo_empty bits of
# HMAC and KMAC are not driven: every mask holds 0 there.
_KMAC_ERR = IrqSrc(
    "kmac_err",
    "KMAC",
    KMAC.field_lsb("INTR_STATE", "kmac_err"),
    agg_from_pic(pic("KMAC error")),
)
_BY_NAME = {s.name: s for s in (*FANIN_SOURCES, *IRQ_TABLE, _KMAC_ERR)}
LEG_BLOCKS: dict[str, tuple[IrqSrc, ...]] = {
    "hmac": (_BY_NAME["hmac_done"], _BY_NAME["hmac_err"]),
    "kmac": (_BY_NAME["kmac_done"], _KMAC_ERR),
    "csrng": tuple(s for s in IRQ_TABLE if s.ip == "CSRNG"),
    "edn": tuple(s for s in IRQ_TABLE if s.ip == "EDN"),
}
# Block reset: the SW_RESET_N bit of the block (TRNG for CSRNG and EDN), the gated-reset
# probe of the domain and its active level.
LEG_RESET = {
    "hmac": ("hmac", "hmac_gated_rst_n_probe_o", 0),
    "kmac": ("kmac", "kmac_gated_rst_n_probe_o", 0),
    "csrng": ("trng", "trng_reset_active_probe_o", 1),
    "edn": ("trng", "trng_reset_active_probe_o", 1),
}
LEG_BASELINE = 0x7E
_IP_BLOCK = {"hmac": HMAC, "kmac": KMAC, "csrng": CSRNG, "edn": EDN}
# Cells graded here. The other cells are controls: the cell (1, 1) and the write-one clear
# with the enable set of every source but kmac_err, and the cell (0, 0) of the seven
# sources of IRQ_TABLE, belong to the open owners.
_NEW_SOURCES = ("hmac_done", "kmac_done", "kmac_err")


def cell_graded(src: str, state: int, enable: int) -> bool:
    if (state, enable) in ((0, 1), (1, 0)):
        return True
    if (state, enable) == (0, 0):
        return src in _NEW_SOURCES
    return src == "kmac_err"


def w1c_graded(src: str, enable: int) -> bool:
    return enable == 0 or src == "kmac_err"


def _reg_mask(srcs: tuple[IrqSrc, ...], idx_mask: int) -> int:
    """Map a mask over the driven-bit index of a block to INTR_* register bits."""
    return sum(1 << s.test_bit for i, s in enumerate(srcs) if (idx_mask >> i) & 1)


@dataclass(frozen=True)
class MaskTrial:
    kind: str
    enable: int
    test: int
    clear: int
    flips: tuple[int, ...]
    """Register bits of the state bits left after the clear, in the drawn flip order."""


@dataclass(frozen=True)
class LegPlan:
    seed: int
    blocks: tuple[str, ...]
    sources: dict[str, tuple[str, ...]]
    cells: dict[str, tuple[tuple[int, int], ...]]
    trials: dict[str, tuple[MaskTrial, ...]]

    def summary(self) -> str:
        parts = [f"blocks={','.join(self.blocks)}"]
        for b in self.blocks:
            parts.append(f"{b}.src={','.join(self.sources[b])}")
            for t in self.trials[b]:
                parts.append(f"{b}.{t.kind}=E0x{t.enable:x}/T0x{t.test:x}/C0x{t.clear:x}")
        cells = " ".join(f"{n}:" + ",".join(f"{s}{e}" for s, e in c) for n, c in self.cells.items())
        return " ".join(parts) + " cells=" + cells


def _draw_mixed(rng: SepSeededRng, n: int) -> int:
    """A mask over n driven bits with at least one 0 and one 1."""
    full = (1 << n) - 1
    while True:
        v = rng.getrandbits(n)
        if v not in (0, full):
            return v


def _draw_clear(rng: SepSeededRng, n: int, test: int) -> int:
    """C != 0, and C shares a set bit with T when T has one."""
    while True:
        c = rng.getrandbits(n)
        if c and (test == 0 or c & test):
            return c


def draw_leg_plan(seed: int) -> LegPlan:
    """The plan of the leg, a pure function of the seed. Fixed draw order."""
    rng = SepSeededRng(seed)
    blocks = list(LEG_BLOCKS)
    rng.shuffle(blocks)
    sources: dict[str, tuple[str, ...]] = {}
    cells: dict[str, tuple[tuple[int, int], ...]] = {}
    trials: dict[str, tuple[MaskTrial, ...]] = {}
    for b in blocks:
        names = [s.name for s in LEG_BLOCKS[b]]
        rng.shuffle(names)
        sources[b] = tuple(names)
        for name in names:
            rest = [(0, 0), (0, 1), (1, 0)]
            rng.shuffle(rest)
            cells[name] = ((1, 1), *rest)
    for b in blocks:
        srcs = LEG_BLOCKS[b]
        n = len(srcs)
        full = (1 << n) - 1
        pairs = [
            ("drawn0", _draw_mixed(rng, n), _draw_mixed(rng, n)),
            ("drawn1", _draw_mixed(rng, n), _draw_mixed(rng, n)),
        ]
        bit = rng.randrange(n)
        others = [i for i in range(n) if i != bit]
        e_more = sum(1 << i for i in others if rng.getrandbits(1))
        t_more = sum(1 << i for i in others if not (e_more >> i) & 1 and rng.getrandbits(1))
        corners = [
            ("ones_ones", full, full),
            ("ones_zero", full, 0),
            ("zero_ones", 0, full),
            ("zero_zero", 0, 0),
            ("one_common", (1 << bit) | e_more, (1 << bit) | t_more),
        ]
        order = pairs + corners
        rng.shuffle(order)
        out = []
        for kind, e, t in order:
            c = _draw_clear(rng, n, t)
            left = [i for i in range(n) if (t & ~c) >> i & 1]
            rng.shuffle(left)
            out.append(
                MaskTrial(
                    kind,
                    _reg_mask(srcs, e),
                    _reg_mask(srcs, t),
                    _reg_mask(srcs, c),
                    tuple(srcs[i].test_bit for i in left),
                )
            )
        trials[b] = tuple(out)
    return LegPlan(seed, tuple(blocks), sources, cells, trials)


@pyuvm.test()
class sep_irq_ip_to_aggregator_test(sep_base_test):
    """CSRNG/EDN/HMAC/DMA INTR_TEST and bridge faults set only their own aggregator bit."""

    # The crypto interrupt-line leg grades these; the body before it keeps its asserts.
    required_evidence = ("CHK-INTR-LINE", "CHK-INTR-CLEAR", "CHK-INTR-FLIP", "CHK-INTR-BITWALK")

    async def _sample_agg_known(self, mask: int) -> int:
        """Sample the vector, requiring the bits in ``mask`` to be 0 or 1.

        One clock edge + ReadOnly per call. ``rd`` raises on an X/Z bit inside
        ``mask``, so ``bit == 0`` cannot hold for a bit nothing drives -- the
        risk on bit [41], a source this leaf never raises. Only the named bits
        are required to be known; the rest of the vector may legitimately be X.
        """
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        return self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, mask)

    async def _poll_agg(self, idx: int, expect: int, *, timeout: int = 200) -> tuple[bool, int]:
        sample = 0
        for _ in range(timeout):
            sample = await self._sample_agg_known(1 << idx)
            if ((sample >> idx) & 1) == expect:
                return True, sample
        return False, sample

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.irq = SepIrqIp(self)
        status_release_max = 0

        for src in IRQ_TABLE:
            # CHK-BASE: drive to a known-clear state and prove the aggregate bit is
            # low (a stuck-high bit would fail here -> the SET check is non-vacuous).
            await self.irq.stop_inject(src)
            await self.irq.clear_state(src)
            base_ok, base_vec = await self._poll_agg(src.agg_idx, 0)
            assert base_ok, (
                f"{src.name}: sep_internal_interrupts[{src.agg_idx}] not low at baseline"
            )
            self.logger.info(
                "STEP %s: INTR_TEST + INTR_STATE pre-cleared; aggregate bit[%d] "
                "baseline-low confirmed (vec=0x%08x)",
                src.name,
                src.agg_idx,
                base_vec,
            )

            # CHK-SET: enable then inject via INTR_TEST; the mapped aggregate bit must
            # go high and the IP's own INTR_STATE bit must set.
            await self.irq.enable(src)
            await self.irq.inject(src)
            self.logger.info(
                "STEP %s: interrupt enabled and INTR_TEST bit %d injected",
                src.name,
                src.test_bit,
            )
            set_ok, _ = await self._poll_agg(src.agg_idx, 1)
            assert set_ok, (
                f"{src.name}: INTR_TEST did not propagate to sep_internal_interrupts[{src.agg_idx}]"
            )
            assert await self.irq.read_state_bit(src) == 1, (
                f"{src.name}: INTR_STATE bit not set after INTR_TEST"
            )

            # CHK-ISO: from a single fresh sample (injection still active), only this
            # source's bit is set among the mapped sources -- one-hot aggregation,
            # catching an OR-network smear.
            iso_mask = 0
            for mapped in IRQ_TABLE:
                iso_mask |= 1 << mapped.agg_idx
            iso = await self._sample_agg_known(iso_mask)
            assert (iso >> src.agg_idx) & 1, (
                f"{src.name}: aggregate bit[{src.agg_idx}] dropped before isolation check"
            )
            for other in IRQ_TABLE:
                if other.agg_idx == src.agg_idx:
                    continue
                assert ((iso >> other.agg_idx) & 1) == 0, (
                    f"{src.name} asserted but sep_internal_interrupts[{other.agg_idx}] "
                    f"({other.name}) is also set -- aggregator smear (vec=0x{iso:08x})"
                )

            # CHK-CLR: Event sources W1C INTR_STATE; Status sources drop INTR_TEST.
            await self.irq.stop_inject(src)
            if src.kind == "event":
                # The INTR_TEST release alone must not clear an Event source,
                # so the W1C below is what the clear checks credit.
                for cyc in range(_STICKY_HOLD):
                    if await self._agg_bit(src.agg_idx) != 1:
                        raise AssertionError(
                            f"CHK-AGG FAIL: {src.name} sep_internal_interrupts"
                            f"[{src.agg_idx}] dropped {cyc} clocks after INTR_TEST=0 "
                            "with no W1C; Event state is not sticky"
                        )
                sticky_state = await self.irq.read_state_bit(src)
                assert sticky_state == 1, (
                    f"CHK-AGG FAIL: {src.name} INTR_STATE bit={sticky_state} after "
                    "INTR_TEST=0 with no W1C; Event state is not sticky"
                )
                self.logger.info(
                    "STEP %s: INTR_TEST=0 -> aggregate bit[%d] held 1 for %d clocks, "
                    "INTR_STATE bit=%d before W1C",
                    src.name,
                    src.agg_idx,
                    _STICKY_HOLD,
                    sticky_state,
                )
                await self.irq.clear_state(src)
                clr_ok, _ = await self._poll_agg(src.agg_idx, 0)
            else:
                clr_ok = False
                for cyc in range(1, 201):
                    if await self._agg_bit(src.agg_idx) == 0:
                        clr_ok = True
                        status_release_max = max(status_release_max, cyc)
                        break
            clr_how = "W1C clear" if src.kind == "event" else "INTR_TEST release"
            assert clr_ok, (
                f"{src.name}: sep_internal_interrupts[{src.agg_idx}] stuck after {clr_how}"
            )
            assert await self.irq.read_state_bit(src) == 0, (
                f"{src.name}: INTR_STATE bit not cleared by {clr_how}"
            )
            self.logger.info(
                "%s PASS: INTR_TEST -> sep_internal_interrupts[%d] 0->1->0 + "
                "%s + isolation (vec=0x%08x)",
                src.name,
                src.agg_idx,
                "INTR_STATE RW1C" if src.kind == "event" else "Status-type INTR_TEST release",
                iso,
            )

        assert 0 < status_release_max < _STICKY_HOLD, (
            f"CHK-AGG FAIL: slowest Status INTR_TEST release took {status_release_max} "
            f"clocks; the Event sticky hold of {_STICKY_HOLD} clocks must exceed it"
        )
        self.logger.info(
            "CHK-AGG PASS: all %d HMAC/DMA/CSRNG/EDN IRQs propagate to the aggregator, "
            "one-hot, with Event W1C (sticky for %d clocks after INTR_TEST=0) / "
            "Status INTR_TEST release (slowest %d clocks)",
            len(IRQ_TABLE),
            _STICKY_HOLD,
            status_release_max,
        )
        await self._check_bus_err_paths()
        await self._crypto_line_leg()

    async def _agg_bit(self, idx: int) -> int:
        return (await self._sample_agg_known(1 << idx) >> idx) & 1

    async def _check_bus_err_paths(self) -> None:
        dma_hole = dma_reg_unmapped_addr()
        holes = periph_holes()

        dma_st = await self.irq.read32(DMA_STATUS_ADDR)
        periph_st = await self.irq.read32(PERIPH_STATUS_ADDR)
        assert dma_st == 0, f"DMA_BUS_ERR_STATUS=0x{dma_st:x} at baseline, expected 0"
        assert periph_st == 0, f"PERIPH_BUS_ERR_STATUS=0x{periph_st:x} at baseline, expected 0"
        assert await self._agg_bit(IRQ_DMA_REG_PATH) == 0, (
            "sep_internal_interrupts[40] high before a DMA register-path fault"
        )
        assert await self._agg_bit(IRQ_PERIPH_OR) == 0, (
            "sep_internal_interrupts[42] high before a peripheral bridge fault"
        )
        self.logger.info("CHK-BUSERR-BASE PASS: DMA/PERIPH STATUS=0; aggregator [40]/[42]=0")

        await self.irq.read_expect_slverr(dma_hole)
        dma_st = await self.irq.read32(DMA_STATUS_ADDR)
        periph_st = await self.irq.read32(PERIPH_STATUS_ADDR)
        assert dma_st == DMA_REG_PATH_BIT, (
            f"DMA_BUS_ERR_STATUS=0x{dma_st:x} after 0x{dma_hole:08x}, "
            f"expected exclusive reg_path_err=0x{DMA_REG_PATH_BIT:x}"
        )
        assert periph_st == 0, (
            f"PERIPH_BUS_ERR_STATUS=0x{periph_st:x} after the DMA hole, expected 0"
        )
        dma_ok, dma_vec = await self._poll_agg(IRQ_DMA_REG_PATH, 1)
        assert dma_ok, (
            f"sep_internal_interrupts[{IRQ_DMA_REG_PATH}] stayed 0 after "
            f"DMA register-path SLVERR (vec=0x{dma_vec:x})"
        )
        # Exclusivity, not liveness: a register-path fault must not raise the
        # host-path or peripheral-OR source. Re-sampled with the two bits
        # required to be known -- this leaf never drives [41] high (see the
        # module docstring), so an undriven or X bit would otherwise satisfy
        # "== 0" on any RTL.
        excl_mask = (1 << IRQ_DMA_HOST_PATH) | (1 << IRQ_PERIPH_OR)
        excl_vec = await self._sample_agg_known(excl_mask)
        assert ((excl_vec >> IRQ_DMA_HOST_PATH) & 1) == 0, (
            "host-path bit [41] set on a register-path fault"
        )
        assert ((excl_vec >> IRQ_PERIPH_OR) & 1) == 0, (
            "periph OR [42] set on a DMA register-path fault"
        )
        self.logger.info(
            "CHK-BUSERR-DMA PASS: 0x%08x SLVERR; STATUS=0x%x exclusive; [40]=1",
            dma_hole,
            dma_st,
        )

        # DMA_BUS_ERR_CLEAR is sw=w singlepulse and always reads 0, so its read
        # value is not a contract the DUT can fail. The clear is proven by the
        # STATUS bit and the aggregator bit going back to 0 below.
        await self.irq.write32(DMA_CLEAR_ADDR, DMA_CLR_BIT)
        dma_st = await self.irq.read32(DMA_STATUS_ADDR)
        assert dma_st == 0, f"DMA_BUS_ERR_STATUS=0x{dma_st:x} after CLEAR, expected 0"
        clr_ok, _ = await self._poll_agg(IRQ_DMA_REG_PATH, 0)
        assert clr_ok, "sep_internal_interrupts[40] stuck after DMA_BUS_ERR_CLEAR"
        self.logger.info("CHK-BUSERR-CLR PASS: DMA_BUS_ERR_CLEAR; STATUS=0; [40]=0")

        # The read leg above walks TL_GET_REQ/GET_ACK. A write to the same hole
        # walks the TL_PUT_REQ/PUT_ACK/AXI_B_RESP states of axi_lite_to_tlul.sv, a
        # separate FSM arm with its own opcode select, and raises the sticky
        # error from BRESP rather than RRESP.
        await self.irq.write_expect_slverr(dma_hole, 0xA5A5_1234)
        dma_st = await self.irq.read32(DMA_STATUS_ADDR)
        periph_st = await self.irq.read32(PERIPH_STATUS_ADDR)
        assert dma_st == DMA_REG_PATH_BIT, (
            f"DMA_BUS_ERR_STATUS=0x{dma_st:x} after a write to 0x{dma_hole:08x}, "
            f"expected exclusive reg_path_err=0x{DMA_REG_PATH_BIT:x}"
        )
        assert periph_st == 0, (
            f"PERIPH_BUS_ERR_STATUS=0x{periph_st:x} after the DMA write hole, expected 0"
        )
        wr_ok, wr_vec = await self._poll_agg(IRQ_DMA_REG_PATH, 1)
        assert wr_ok, (
            f"sep_internal_interrupts[{IRQ_DMA_REG_PATH}] stayed 0 after a DMA "
            f"register-path write SLVERR (vec=0x{wr_vec:x})"
        )
        excl_vec = await self._sample_agg_known(excl_mask)
        assert ((excl_vec >> IRQ_DMA_HOST_PATH) & 1) == 0, (
            "host-path bit [41] set on a register-path write fault"
        )
        assert ((excl_vec >> IRQ_PERIPH_OR) & 1) == 0, (
            "periph OR [42] set on a DMA register-path write fault"
        )
        self.logger.info(
            "CHK-BUSERR-DMA-WR PASS: write 0x%08x BRESP=SLVERR; STATUS=0x%x exclusive; [40]=1",
            dma_hole,
            dma_st,
        )

        await self.irq.write32(DMA_CLEAR_ADDR, DMA_CLR_BIT)
        dma_st = await self.irq.read32(DMA_STATUS_ADDR)
        assert dma_st == 0, (
            f"DMA_BUS_ERR_STATUS=0x{dma_st:x} after CLEAR of the write fault, expected 0"
        )
        clr_ok, _ = await self._poll_agg(IRQ_DMA_REG_PATH, 0)
        assert clr_ok, "sep_internal_interrupts[40] stuck after clearing the write fault"
        self.logger.info("CHK-BUSERR-DMA-WR-CLR PASS: STATUS=0; [40]=0")

        for hole in holes:
            await self.irq.read_expect_slverr(hole.addr)
            periph_st = await self.irq.read32(PERIPH_STATUS_ADDR)
            dma_st = await self.irq.read32(DMA_STATUS_ADDR)
            assert periph_st == hole.status_bit, (
                f"PERIPH_BUS_ERR_STATUS=0x{periph_st:x} after 0x{hole.addr:08x}, "
                f"expected exclusive {hole.name}=0x{hole.status_bit:x}"
            )
            assert dma_st == 0, (
                f"DMA_BUS_ERR_STATUS=0x{dma_st:x} after the {hole.name} hole, expected 0"
            )
            per_ok, per_vec = await self._poll_agg(IRQ_PERIPH_OR, 1)
            assert per_ok, (
                f"sep_internal_interrupts[{IRQ_PERIPH_OR}] stayed 0 after "
                f"{hole.name} adapter SLVERR (vec=0x{per_vec:x})"
            )
            excl = await self._sample_agg_known(1 << IRQ_DMA_REG_PATH)
            assert ((excl >> IRQ_DMA_REG_PATH) & 1) == 0, (
                f"DMA register-path [40] set on a {hole.name} bridge fault"
            )
            self.logger.info(
                "CHK-BUSERR-PERIPH PASS: %s 0x%08x SLVERR; STATUS=0x%x exclusive; [42]=1",
                hole.name,
                hole.addr,
                periph_st,
            )

            await self.irq.write32(PERIPH_CLEAR_ADDR, hole.clear_bit)
            periph_st = await self.irq.read32(PERIPH_STATUS_ADDR)
            assert periph_st == 0, (
                f"PERIPH_BUS_ERR_STATUS=0x{periph_st:x} after {hole.name} CLEAR, expected 0"
            )
            clr_ok, _ = await self._poll_agg(IRQ_PERIPH_OR, 0)
            assert clr_ok, (
                f"sep_internal_interrupts[42] stuck after PERIPH_BUS_ERR_CLEAR.{hole.name}"
            )
            self.logger.info(
                "CHK-BUSERR-CLR PASS: PERIPH_BUS_ERR_CLEAR.%s; STATUS=0; [42]=0",
                hole.name,
            )

    # ---- Crypto interrupt-line leg -------------------------------------------------------
    # Outer limits of the clean-time measurements of the leg; never a contract.
    _LEG_RESET_BOUND = 2_000
    _LEG_OKAY_TRIES = 200
    _LEG_RISE_BOUND = 1_000

    async def _crypto_line_leg(self) -> None:
        """INTR_STATE AND INTR_ENABLE drives each crypto line; INTR_TEST sets; W1C clears.

        Spec: hw/sys/sep/doc/interrupts.adoc:23 (bit i is PIC source i+1) and :117-161;
        the INTR_STATE, INTR_ENABLE and INTR_TEST rows of
        vendor/lowRISC/opentitan/overlay/regs/{hmac,kmac,csrng,edn}/regs/gen/adoc/*.adoc.
        Every trial starts from a block reset. The graded FCOV window opens at the first
        write of a trial and closes before each block reset.
        """
        dut = cocotb.top
        seed = self.random_seed()
        plan = draw_leg_plan(seed)
        self.chk = SepChkLog(self, "sep_irq_ip_to_aggregator_test", seed)
        self.swrst = SepSwReset(self)
        self.swrst.value = LEG_BASELINE
        await self.swrst.release()
        readback = await self.swrst.read_back()
        self.chk.ctrl("INTR-BASELINE", readback == LEG_BASELINE, sw_reset_n=f"0x{readback:02x}")
        self.logger.info("PLAN seed=%d %s", seed, plan.summary())

        self.vec = SepBitWatch(
            dut.sep_internal_interrupts_probe_o,
            {s.name: s.agg_idx for blk in LEG_BLOCKS.values() for s in blk},
            name="sep_internal_interrupts",
        ).start()
        self.t_rise: dict[str, int | None] = {}

        for block in plan.blocks:
            for name in plan.sources[block]:
                for state, enable in plan.cells[name]:
                    await self._leg_cell(block, _BY_NAME[name], state, enable)
                self.chk.ctrl(
                    "INTR-CELL11",
                    self.t_rise.get(name) is not None,
                    block=block,
                    src=name,
                    t_rise=self.t_rise.get(name),
                )
        for block in plan.blocks:
            for trial in plan.trials[block]:
                await self._leg_mask_trial(block, trial)

        close_graded_window(self.logger)
        self.swrst.value = LEG_BASELINE
        await self.swrst.release()
        await self.vec.stop()
        self.chk.finish()

    @staticmethod
    def _leg_field_mask(block: str, reg: str) -> int:
        rb = _IP_BLOCK[block]
        return rb.mask32(reg) if hasattr(rb, "mask32") else rb.mask(reg)

    async def _leg_block_reset(self, block: str) -> tuple[int, int]:
        """Reset the domain of ``block``; return INTR_STATE and INTR_ENABLE after it."""
        close_graded_window(self.logger)
        dut = cocotb.top
        eng, probe, active = LEG_RESET[block]
        sig = getattr(dut, probe)
        await self.swrst.park(eng)
        for _ in range(self._LEG_RESET_BOUND):
            if self.rd(sig) == active:
                break
            await ClockCycles(dut.clk_i, 1)
        else:
            raise AssertionError(
                f"{probe} did not go active within {self._LEG_RESET_BOUND} clocks ({block})"
            )
        await self.swrst.release(eng)
        for _ in range(self._LEG_RESET_BOUND):
            if self.rd(sig) != active:
                break
            await ClockCycles(dut.clk_i, 1)
        else:
            raise AssertionError(
                f"{probe} did not release within {self._LEG_RESET_BOUND} clocks ({block})"
            )
        src0 = LEG_BLOCKS[block][0]
        for _ in range(self._LEG_OKAY_TRIES):
            seq = SepAxiAccessSeq(
                "irq_state_okay",
                op=SepAxiOp.READ,
                addr=src0.state_addr,
                size=2,
                allow_ungraded_read_resp=True,
            )
            await self.start_seq(seq)
            if seq.resp_ok:
                break
            await ClockCycles(dut.clk_i, 10)
        else:
            raise AssertionError(
                f"{block} INTR_STATE not OKAY within {self._LEG_OKAY_TRIES} reads after reset"
            )
        # A read with an X or Z bit raises in the AXI master (4-state simulators).
        state = await self.irq.read32(src0.state_addr)
        enable = await self.irq.read32(src0.enable_addr)
        return state, enable

    def _leg_base_ok(self, block: str, state: int, enable: int) -> bool:
        srcs = LEG_BLOCKS[block]
        drv = _reg_mask(srcs, (1 << len(srcs)) - 1)
        return (state & drv) == 0 and (enable & self._leg_field_mask(block, "INTR_ENABLE")) == 0

    def _leg_hold(self, *names: str) -> int:
        """t_rise of the sources (largest), at least 1 clock, logged with each check."""
        return max([1] + [self.t_rise.get(n) or 0 for n in names])

    async def _leg_settle(self, name: str, level: int, bound: int, hold: int):
        """Wait (bounded) for the line to read ``level``, then require it to hold."""
        m = self.vec.mark()
        try:
            await self.vec.wait_level(level, bound, name)
        except BitWatchTimeout:
            return False, "timeout"
        t = self.vec.clk - m.clk
        m2 = self.vec.mark()
        await ClockCycles(cocotb.top.clk_i, hold)
        stable = self.vec.rises_since(m2, name) == 0 and not self.vec.fall_clks_since(m2, name)
        return stable and self.vec.level(name) == level, t

    def _leg_still(self, mark, names) -> bool:
        """No edge on any of ``names`` since ``mark``."""
        return all(
            self.vec.rises_since(mark, n) == 0 and not self.vec.fall_clks_since(mark, n)
            for n in names
        )

    def _leg_vec(self, block: str) -> int:
        """The lines of the block at the last sample, in INTR_* register bit positions."""
        return sum((self.vec.level(s.name) or 0) << s.test_bit for s in LEG_BLOCKS[block])

    async def _leg_cell(self, block: str, src: IrqSrc, state: int, enable: int) -> None:
        dut = cocotb.top
        srcs = LEG_BLOCKS[block]
        drv = _reg_mask(srcs, (1 << len(srcs)) - 1)
        others = [s.name for s in srcs if s is not src]
        bit = 1 << src.test_bit
        st0, en0 = await self._leg_block_reset(block)
        base_ok = self._leg_base_ok(block, st0, en0)
        base_lv = {n: self.vec.level(n) for n in others}

        m0 = self.vec.mark()
        open_graded_window("sep_irq_ip_to_aggregator_test", self.logger)
        if enable:
            await self.irq.write32(src.enable_addr, bit)
        if state:
            await self.irq.write32(src.test_addr, bit)
        m1 = self.vec.mark()
        high_at_resp = self.vec.level(src.name)
        st = await self.irq.read32(src.state_addr)
        expect = state & enable
        if (state, enable) == (1, 1):
            t_rise: int | None = 0
            if high_at_resp != 1:
                try:
                    t_rise = await self.vec.wait_rise(m1, self._LEG_RISE_BOUND, src.name) - m1.clk
                except BitWatchTimeout:
                    t_rise = None
            self.t_rise[src.name] = t_rise
            self.chk.obs(
                "INTR-TRISE",
                src=src.name,
                t_rise="timeout" if t_rise is None else t_rise,
                bound=self._LEG_RISE_BOUND,
            )
        hold = 4 * self._leg_hold(src.name)
        await ClockCycles(dut.clk_i, hold)
        if expect:
            line_ok = (
                self.t_rise.get(src.name) is not None
                and self.vec.level(src.name) == 1
                and not self.vec.fall_clks_since(m1, src.name)
            )
        else:
            line_ok = self.vec.high_clocks_since(m0, src.name) == 0
        others_ok = self._leg_still(m0, others) and all(
            self.vec.level(n) == base_lv[n] for n in others
        )
        state_ok = (st & drv) == (bit if state else 0)
        fields = dict(
            block=block,
            src=src.name,
            bit=src.test_bit,
            cell=f"{state}{enable}",
            state=f"0x{st & drv:x}",
            vec=self.vec.level(src.name),
            others_unchanged=int(others_ok),
            baseline_ok=int(base_ok),
            baseline_x=0,
            undriven=f"0x{st & ~drv:x}",
            hold=hold,
            w1c="n/a",
        )
        ok = base_ok and line_ok and others_ok and state_ok
        if cell_graded(src.name, state, enable):
            self.chk.ok("INTR-BITWALK", ok, **fields)
        else:
            self.chk.ctrl("INTR-OPEN", ok, **fields)
        if not state:
            return

        await self._leg_flip(block, src, bit if enable else 0)

        pre = await self.irq.read32(src.state_addr)
        self.chk.ctrl(
            "INTR-W1C-PRE", bool(pre & bit), block=block, src=src.name, state=f"0x{pre:x}"
        )
        tr = self._leg_hold(src.name)
        await self.irq.write32(src.state_addr, bit)
        st2 = await self.irq.read32(src.state_addr)
        low_ok, t = await self._leg_settle(src.name, 0, 8 * tr, 4 * tr)
        others_ok = self._leg_still(m0, others) and all(
            self.vec.level(n) == base_lv[n] for n in others
        )
        ok = low_ok and others_ok and not (st2 & bit)
        fields.update(
            state=f"0x{st2 & drv:x}",
            vec=self.vec.level(src.name),
            others_unchanged=int(others_ok),
            w1c=enable,
            t_fall=t,
            bound=8 * tr,
            hold=4 * tr,
        )
        if w1c_graded(src.name, enable):
            self.chk.ok("INTR-BITWALK", ok, **fields)
        else:
            self.chk.ctrl("INTR-OPEN", ok, **fields)

    async def _leg_flip(self, block: str, src: IrqSrc, enable_reg: int) -> None:
        """Toggle the enable bit of ``src`` (state 1) and back; the line follows each write."""
        bit = 1 << src.test_bit
        tr = self._leg_hold(src.name)
        for new_reg in (enable_reg ^ bit, enable_reg):
            new_en = int(bool(new_reg & bit))
            m = self.vec.mark()
            await self.irq.write32(src.enable_addr, new_reg)
            ok, t = await self._leg_settle(src.name, new_en, 8 * tr, 4 * tr)
            self.chk.ok(
                "INTR-FLIP",
                ok,
                block=block,
                src=src.name,
                bit=src.test_bit,
                enable=new_en,
                vec=self.vec.level(src.name),
                t=t,
                bound=8 * tr,
                hold=4 * tr,
            )
            if new_en:
                self.chk.ctrl(
                    "INTR-FLIP-RISE",
                    self.vec.rises_since(m, src.name) > 0,
                    block=block,
                    src=src.name,
                    bit=src.test_bit,
                )

    async def _leg_mask_trial(self, block: str, trial: MaskTrial) -> None:
        dut = cocotb.top
        srcs = LEG_BLOCKS[block]
        src0 = srcs[0]
        drv = _reg_mask(srcs, (1 << len(srcs)) - 1)
        st0, en0 = await self._leg_block_reset(block)
        self.chk.ctrl(
            "INTR-RESET-CLEAN",
            self._leg_base_ok(block, st0, en0),
            block=block,
            trial=trial.kind,
            state=f"0x{st0:x}",
            enable=f"0x{en0:x}",
        )
        tr = self._leg_hold(*(s.name for s in srcs))
        m0 = self.vec.mark()
        open_graded_window("sep_irq_ip_to_aggregator_test", self.logger)
        await self.irq.write32(src0.enable_addr, trial.enable)
        await self.irq.write32(src0.test_addr, trial.test)
        st = await self.irq.read32(src0.state_addr) & drv
        expect = st & trial.enable
        rise_ok = True
        for s in srcs:
            if expect >> s.test_bit & 1:
                try:
                    await self.vec.wait_level(1, 8 * tr, s.name)
                except BitWatchTimeout:
                    rise_ok = False
        m2 = self.vec.mark()
        await ClockCycles(dut.clk_i, 4 * tr)
        bits_ok = all(
            (self.vec.level(s.name) == 1 and self._leg_still(m2, [s.name]))
            if expect >> s.test_bit & 1
            else self.vec.high_clocks_since(m0, s.name) == 0
            for s in srcs
        )
        vec = self._leg_vec(block)
        self.chk.ok(
            "INTR-LINE",
            rise_ok and bits_ok and st == trial.test,
            block=block,
            trial=trial.kind,
            enable=f"0x{trial.enable:x}",
            test=f"0x{trial.test:x}",
            state=f"0x{st:x}",
            vec=f"0x{vec:x}",
            expect=f"0x{expect:x}",
            bound=8 * tr,
            hold=4 * tr,
        )
        self.chk.ctrl(
            "INTR-LINE-CAUSE",
            all(self.t_rise.get(s.name) is not None for s in srcs),
            block=block,
            trial=trial.kind,
        )

        # Write-one clear of C. The LINE read above shows the bits of C that are set.
        self.chk.ctrl(
            "INTR-CLEAR-PRE",
            (st & trial.clear) == (trial.test & trial.clear),
            block=block,
            trial=trial.kind,
            clear=f"0x{trial.clear:x}",
            state=f"0x{st:x}",
        )
        mc = self.vec.mark()
        await self.irq.write32(src0.state_addr, trial.clear)
        st2 = await self.irq.read32(src0.state_addr) & drv
        expect2 = st2 & trial.enable
        fall_ok = True
        for s in srcs:
            if (expect >> s.test_bit & 1) and not (expect2 >> s.test_bit & 1):
                try:
                    await self.vec.wait_level(0, 8 * tr, s.name)
                except BitWatchTimeout:
                    fall_ok = False
        m3 = self.vec.mark()
        await ClockCycles(dut.clk_i, 4 * tr)
        bits_ok = all(
            self.vec.level(s.name) == (expect2 >> s.test_bit & 1)
            and self._leg_still(m3, [s.name])
            and self.vec.rises_since(mc, s.name) == 0
            for s in srcs
        )
        vec2 = self._leg_vec(block)
        self.chk.ok(
            "INTR-CLEAR",
            fall_ok and bits_ok and st2 == (trial.test & ~trial.clear & drv),
            block=block,
            trial=trial.kind,
            clear=f"0x{trial.clear:x}",
            state=f"0x{st2:x}",
            expect=f"0x{trial.test & ~trial.clear & drv:x}",
            vec=f"0x{vec2:x}",
            bound=8 * tr,
            hold=4 * tr,
        )

        by_bit = {s.test_bit: s for s in srcs}
        for b in trial.flips:
            await self._leg_flip(block, by_bit[b], trial.enable)
