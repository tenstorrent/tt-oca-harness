# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC alias remap in front of the iDMA manager: source remap, destination remap, shared table.

Spec: hw/sys/smc/doc/fabric.adoc, the "DMA Controller" row of the master table (alias remap, then
filtering, then the destination) and "Alias Remapping" (transparent at reset);
hw/ip/axi_alias_remap/regs/alias_remap.rdl (REGION_START / REGION_END non-inclusive, REGION_ATTRS
offset added to address bits [55:12], valid); hw/sys/smc/doc/dma.adoc (a read of NEXT_ID_0 submits
the programmed copy, DONE_0 reports the id).

The JTAG2AXI bridge programs the iDMA and the alias regions. The bench responder behind
smu_axi_out holds the bytes and a passive tap of the outbound interface captures the address
phases of each copy. The same copy runs three times: with every region at reset, with a region
over the source page, and with a region over the destination page.

S1 setup, S2 copy with every region at reset, S3 source remap, S4 destination remap, S5 shared
table observation, S6 bounded waits.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_alias_priority_overflow_test_seq import (
    _ATTRS,
    _END,
    _START,
    ADDR_MASK56,
    LOW_MASK,
    OFFSET_BM,
    PAGE,
    VALID_BM,
    _OutboundTap,
    _region_reg,
)
from seq_lib.smu_axi_out_addr_len_size_test_seq import (
    DMA_CONFIG,
    DMA_CONFIG_ENABLE_ND,
    DMA_DONE_0,
    DMA_DONE_POLLS,
    DMA_DST_HI,
    DMA_DST_LO,
    DMA_DST_STRIDE_HI,
    DMA_DST_STRIDE_LO,
    DMA_LEN_HI,
    DMA_LEN_LO,
    DMA_NEXT_ID_0,
    DMA_POLL_CYCLES,
    DMA_REPS_HI,
    DMA_REPS_LO,
    DMA_SRC_HI,
    DMA_SRC_LO,
    DMA_SRC_STRIDE_HI,
    DMA_SRC_STRIDE_LO,
)
from seq_lib.smu_filter_helpers import (
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    PASS_ALL_END,
    PASS_RW_CONFIG,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

# Source and destination pages outside the SMC and SEP apertures (hw/sys/smu/doc/index.adoc
# "AXI Crossbar"); X' and D' are the pages the regions map them to.
PAGE_X = 0x0200_0000
PAGE_D = 0x0300_0000
# Region offsets in bytes added to bits [55:12] (alias_remap.rdl REGION_ATTRS offset).
OFFSET_X = 0x0200_0000
OFFSET_D = 0x0200_0000
PAGE_X_ALIAS = PAGE_X + OFFSET_X
PAGE_D_ALIAS = PAGE_D + OFFSET_D
# Alias region indices (hw/sys/smc/regs/gen/c/smc_addr.h, eight regions).
REGION_SRC = 0
REGION_DST = 1
# hw/sys/smc/doc/dma.adoc: the copy moves LENGTH bytes from SRC_ADDRESS to DST_ADDRESS.
COPY_LENGTH = 64
# Eight-byte words repeated over the copy; the three values are distinct and non-zero.
WORD_PX = 0x1111_2222_3333_4444
WORD_PY = 0x5555_6666_7777_8888
WORD_D0 = 0x9999_AAAA_BBBB_CCCC
# A bridge write through the destination region, one 8-byte word inside the page.
SHARED_LOW_BITS = 0x200
SHARED_DATA = 0x0123_4567_89AB_CDEF

J2A_POLL_LIMIT = 128
OUT_OBS_BOUND_CYCLES = 2000
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
ACCESS_STEPS = ("S2", "S3", "S4", "S5")


def _words(word: int) -> bytes:
    return word.to_bytes(8, "little") * (COPY_LENGTH // 8)


def _span(phases: list[tuple], base: int) -> tuple[int, int]:
    """Bytes the phases cover inside [base, base + PAGE), and the phases outside that page."""
    inside = sum((p[1] + 1) << p[2] for p in phases if base <= p[0] < base + PAGE)
    outside = sum(1 for p in phases if not base <= p[0] < base + PAGE)
    return inside, outside


class smu_alias_dma_manager_test_seq:
    """One iDMA copy through no region, a source region and a destination region."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.clk = self.dut.clk_smu_i
        self.jtag = None
        self.tap = None
        self.step = "S1"
        self.step_ts: dict[str, float] = {}
        self.step_access = {s: 0 for s in STEPS}
        self.j2a = 0
        self.j2a_last = "none"
        self.j2a_expired = 0
        self.dma_polls_max = 0
        self.dma_count = 0
        self.dma_last = "none"
        self.dma_expired = 0
        self.obs_used_max = 0
        self.obs_count = 0
        self.obs_last = "none"
        self.obs_expired = 0

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.step = step
        self.step_ts[step] = get_sim_time("ns")
        self._log(f"STEP {step}: {text}")

    def _chk(self, sb, chk: str, name: str, observed, expected, text: str) -> None:
        self._log(f"{chk}: {text} observed={observed} expected={expected}")
        sb.expect_eq(f"{chk} {name}", observed, expected, evidence=chk)

    async def _j2a(self, write: bool, addr: int, data: int = 0, **kw):
        kind = "WR" if write else "RD"
        try:
            if write:
                status, raw = await jtag2axi_single_write(
                    self.jtag,
                    addr,
                    data,
                    poll_limit=J2A_POLL_LIMIT,
                    require_complete=True,
                    **kw,
                )
            else:
                status, raw = await jtag2axi_single_read(
                    self.jtag, addr, poll_limit=J2A_POLL_LIMIT, require_complete=True, **kw
                )
        except TimeoutError as exc:
            self.j2a_expired += 1
            self.j2a_last = f"EXPIRED {exc}"
            self._log(f"TIMEOUT-PATH j2a: bound={J2A_POLL_LIMIT} polls EXPIRED last={exc}")
            raise
        require_jtag_tdo_resolved(f"J2A {kind} @0x{addr:x}")
        self.j2a += 1
        self.step_access[self.step] += 1
        self.j2a_last = f"{kind} @0x{addr:x} status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A {kind} @0x{addr:x} status={status}")
        return int(raw)

    async def _wr32(self, addr: int, value: int) -> None:
        word = int(value) & 0xFFFF_FFFF
        packed, wstrb = (word << 32, 0xF0) if addr & 0x4 else (word, 0x0F)
        await self._j2a(True, addr, packed, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B)

    async def _rd32(self, addr: int) -> int:
        raw = await self._j2a(False, addr, size=SMC_DBG_AXSIZE_4B)
        return (raw >> 32) & 0xFFFF_FFFF if addr & 0x4 else raw & 0xFFFF_FFFF

    async def _region(self, idx: int, start: int, offset: int, valid: bool) -> None:
        values = (
            (_START, start & ADDR_MASK56 & ~LOW_MASK),
            (_END, (start + PAGE) & ADDR_MASK56 & ~LOW_MASK),
            (_ATTRS, (offset & OFFSET_BM) | (VALID_BM if valid else 0)),
        )
        for reg, value in values:
            await self._j2a(True, _region_reg(reg, idx), value)
        self._log(
            f"CELL region {idx} start=0x{start:x} offset=0x{offset:x} valid={int(valid)} "
            f"j2a_accesses={self.j2a}"
        )

    async def _program_copy(self) -> None:
        await self._wr32(DMA_CONFIG, DMA_CONFIG_ENABLE_ND)
        for addr, value in (
            (DMA_DST_LO, PAGE_D & 0xFFFF_FFFF),
            (DMA_DST_HI, PAGE_D >> 32),
            (DMA_SRC_LO, PAGE_X & 0xFFFF_FFFF),
            (DMA_SRC_HI, PAGE_X >> 32),
            (DMA_LEN_LO, COPY_LENGTH),
            (DMA_LEN_HI, 0),
            (DMA_DST_STRIDE_LO, 0),
            (DMA_DST_STRIDE_HI, 0),
            (DMA_SRC_STRIDE_LO, 0),
            (DMA_SRC_STRIDE_HI, 0),
            (DMA_REPS_LO, 1),
            (DMA_REPS_HI, 0),
        ):
            await self._wr32(addr, value)

    async def _copy(self, tag: str):
        """Submit the programmed copy; return (done, id, AW phases, AR phases)."""
        mark = self.tap.mark()
        start_id = await self._rd32(DMA_NEXT_ID_0)
        done, used = None, 0
        for used in range(1, DMA_DONE_POLLS + 1):
            await ClockCycles(self.clk, DMA_POLL_CYCLES)
            done = await self._rd32(DMA_DONE_0)
            if done == start_id:
                break
        else:
            self.dma_expired += 1
            self.dma_last = f"EXPIRED {tag} id={start_id} done={done} after {used} polls"
            raise AssertionError(self.dma_last)
        self.dma_count += 1
        self.dma_polls_max = max(self.dma_polls_max, used)
        self.dma_last = f"{tag} id={start_id} done={done} polls={used}"
        aw, ar = self.tap.since(mark)
        self._log(
            f"CELL copy {tag} id={start_id} done={done} polls={used} "
            f"aw={[(hex(p[0]), p[1], p[2]) for p in aw]} ar={[(hex(p[0]), p[1], p[2]) for p in ar]}"
        )
        return done, start_id, aw, ar

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut
        await self._mark("S1", "SETUP: TAP, JTAG2AXI gate, patterns at X, X', D and D'")
        await self.cfg.reset_done.wait()
        await ClockCycles(self.clk, 16)
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        self.tap = _OutboundTap(dut)
        try:
            await self._body(sb)
        finally:
            self.tap.stop()

    async def _body(self, sb) -> None:
        mem = self.cfg.axi_out_mem
        px, py, d0 = _words(WORD_PX), _words(WORD_PY), _words(WORD_D0)
        mem.write(PAGE_X, px)
        mem.write(PAGE_X_ALIAS, py)
        mem.write(PAGE_D, d0)
        mem.write(PAGE_D_ALIAS, d0)
        for reg, value in (
            (OUTBOUND0_START, 0),
            (OUTBOUND0_END, PASS_ALL_END),
            (OUTBOUND0_FILTER_CONFIG, PASS_RW_CONFIG),
        ):
            await self._j2a(True, reg, value)
        await self._program_copy()
        self._log(
            f"CELL setup seed={getattr(cocotb, 'RANDOM_SEED', 'na')} X=0x{PAGE_X:x} "
            f"X'=0x{PAGE_X_ALIAS:x} D=0x{PAGE_D:x} D'=0x{PAGE_D_ALIAS:x} length={COPY_LENGTH}"
        )

        await self._mark("S2", "copy X to D with every alias region at reset")
        done, cid, aw, ar = await self._copy("no region")
        got_d = mem.read(PAGE_D, COPY_LENGTH)
        ar_x = _span(ar, PAGE_X)
        self._chk(
            sb,
            "CHK-ALIASDMA-NOREGION-PLACE",
            "with no valid region D holds PX and the AR phases cover X",
            (done == cid, got_d.hex(), ar_x),
            (True, px.hex(), (COPY_LENGTH, 0)),
            f"id={cid} done={done} D={got_d.hex()} PX={px.hex()} AR bytes at X and AR phases "
            f"elsewhere={ar_x}",
        )

        await self._mark("S3", "region 0 valid over X with offset OFFX; the same copy")
        await self._region(REGION_SRC, PAGE_X, OFFSET_X, True)
        done, cid, aw, ar = await self._copy("source remap")
        got_d = mem.read(PAGE_D, COPY_LENGTH)
        ar_alias = _span(ar, PAGE_X_ALIAS)
        ar_plain = _span(ar, PAGE_X)[0]
        self._chk(
            sb,
            "CHK-ALIASDMA-SRC",
            "D holds PY and the AR phases cover X' and never X",
            (done == cid, got_d.hex(), ar_alias, ar_plain, got_d != px),
            (True, py.hex(), (COPY_LENGTH, 0), 0, True),
            f"id={cid} done={done} D={got_d.hex()} PY={py.hex()} AR bytes at X' and AR phases "
            f"elsewhere={ar_alias} AR bytes at X={ar_plain}",
        )

        await self._mark(
            "S4", "region 0 invalid, region 1 valid over D with offset OFFD; same copy"
        )
        await self._j2a(True, _region_reg(_ATTRS, REGION_SRC), OFFSET_X & OFFSET_BM)
        self._log(f"CELL region {REGION_SRC} invalid offset=0x{OFFSET_X:x} j2a_accesses={self.j2a}")
        await self._region(REGION_DST, PAGE_D, OFFSET_D, True)
        done, cid, aw, ar = await self._copy("destination remap")
        got_d = mem.read(PAGE_D, COPY_LENGTH)
        got_alias = mem.read(PAGE_D_ALIAS, COPY_LENGTH)
        aw_alias = _span(aw, PAGE_D_ALIAS)
        aw_plain = _span(aw, PAGE_D)[0]
        self._chk(
            sb,
            "CHK-ALIASDMA-DST",
            "D' holds PX while D keeps PY and the AW phases cover D' and never D",
            (done == cid, got_alias.hex(), got_d.hex(), aw_alias, aw_plain, got_d != px),
            (True, px.hex(), py.hex(), (COPY_LENGTH, 0), 0, True),
            f"id={cid} done={done} D'={got_alias.hex()} PX={px.hex()} D={got_d.hex()} "
            f"PY={py.hex()} AW bytes at D' and AW phases elsewhere={aw_alias} AW bytes at D="
            f"{aw_plain} D0={d0.hex()}",
        )

        await self._mark(
            "S5", "bridge write at D while region 1 is valid; shared table observation"
        )
        shared_issued = PAGE_D + SHARED_LOW_BITS
        mark = self.tap.mark()
        await self._j2a(True, shared_issued, SHARED_DATA)
        used = 0
        shared_aw: list[tuple] = []
        while used < OUT_OBS_BOUND_CYCLES:
            shared_aw = self.tap.since(mark)[0]
            if shared_aw:
                break
            await RisingEdge(self.clk)
            used += 1
        self.obs_count += 1
        self.obs_used_max = max(self.obs_used_max, used)
        self.obs_last = f"shared write waited={used} cycles seen={len(shared_aw)}"
        if not shared_aw:
            self.obs_expired += 1
            self.obs_last = f"EXPIRED shared write after {used} cycles"
            raise AssertionError("shared write: no AW on smu_axi_out")
        leaving = shared_aw[0][0]
        dma_dst = aw[0][0] if aw else -1
        held = mem.read_int(leaving, 8)
        self._log(
            f"OBSERVATION shared table: iDMA destination leaving=0x{dma_dst:x} "
            f"bridge write issued=0x{shared_issued:x} leaving=0x{leaving:x} held=0x{held:x} "
            "measured and logged only"
        )
        self._chk(
            sb,
            "CHK-ALIASDMA-SHARED-TABLE",
            "the iDMA destination address and the bridge write address are both captured",
            (dma_dst >= 0, bool(shared_aw)),
            (True, True),
            f"dma_dst=0x{dma_dst:x} bridge_leaving=0x{leaving:x} (measured and logged only)",
        )

        await self._mark("S6", "TIMEOUT: bounded waits and last state")
        self._timeout_paths(sb)
        await ClockCycles(self.clk, 2)
        self.step_ts["PASS"] = get_sim_time("ns")
        order = [*STEPS, "PASS"]
        stamps = " ".join(f"{k}={self.step_ts[k]:.0f}ns" for k in order)
        counts = " ".join(f"{s}={self.step_access[s]}" for s in STEPS)
        increasing = all(self.step_ts[b] > self.step_ts[a] for a, b in zip(order, order[1:]))
        every_step = all(self.step_access[s] > 0 for s in ACCESS_STEPS)
        self._log(f"CHK-NONVAC: ordered fence {'<'.join(order)} {stamps}; j2a accesses {counts}")
        self._chk(
            sb,
            "CHK-NONVAC",
            "ordered fence",
            (increasing, every_step),
            (True, True),
            f"stamps strictly increase to the pass point, the un-remapped copy precedes both "
            f"remapped copies, S2..S5 each count an access, total {self.j2a}",
        )

    def _timeout_paths(self, sb) -> None:
        self._log(
            f"TIMEOUT-PATH j2a: bound={J2A_POLL_LIMIT} polls used: not measured "
            f"count={self.j2a} expired={self.j2a_expired} last={self.j2a_last}"
        )
        self._log(
            f"TIMEOUT-PATH dma_done: bound={DMA_DONE_POLLS} polls max_used={self.dma_polls_max} "
            f"count={self.dma_count} expired={self.dma_expired} last={self.dma_last}"
        )
        self._log(
            f"TIMEOUT-PATH out_obs: bound={OUT_OBS_BOUND_CYCLES} clk max_used={self.obs_used_max} "
            f"count={self.obs_count} expired={self.obs_expired} last={self.obs_last}"
        )
        expired = self.j2a_expired + self.dma_expired + self.obs_expired
        finite = all(0 < b < 10**9 for b in (J2A_POLL_LIMIT, DMA_DONE_POLLS, OUT_OBS_BOUND_CYCLES))
        self._chk(
            sb,
            "CHK-TIMEOUT-PATHS",
            "bounded waits",
            (expired, finite, bool(self.j2a_last), bool(self.dma_last), bool(self.obs_last)),
            (0, True, True, True, True),
            f"sites=3 expired={expired} j2a_accesses={self.j2a} copies={self.dma_count}",
        )
