# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVS_CFG_0 round trip through the AVSBus CDC bridge at one peripheral clock period.

Contract SMC_CLOCK_SRC_005, anchor smc_periph_floor_roundtrip_test.
Scenarios: CSRC-PERIPH-FLOOR.S1, CSRC-PERIPH-FLOOR.S2, CSRC-PERIPH-FLOOR.S3.
Spec: clk_rst.adoc (Peripheral Timing Requirements), avsbus_controller memmap.adoc (AVS_CFG_0).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_avsbus_protocol_utils import AVS_CFG_0, avs_field
from .smc_csr_seq_utils import SmcCsrSeq

MAX_RETRIES_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_0__MAX_RETRIES_bm")
MAX_RETRIES_BP = avs_field("AVSBUS_CONTROLLER__AVS_CFG_0__MAX_RETRIES_bp")
RESYNC_INTERVAL_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_0__RESYNC_INTERVAL_bm")
RESYNC_INTERVAL_BP = avs_field("AVSBUS_CONTROLLER__AVS_CFG_0__RESYNC_INTERVAL_bp")

MAX_RETRIES_WRITTEN = 0x2A
MEASURE_EDGES = 64
ACCESS_TIMEOUT_NS = 50_000
EDGE_TIMEOUT_NS = 100_000
OKAY = 0

FENCE_TERMS = (
    "CELL_PERIODS_MEASURED",
    "AVS_CFG_0_SAVED",
    "AVS_CFG_0_WRITTEN",
    "AVS_CFG_0_READ_BACK",
    "AVS_CFG_0_RESTORED",
)
CHECKER_TERM = "CHK-PERIPH-FLOOR-ROUNDTRIP"


class smc_periph_floor_roundtrip_test_seq(SmcCsrSeq):
    """Measure the three input clock periods, then round-trip AVS_CFG_0.MAX_RETRIES."""

    def __init__(self, name: str, *, cell: str, periods_ns: tuple[float, float, float]) -> None:
        super().__init__(name)
        self.cell = cell
        self.declared_ps = dict(zip(("ref", "smc", "periph"), (int(p * 1000) for p in periods_ns)))
        self.measured_ps: dict[str, float] = {}
        self.fence: list[tuple[str, int]] = []
        self.last_resp: int | None = None
        self.last_edge_state = "no edge wait yet"
        self.edge_waits = 0

    def _mark(self, term: str) -> None:
        now = int(get_sim_time("ps"))
        self.fence.append((term, now))
        cocotb.log.info("STEP %s: complete at %d ps", term, now)

    async def _edge(self, clk_name: str, clk, idx: int) -> None:
        self.edge_waits += 1
        edge = RisingEdge(clk)
        try:
            await cocotb.triggers.with_timeout(edge, EDGE_TIMEOUT_NS, "ns")
        except cocotb.result.SimTimeoutError:
            raise AssertionError(
                f"{clk_name} rising edge {idx} not seen within {EDGE_TIMEOUT_NS} ns; "
                f"last={self.last_edge_state}"
            ) from None
        self.last_edge_state = f"{clk_name} edge {idx} at {int(get_sim_time('ps'))} ps"

    async def _measure_periods(self) -> None:
        dut = cocotb.top
        for name, clk in (
            ("ref", dut.clk_ref_i),
            ("smc", dut.clk_smc_i),
            ("periph", dut.clk_periph_i),
        ):
            await self._edge(name, clk, 0)
            start = get_sim_time("ps")
            for idx in range(1, MEASURE_EDGES + 1):
                await self._edge(name, clk, idx)
            self.measured_ps[name] = (get_sim_time("ps") - start) / MEASURE_EDGES

    async def _access(self, label: str, op: SmcSysAxiOp, data: int = 0) -> int:
        item = SmcSysAxiItem(f"{'rd' if op == SmcSysAxiOp.READ else 'wr'}_{label}")
        item.op = op
        item.addr = AVS_CFG_0
        item.length = 4
        item.timeout_ns = ACCESS_TIMEOUT_NS
        if op == SmcSysAxiOp.WRITE:
            item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.last_resp = item.resp_code
        assert item.resp_code == OKAY, (
            f"{label} @ 0x{AVS_CFG_0:08x}: response code {item.resp_code}, expected OKAY ({OKAY})"
        )
        return item.rdata

    async def body(self) -> None:
        assert hasattr(cocotb.top, "clk_ref_i"), "clk_ref_i not exported"
        assert hasattr(cocotb.top, "clk_smc_i"), "clk_smc_i not exported"
        assert hasattr(cocotb.top, "clk_periph_i"), "clk_periph_i not exported"

        await self._measure_periods()
        for name, want in self.declared_ps.items():
            got = self.measured_ps[name]
            assert got == want, (
                f"cell {self.cell}: {name} period measured {got} ps, expected {want} ps"
            )
        self._mark(FENCE_TERMS[0])

        saved = await self._access("AVS_CFG_0_SAVE", SmcSysAxiOp.READ)
        self._mark(FENCE_TERMS[1])

        resync = (saved & RESYNC_INTERVAL_BM) >> RESYNC_INTERVAL_BP
        written = (saved & ~MAX_RETRIES_BM) | (MAX_RETRIES_WRITTEN << MAX_RETRIES_BP)
        await self._access("AVS_CFG_0_WRITE", SmcSysAxiOp.WRITE, written)
        self._mark(FENCE_TERMS[2])

        got = await self._access("AVS_CFG_0_READ_BACK", SmcSysAxiOp.READ)
        self._mark(FENCE_TERMS[3])
        assert got == written, f"AVS_CFG_0 read back 0x{got:08x}, expected 0x{written:08x}"
        got_retries = (got & MAX_RETRIES_BM) >> MAX_RETRIES_BP
        got_resync = (got & RESYNC_INTERVAL_BM) >> RESYNC_INTERVAL_BP
        assert got_retries == MAX_RETRIES_WRITTEN, f"MAX_RETRIES 0x{got_retries:02x}"
        assert got_resync == resync, (
            f"RESYNC_INTERVAL 0x{got_resync:04x} changed from 0x{resync:04x}"
        )

        await self._access("AVS_CFG_0_RESTORE", SmcSysAxiOp.WRITE, saved)
        restored = await self._access("AVS_CFG_0_RESTORE_RB", SmcSysAxiOp.READ)
        self._mark(FENCE_TERMS[4])
        assert restored == saved, f"restore read 0x{restored:08x}, expected 0x{saved:08x}"

        chk_stamp = int(get_sim_time("ps"))
        cocotb.log.info(
            "%s: cell=%s periods_ps ref=%s smc=%s periph=%s; AVS_CFG_0 saved=0x%08x "
            "written=0x%08x read_back=0x%08x MAX_RETRIES=0x%02x RESYNC_INTERVAL=0x%04x "
            "restored=0x%08x resp=OKAY",
            CHECKER_TERM,
            self.cell,
            self.measured_ps["ref"],
            self.measured_ps["smc"],
            self.measured_ps["periph"],
            saved,
            written,
            got,
            got_retries,
            got_resync,
            restored,
        )

        waits = (
            f"SEP_IN_access={ACCESS_TIMEOUT_NS}ns last_resp={self.last_resp} "
            f"fail=AssertionError(access timeout or non-OKAY) accesses={self.accesses}",
            f"input_clock_edge={EDGE_TIMEOUT_NS}ns last={self.last_edge_state} "
            f"fail=AssertionError(no edge) edge_waits={self.edge_waits}",
        )
        cocotb.log.info("CHK-TIMEOUT-PATHS: %d bounded waits: %s", len(waits), " ".join(waits))

        order = [t for t, _ in self.fence]
        assert order == list(FENCE_TERMS), f"fence order {order} != {list(FENCE_TERMS)}"
        times = [t for _, t in self.fence]
        for prev, cur, term in zip(times, times[1:], order[1:]):
            assert cur > prev, f"step {term} stamp {cur} ps is not after {prev} ps"
        assert chk_stamp >= times[-1], f"{CHECKER_TERM} printed at {chk_stamp} ps before restore"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS),
            CHECKER_TERM,
            ", ".join(f"{t}@{s}" for t, s in self.fence),
        )
