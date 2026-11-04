# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Measure the FLR cool-reset counters in clk_ref_i cycles.

Source hw/sys/smc/regs/blocks/reset_unit/reset_unit.rdl: ISOLATE_REQ_FLR_COUNTER_VALUE is the
"number of cycles post cfg_flr_pf_active assertion is waited until cool_reset_n is asserted" and
ISOLATE_REQ_FLR_RESET_COUNTER_VALUE the "number of cycles cool_reset_n is asserted for"; neither
names a clock or an origin for the count.

For each (N, M) pair the sequence programs both counters, raises ``cfg_flr_pf_active_i`` and
samples on every ``clk_ref_i`` edge: the first edge on which the synchronised request's rising
edge is visible inside the wrap (``tb_flr_posedge_ref``), the first edge on which
``rst_cool_no`` (``tb_rst_cool_from_flr``) reads 0 and the first edge on which it reads 1 again.
A final leg raises a second ``cfg_flr_pf_active_i`` edge while the pre-delay counter is in
COUNT_DOWN and reports the counter state the edge met. Every measurement is an OBS-FLR line; the
CHK line grades liveness only: each leg produced exactly one bounded cool pulse, the warm smc
clock reset fell after the request edge and was released again.
#3423 asks `reset_unit.rdl` to state the clock, the pre-delay offset and the no-queue rule; the
leaf is held out of `all` until that ruling lands.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import reset_unit_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_isolate_pin_utils import await_skip_mem_repair, drive_isolate_pin

SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
FLR_DELAY = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_HOLD = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
SMC_BIT = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bm")

_COMBOS = [(n, m) for n in (1, 2, 3, 8) for m in (1, 4)]
_SECOND_EDGE_N, _SECOND_EDGE_M = 64, 4
_SECOND_EDGE_LOW_REF = 8
_PIN_BOUND = 64
_CDC_REF = 64
_SYNC_ALLOWANCE = 64
_RECOVERY_SMC = 50_000
_WARM_LOW_BOUND_SMC = 20_000

FLR_IDLE, FLR_COUNT_DOWN, FLR_EQUAL_ZERO = 0, 1, 2
_FLR_NAME = {0: "IDLE", 1: "COUNT_DOWN", 2: "EQUAL_ZERO"}


def _int(sig) -> int:
    assert sig.value.is_resolvable, f"X/Z on {sig._name}: {sig.value}"
    return int(sig.value)


class _RefMon:
    """clk_ref_i sampler of the FLR request edge, counter state and rst_cool_no.

    A second sampler on clk_smc_i records every fall of the warm smc clock reset, so a leg that
    is armed before its request edge sees the warm reset the cool pulse causes however long the
    pre-delay is.
    """

    def __init__(self) -> None:
        self.edge = 0
        self.posedges: list[tuple[int, int]] = []
        self.falls: list[int] = []
        self.rises: list[int] = []
        self.warm_falls = 0
        self._prev_cool = 1
        self._prev_warm = 1
        self._tasks: list = []

    def arm(self) -> None:
        self.edge = 0
        self.posedges = []
        self.falls = []
        self.rises = []
        self.warm_falls = 0
        self._prev_cool = _int(cocotb.top.tb_rst_cool_from_flr) & 1
        self._prev_warm = _int(cocotb.top.tb_rst_warm_smc_clk_n) & 1

    def start(self) -> None:
        self._tasks = [cocotb.start_soon(self._run()), cocotb.start_soon(self._run_warm())]

    def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks = []

    async def _run_warm(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            warm = _int(dut.tb_rst_warm_smc_clk_n) & 1
            if self._prev_warm and not warm:
                self.warm_falls += 1
            self._prev_warm = warm

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_ref_i)
            self.edge += 1
            if _int(dut.tb_flr_posedge_ref):
                self.posedges.append((self.edge, _int(dut.tb_flr_counter_state)))
            cool = _int(dut.tb_rst_cool_from_flr) & 1
            if self._prev_cool and not cool:
                self.falls.append(self.edge)
            elif cool and not self._prev_cool:
                self.rises.append(self.edge)
            self._prev_cool = cool


class smc_flr_counter_timing_obs_test_seq(SmcCsrSeq):
    """FLR pre-delay and hold measured on clk_ref_i for several counter values."""

    def __init__(self, name: str = "smc_flr_counter_timing_obs_test_seq") -> None:
        super().__init__(name)
        self.rows: list[dict] = []
        self._mon = _RefMon()

    async def _ref(self, n: int) -> None:
        for _ in range(n):
            await RisingEdge(cocotb.top.clk_ref_i)

    async def _await_cool(self, want: int, bound: int, label: str) -> None:
        dut = cocotb.top
        last = None
        for _ in range(bound):
            await RisingEdge(dut.clk_ref_i)
            last = _int(dut.tb_rst_cool_from_flr) & 1
            if last == want:
                return
        raise AssertionError(
            f"{label}: rst_cool_from_flr stuck at {last}, want {want}, after {bound} clk_ref_i edges"
        )

    async def _await_smc_bit(self, want: int, bound: int, label: str) -> int:
        last = 0
        for _ in range(bound):
            last = await self.csr_read(label, SMC_REG)
            if (last & SMC_BIT) == want:
                return last
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: SMC_REG=0x{last:x} want bit={want}")

    async def _recover(self, label: str) -> str:
        """Drop the request, wait the warm domain back out of reset, clear the latch.

        The warm reset must have fallen since the leg was armed (the sampler watches it from
        before the request edge) and must be released again within the bound.
        """
        dut = cocotb.top
        dut.tb_cfg_flr_pf_active.value = 0
        for _ in range(_WARM_LOW_BOUND_SMC):
            await RisingEdge(dut.clk_smc_i)
            if self._mon.warm_falls:
                break
        saw_low = self._mon.warm_falls > 0
        assert saw_low, f"{label}: warm smc clk reset never fell after the FLR cool"
        for _ in range(_RECOVERY_SMC):
            await RisingEdge(dut.clk_smc_i)
            if (_int(dut.tb_rst_warm_smc_clk_n) & 1) == 1:
                break
        else:
            raise AssertionError(f"{label}: warm smc clk reset still 0 after the FLR cool")
        post = await self.csr_read(f"SMC_REG_POST_{label}", SMC_REG)
        await self.csr_write(f"SMC_REG_CLR_{label}", SMC_REG, SMC_BIT)
        await self._await_smc_bit(0, _PIN_BOUND, f"SMC_REG_CLR_RB_{label}")
        return f"warm_low_seen={saw_low} warm_falls={self._mon.warm_falls} smc_reg_post=0x{post:x}"

    async def _program(self, label: str, n: int, m: int) -> None:
        await self.csr_write(f"FLR_DELAY_{label}", FLR_DELAY, n)
        await self.csr_read(f"FLR_DELAY_RB_{label}", FLR_DELAY, expected=n)
        await self.csr_write(f"FLR_HOLD_{label}", FLR_HOLD, m)
        await self.csr_read(f"FLR_HOLD_RB_{label}", FLR_HOLD, expected=m)
        await self._ref(_CDC_REF)

    def _measure(self, n: int, m: int, label: str) -> dict:
        mon = self._mon
        assert mon.posedges, f"{label}: no tb_flr_posedge_ref seen"
        assert mon.falls and mon.rises, f"{label}: no cool pulse recorded: {mon.falls} {mon.rises}"
        assert len(mon.falls) == 1, f"{label}: {len(mon.falls)} cool pulses, want one: {mon.falls}"
        first_pos = mon.posedges[0][0]
        return {
            "N": n,
            "M": m,
            "pre": mon.falls[0] - first_pos,
            "hold": mon.rises[0] - mon.falls[0],
            "posedge_edge": first_pos,
            "fall_edge": mon.falls[0],
            "rise_edge": mon.rises[0],
            "posedges": list(mon.posedges),
            "pulses": len(mon.falls),
        }

    async def _combo(self, n: int, m: int) -> dict:
        dut = cocotb.top
        label = f"N{n}_M{m}"
        await self._program(label, n, m)
        self._mon.arm()
        dut.tb_cfg_flr_pf_active.value = 1
        await self._await_cool(0, n + _SYNC_ALLOWANCE, f"COOL_ASSERT_{label}")
        await self._await_cool(1, m + _SYNC_ALLOWANCE, f"COOL_RELEASE_{label}")
        await self._ref(16)
        row = self._measure(n, m, label)
        row["second"] = "none"
        row["recover"] = await self._recover(label)
        cocotb.log.info(
            "OBS-FLR N=%d M=%d pre_cycles_ref=%d hold_cycles_ref=%d second_edge_during_seq=%s "
            "posedge_ref_edge=%d cool_fall_edge=%d cool_rise_edge=%d cool_pulses=%d %s",
            n,
            m,
            row["pre"],
            row["hold"],
            row["second"],
            row["posedge_edge"],
            row["fall_edge"],
            row["rise_edge"],
            row["pulses"],
            row["recover"],
        )
        return row

    async def _second_edge(self) -> dict:
        dut = cocotb.top
        n, m = _SECOND_EDGE_N, _SECOND_EDGE_M
        label = f"N{n}_M{m}_2ND"
        await self._program(label, n, m)
        self._mon.arm()
        dut.tb_cfg_flr_pf_active.value = 1
        last = None
        for _ in range(_SYNC_ALLOWANCE):
            await RisingEdge(dut.clk_ref_i)
            last = _int(dut.tb_flr_counter_state)
            if last == FLR_COUNT_DOWN:
                break
        else:
            raise AssertionError(f"{label}: flr_counter_state never COUNT_DOWN (last {last})")
        dut.tb_cfg_flr_pf_active.value = 0
        await self._ref(_SECOND_EDGE_LOW_REF)
        dut.tb_cfg_flr_pf_active.value = 1
        second_edge_at = self._mon.edge
        await self._await_cool(0, n + _SYNC_ALLOWANCE, f"COOL_ASSERT_{label}")
        await self._await_cool(1, m + _SYNC_ALLOWANCE, f"COOL_RELEASE_{label}")
        # Long enough for a queued request to run its own N + M after the first cool.
        await self._ref(2 * (n + m) + _SYNC_ALLOWANCE)
        row = self._measure(n, m, label)
        later = [(e, s) for e, s in self._mon.posedges if e > second_edge_at]
        in_count_down = [e for e, s in later if s == FLR_COUNT_DOWN]
        if not later:
            row["second"] = "not-seen"
        elif not in_count_down:
            row["second"] = "seen-in-" + _FLR_NAME.get(later[0][1], str(later[0][1]))
        else:
            row["second"] = "ignored"
        row["recover"] = await self._recover(label)
        cocotb.log.info(
            "OBS-FLR N=%d M=%d pre_cycles_ref=%d hold_cycles_ref=%d second_edge_during_seq=%s "
            "posedge_ref_edge=%d cool_fall_edge=%d cool_rise_edge=%d cool_pulses=%d "
            "posedges_ref=%s second_edge_driven_at_ref_edge=%d %s",
            n,
            m,
            row["pre"],
            row["hold"],
            row["second"],
            row["posedge_edge"],
            row["fall_edge"],
            row["rise_edge"],
            row["pulses"],
            ",".join(f"{e}:{_FLR_NAME.get(s, s)}" for e, s in row["posedges"]),
            second_edge_at,
            row["recover"],
        )
        return row

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        for name in (
            "tb_cfg_flr_pf_active",
            "tb_flr_posedge_ref",
            "tb_flr_sync_ref",
            "tb_flr_counter_state",
            "tb_rst_cool_from_flr",
            "tb_rst_warm_smc_clk_n",
        ):
            assert hasattr(dut, name), f"{name} missing from the smc_uvm_top port surface"
        dut.tb_cfg_flr_pf_active.value = 0
        dut.rst_cool_ni.value = 1
        drive_isolate_pin(dut, 0)
        await await_skip_mem_repair(dut, 0, "isolate pin low, no FLR")
        await self.csr_read("SMC_REG_IDLE", SMC_REG, expected=0)
        assert (_int(dut.tb_rst_cool_from_flr) & 1) == 1, "rst_cool_from_flr already asserted"
        self._mon.start()
        try:
            for n, m in _COMBOS:
                self.rows.append(await self._combo(n, m))
            self.rows.append(await self._second_edge())
        finally:
            self._mon.stop()
            dut.tb_cfg_flr_pf_active.value = 0
        await self.csr_write("FLR_HOLD_CLR", FLR_HOLD, 0)
        await self.csr_read("FLR_HOLD_CLR_RB", FLR_HOLD, expected=0)
        await self.csr_write("FLR_DELAY_CLR", FLR_DELAY, 0)
        await self.csr_read("FLR_DELAY_CLR_RB", FLR_DELAY, expected=0)
        drive_isolate_pin(dut, None)
        cocotb.log.info(
            "CHK-FLR-COUNTER-TIMING-OBS: %d legs each raised cfg_flr_pf_active_i, saw one bounded "
            "cool pulse on rst_cool_no and recovered the warm domain; pre/hold values are "
            "reported in the OBS-FLR lines and not graded: %s",
            len(self.rows),
            "; ".join(
                f"N={r['N']} M={r['M']} pre={r['pre']} hold={r['hold']} second={r['second']}"
                for r in self.rows
            ),
        )
