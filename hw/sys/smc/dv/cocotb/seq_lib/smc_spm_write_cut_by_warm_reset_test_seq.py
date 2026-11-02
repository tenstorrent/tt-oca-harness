# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An SPM write cut by a watchdog warm reset is answered once the reset releases.

Reproducer for #3510. `cpu.adoc` (CPU AXI Isolation) says each cluster port is
drained before a reset takes effect; the same document (Reset-Domain Crossing)
says a watchdog timeout is followed by a cold reset. The issue leaves open which
of the two bounds the warm reset alone: either the boundary drains or answers an
SPM access cut by a watchdog warm reset, or `cpu.adoc` states that SPM access
after a watchdog warm reset requires the following cold reset. This leaf grades
the first reading, so it fails while the boundary stays unanswering and passes
the day the RTL or the document settles it the other way (the leaf then leaves
`rtl_issue`).

The arm leg writes and reads back an SPM burst over SEP_IN and writes
`CPU_CTRL.SCRATCH[0]` with the AXI ID the cut write uses, so the path and the
ID are known live. The defect leg issues an SPM write burst from SEP_IN, waits
for its AW handshake at the port and for the L2-frontend isolate's pending
write count to rise from 0 (the burst is inside the cluster, its B not
returned), then holds `tb_sep_wdt_reset_n` low, which `smc_reset_ctrl.sv`
folds into the warm reset, so the entry does not depend on the watchdog
register path. No primary reset follows. Graded after the release: the cut
write receives a B response (any code) within a bounded wait, a fresh SPM write
with the same AXI ID bits [2:0] completes OKAY, and a `CPU_CTRL` write with that
ID completes OKAY. Writes with other ID bits are recorded, not graded.

The handshakes are counted at the SEP_IN port by ID, so a B the bench
attributes to the cut write and one it attributes to a later write of the same
ID are both visible in the kept log.
"""

from __future__ import annotations

from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, with_timeout
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import SPM_MEMORY_BASE, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

CHK = "CHK-SPM-WRITE-CUT-BY-WARM-RESET"
ARM = "CHK-SPM-WRITE-CUT-BY-WARM-RESET-ARM"
OBS = "OBS-SPM-WRITE-CUT-BY-WARM-RESET"
FUSE_SENSE_MAX_CYCLES = 200_000
# clk_smc_i rises from the cut write's start to its AW handshake and the isolate's pending rise.
ISSUE_BOUND_CYCLES = 256
ASSERT_BOUND_CYCLES = 300
HOLD_CYCLES = 512
RELEASE_BOUND_CYCLES = 20_000
POST_RELEASE_CYCLES = 200
# clk_smc_i rises after the release in which the cut write's B must arrive.
CUT_B_BOUND_CYCLES = 8_000
# The cut item's own driver bound; it spans the reset and the post-release wait.
CUT_TIMEOUT_NS = 100_000
JOIN_NS = CUT_TIMEOUT_NS + 20_000
BOUNDED_NS = 5_000
SPM_BEATS = 16
SPM_WORD = 8
SPM_ARM_ADDR = SPM_MEMORY_BASE + 0x8000
SPM_CUT_ADDR = SPM_MEMORY_BASE + 0x9000
SPM_FRESH_ADDR = SPM_MEMORY_BASE + 0xA000
SPM_OTHER_ADDR = SPM_MEMORY_BASE + 0xB000
# Bits [2:0] of the two IDs differ; the front-port demux buckets writes by them.
CUT_ID = 0x5
OTHER_ID = 0x2
SCRATCH_PATTERN = 0x5CA7_C0DE
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}


def _burst_pattern(addr: int) -> int:
    return int.from_bytes(bytes((addr + i) & 0xFF for i in range(SPM_WORD * SPM_BEATS)), "little")


class _WritePortMonitor:
    """SEP_IN AW and B handshakes per ID and the L2-frontend isolate's pending write count,
    sampled at `clk_smc_i` rises."""

    def __init__(self) -> None:
        self.aw: Counter[int] = Counter()
        self.b: Counter[int] = Counter()
        self.pending = 0

    def start(self) -> None:
        cocotb.start_soon(self._run())

    @staticmethod
    def _hs(dut, valid: str, ready: str) -> bool:
        sigs = [getattr(dut, n).value for n in (valid, ready)]
        return all(v.is_resolvable and int(v) for v in sigs)

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            if self._hs(dut, "s_axi_awvalid", "s_axi_awready"):
                self.aw[int(dut.s_axi_awid.value)] += 1
            if self._hs(dut, "s_axi_bvalid", "s_axi_bready"):
                self.b[int(dut.s_axi_bid.value)] += 1
            value = dut.tb_cpu_l2_pending_aw.value
            self.pending = int(value) if value.is_resolvable else -1


class smc_spm_write_cut_by_warm_reset_test_seq(SmcCsrSeq):
    """Cut an SPM write burst with the watchdog warm reset, release it, then grade the port."""

    def __init__(self, name: str = "smc_spm_write_cut_by_warm_reset_test_seq") -> None:
        super().__init__(name)
        self.mon = _WritePortMonitor()

    def _item(
        self,
        name: str,
        op: SmcSysAxiOp,
        addr: int,
        axi_id: int | None,
        beats: int = 1,
        wdata: int = 0,
        timeout_ns: int | None = None,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(name)
        item.op = op
        item.addr = addr
        item.length = SPM_WORD
        item.beats = beats
        item.wdata = wdata
        item.axi_id = axi_id
        if timeout_ns is not None:
            item.allow_error = True
            item.allow_timeout = True
            item.allow_reset_abort = True
            item.timeout_ns = timeout_ns
        return item

    async def _strict(self, item: SmcSysAxiItem) -> SmcSysAxiItem:
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == 0, f"{item.get_name()}@0x{item.addr:x}: response {item.resp_code}"
        return item

    @staticmethod
    def _result(item: SmcSysAxiItem) -> str:
        if item.timed_out:
            return "TIMEOUT"
        return _RESP_NAMES.get(item.resp_code, str(item.resp_code))

    async def _bounded_write(self, name: str, addr: int, axi_id: int) -> tuple[str, int]:
        """Bounded one-beat write; returns the driver's result and the B handshakes of its ID."""
        item = self._item(name, SmcSysAxiOp.WRITE, addr, axi_id, wdata=addr, timeout_ns=BOUNDED_NS)
        b0 = self.mon.b[axi_id]
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.bounded_accesses += 1
        if item.timed_out:
            self.timeouts += 1
        got = self.mon.b[axi_id] - b0
        cocotb.log.info(
            "%s %s addr=0x%x id=0x%x result=%s b_hs=+%d pending_aw=%d",
            OBS,
            name,
            addr,
            axi_id,
            self._result(item),
            got,
            self.mon.pending,
        )
        return self._result(item), got

    async def _first_level(self, sig, want: int, bound: int) -> int | None:
        clk = cocotb.top.clk_smc_i
        for i in range(bound):
            await RisingEdge(clk)
            if sig.value.is_resolvable and int(sig.value) == want:
                return i + 1
        return None

    async def _arm(self, scratch: int) -> None:
        wdata = _burst_pattern(SPM_ARM_ADDR)
        await self._strict(
            self._item("arm_spm_wr", SmcSysAxiOp.WRITE, SPM_ARM_ADDR, None, SPM_BEATS, wdata)
        )
        rd = await self._strict(
            self._item("arm_spm_rd", SmcSysAxiOp.READ, SPM_ARM_ADDR, None, SPM_BEATS)
        )
        assert rd.rdata == wdata, f"SPM readback 0x{rd.rdata:x}, wrote 0x{wdata:x}"
        await self._strict(
            self._item("arm_ctrl_wr", SmcSysAxiOp.WRITE, scratch, CUT_ID, wdata=SCRATCH_PATTERN)
        )
        rb = await self._strict(self._item("arm_ctrl_rd", SmcSysAxiOp.READ, scratch, CUT_ID))
        assert rb.rdata == SCRATCH_PATTERN, f"SCRATCH[0] reads 0x{rb.rdata:x}"
        cocotb.log.info(
            "%s PASS: SPM burst of %d beats written and read back OKAY at 0x%x, "
            "CPU_CTRL.SCRATCH[0] written and read back OKAY with id=0x%x; aw_hs id=0x%x %d, "
            "b_hs id=0x%x %d, pending_aw=%d",
            ARM,
            SPM_BEATS,
            SPM_ARM_ADDR,
            CUT_ID,
            CUT_ID,
            self.mon.aw[CUT_ID],
            CUT_ID,
            self.mon.b[CUT_ID],
            self.mon.pending,
        )

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i
        scratch = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)
        for name in (
            "tb_sep_wdt_reset_n",
            "tb_rst_warm_smc_clk_n",
            "tb_cpu_l2_pending_aw",
            "s_axi_awid",
            "s_axi_bid",
        ):
            assert hasattr(dut, name), f"tb_top has no {name}"

        self.mon.start()
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        await ClockCycles(clk, 16)
        assert int(dut.tb_sep_wdt_reset_n.value) == 1, "SEP WDT reset input not idle high"
        assert int(dut.tb_rst_warm_smc_clk_n.value) == 1, "warm reset asserted after boot"

        await self._arm(scratch)

        settle = await self._first_level(dut.tb_cpu_l2_pending_aw, 0, ISSUE_BOUND_CYCLES)
        assert settle is not None, f"pending_aw {self.mon.pending} after the arm leg"
        cut = self._item(
            "cut_spm_wr",
            SmcSysAxiOp.WRITE,
            SPM_CUT_ADDR,
            CUT_ID,
            SPM_BEATS,
            _burst_pattern(SPM_CUT_ADDR),
            CUT_TIMEOUT_NS,
        )
        aw0, b0 = self.mon.aw[CUT_ID], self.mon.b[CUT_ID]
        task = cocotb.start_soon(_OneShot(cut, "cut_os").start(self.sequencer))
        for issue in range(1, ISSUE_BOUND_CYCLES + 1):
            await RisingEdge(clk)
            if self.mon.aw[CUT_ID] > aw0 and self.mon.pending > 0:
                break
        else:
            raise AssertionError(
                f"the cut write was not issued into the cluster within {ISSUE_BOUND_CYCLES} "
                f"clk_smc_i rises: aw_hs +{self.mon.aw[CUT_ID] - aw0} pending_aw={self.mon.pending}"
            )
        dut.tb_sep_wdt_reset_n.value = 0
        cut_aw = self.mon.aw[CUT_ID] - aw0
        pending_at_assert = self.mon.pending
        b_at_assert = self.mon.b[CUT_ID] - b0
        assert b_at_assert == 0, (
            f"the cut write's B arrived {b_at_assert} time(s) before the reset was asserted; "
            f"the burst was not cut"
        )
        fall = await self._first_level(dut.tb_rst_warm_smc_clk_n, 0, ASSERT_BOUND_CYCLES)
        assert fall is not None, (
            f"rst_warm_smc_clk_n still 1 {ASSERT_BOUND_CYCLES} cycles after the SEP WDT reset "
            f"input fell"
        )
        b_at_fall = self.mon.b[CUT_ID] - b0
        await ClockCycles(clk, HOLD_CYCLES)
        pending_in_reset = self.mon.pending
        assert int(dut.tb_rst_warm_smc_clk_n.value) == 0, "warm reset released during the hold"
        dut.tb_sep_wdt_reset_n.value = 1
        released = await self._first_level(dut.tb_rst_warm_smc_clk_n, 1, RELEASE_BOUND_CYCLES)
        assert released is not None, (
            f"rst_warm_smc_clk_n still 0 {RELEASE_BOUND_CYCLES} cycles after the SEP WDT reset "
            f"input rose"
        )
        assert int(dut.rst_primary_smc_clk_no.value) == 1, (
            "primary reset asserted by the warm reset"
        )
        await ClockCycles(clk, POST_RELEASE_CYCLES)
        cocotb.log.info(
            "%s cut: aw_hs id=0x%x +%d after %d clk_smc_i, b_hs +%d at the assertion, +%d at the "
            "warm reset fall (%d cycles later), pending_aw %d at the assertion, %d in reset, "
            "released after %d cycles",
            OBS,
            CUT_ID,
            cut_aw,
            issue,
            b_at_assert,
            b_at_fall,
            fall,
            pending_at_assert,
            pending_in_reset,
            released,
        )

        cut_b_cycles = None
        for n in range(1, CUT_B_BOUND_CYCLES + 1):
            await RisingEdge(clk)
            if self.mon.b[CUT_ID] > b0:
                cut_b_cycles = n
                break
        cut_b = self.mon.b[CUT_ID] - b0
        pending_after = self.mon.pending
        await with_timeout(task, JOIN_NS, "ns")
        cocotb.log.info(
            "%s cut after the release: b_hs id=0x%x +%d (%s of %d clk_smc_i), driver result "
            "%s, pending_aw=%d",
            OBS,
            CUT_ID,
            cut_b,
            "none within" if cut_b_cycles is None else f"after {cut_b_cycles}",
            CUT_B_BOUND_CYCLES,
            self._result(cut),
            pending_after,
        )

        fresh_spm, fresh_spm_b = await self._bounded_write("fresh_spm_wr", SPM_FRESH_ADDR, CUT_ID)
        fresh_ctrl, fresh_ctrl_b = await self._bounded_write("fresh_ctrl_wr", scratch, CUT_ID)
        await self._bounded_write("other_spm_wr", SPM_OTHER_ADDR, OTHER_ID)
        await self._bounded_write("other_ctrl_wr", scratch, OTHER_ID)

        summary = (
            f"cut write id=0x{CUT_ID:x}: aw_hs {cut_aw}, b_hs {cut_b} within "
            f"{CUT_B_BOUND_CYCLES} clk_smc_i after the release (driver {self._result(cut)}); "
            f"fresh SPM write id=0x{CUT_ID:x}: {fresh_spm}, b_hs {fresh_spm_b}; CPU_CTRL write "
            f"id=0x{CUT_ID:x}: {fresh_ctrl}, b_hs {fresh_ctrl_b}; pending_aw {pending_at_assert} "
            f"at the assertion, {pending_in_reset} in reset, {pending_after} after the release, "
            f"{self.mon.pending} at the end"
        )
        failed = [
            name
            for name, bad in (
                ("the cut write got no B", cut_b == 0),
                ("the fresh SPM write did not complete OKAY", fresh_spm != "OKAY"),
                ("the CPU_CTRL write did not complete OKAY", fresh_ctrl != "OKAY"),
            )
            if bad
        ]
        if failed:
            raise AssertionError(
                f"{CHK} FAIL: after the watchdog warm reset released {'; '.join(failed)}; {summary}"
            )
        cocotb.log.info(
            "%s PASS: the cut write was answered and the later writes completed OKAY after the "
            "release; %s",
            CHK,
            summary,
        )
