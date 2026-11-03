# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FLR edges inside a running cool-reset sequence give one pulse of the single-request width.

``clk_rst.adoc`` "Timing and Recovery": on a synchronized FLR edge the sequencer counts in
reference-clock cycles, asserts cool reset, then releases it after the hold countdown; the
sequencer is not a queue of overlapping FLR requests.

The arm leg raises one FLR edge with the pre-reset count N and the hold count M, keeps the input
high through the same watch window the overlap leg uses, and records the cool pulse width on
``clk_ref_i``. The overlap leg raises the same request, drops and raises the
input again inside the pre-reset count and once more inside the hold, with N larger than the
hold left when the third edge lands, and then watches for twice the sequence length after the
release. All three edges must be seen by the reference-domain synchroniser, the second met with
the pre-reset counter in COUNT_DOWN and the third with it in IDLE; ``rst_cool_no`` must fall once
and rise once, the hold must equal the arm leg's, and nothing may fall again in the watched
window.
"""

from __future__ import annotations

import cocotb

from .smc_flr_sequencer_single_pulse_test_seq import (
    FLR_COUNT_DOWN,
    FLR_IDLE,
    FLR_M,
    FLR_N,
    SYNC_ALLOWANCE,
    SmcFlrLegSeq,
)

#: clk_ref_i cycles the FLR input is held low between two edges.
_EDGE_LOW_REF = 8
#: clk_ref_i edges watched after the overlap leg's release for a queued second pulse.
_REQUEUE_WATCH_REF = 2 * (FLR_N + FLR_M) + SYNC_ALLOWANCE

CHK = "CHK-FLR-NO-REQUEUE"


class smc_flr_hold_edge_requeue_test_seq(SmcFlrLegSeq):
    """Arm with one request, then a request with edges inside the count and inside the hold."""

    def __init__(self, name: str = "smc_flr_hold_edge_requeue_test_seq") -> None:
        super().__init__(name)

    async def _arm(self) -> dict:
        """One request held high through the same watch window as the overlap leg: one pulse."""
        dut = cocotb.top
        await self.program("ARM", FLR_N, FLR_M)
        self.mon.arm()
        dut.tb_cfg_flr_pf_active.value = 1
        await self.await_cool(0, FLR_N + SYNC_ALLOWANCE, "ARM_COOL_ASSERT")
        await self.await_cool(1, FLR_M + SYNC_ALLOWANCE, "ARM_COOL_RELEASE")
        await self.ref(_REQUEUE_WATCH_REF)
        pre, hold = self.pulse(
            f"ARM: one request, {_REQUEUE_WATCH_REF} edges watched after the release"
        )
        row = {"leg": "ARM", "N": FLR_N, "M": FLR_M, "pre": pre, "hold": hold}
        await self.recover("ARM")
        self.rows.append(row)
        return row

    async def _overlap(self, ref_pre: int, ref_hold: int) -> dict:
        dut = cocotb.top
        mon = self.mon
        mon.arm()
        dut.tb_cfg_flr_pf_active.value = 1
        await self.await_state(FLR_COUNT_DOWN, "OVL_COUNT_DOWN")
        await self.ref(FLR_N // 2 - _EDGE_LOW_REF)
        dut.tb_cfg_flr_pf_active.value = 0
        await self.ref(_EDGE_LOW_REF)
        dut.tb_cfg_flr_pf_active.value = 1
        second_at = mon.edge
        assert self.cool() == 1, "OVL: cool reset asserted before the pre-reset count ended"
        await self.await_cool(0, FLR_N + SYNC_ALLOWANCE, "OVL_COOL_ASSERT")
        await self.ref(FLR_M // 2 - _EDGE_LOW_REF)
        dut.tb_cfg_flr_pf_active.value = 0
        await self.ref(_EDGE_LOW_REF)
        assert self.cool() == 0, "OVL: cool reset released before the hold count ended"
        dut.tb_cfg_flr_pf_active.value = 1
        third_at = mon.edge
        await self.await_cool(1, FLR_M + SYNC_ALLOWANCE, "OVL_COOL_RELEASE")
        await self.ref(_REQUEUE_WATCH_REF)
        setting = (
            f"N={FLR_N} M={FLR_M}, second edge driven at clk_ref_i edge {second_at} (inside the "
            f"pre-reset count), third at {third_at} (inside the hold), {_REQUEUE_WATCH_REF} edges "
            f"watched after the release; the arm leg held {ref_hold}"
        )
        seen = [(e, st) for e, st in mon.posedges]
        later = [(e, st) for e, st in seen if e > second_at]
        in_count = [e for e, st in later if e <= third_at and st == FLR_COUNT_DOWN]
        in_hold = [e for e, st in later if e > third_at and st == FLR_IDLE and e < mon.rises[0]]
        assert len(seen) == 3 and len(in_count) == 1 and len(in_hold) == 1, (
            f"{CHK} FAIL: {setting}; the three request edges did not all reach the sequencer: "
            f"edges seen {mon.posedge_text()} (want one before the count, one inside the "
            f"pre-reset count met in COUNT_DOWN and one inside the hold met in IDLE)"
        )
        if len(mon.falls) > 1:
            gap = mon.falls[1] - in_hold[0]
            raise AssertionError(
                f"{CHK} FAIL: {setting}; rst_cool_no fell at clk_ref_i edges {mon.falls} and rose "
                f"at {mon.rises}: a second fall {gap} edges after the third edge, where the single "
                f"request's pre-reset count is {ref_pre}; request edges {mon.posedge_text()}"
            )
        pre, hold = self.pulse(f"{CHK} FAIL: {setting}")
        assert hold == ref_hold, (
            f"{CHK} FAIL: {setting}; the overlap pulse held {hold}; request edges "
            f"{mon.posedge_text()}"
        )
        row = {
            "leg": "OVL",
            "pre": pre,
            "hold": hold,
            "second_at": second_at,
            "third_at": third_at,
            "posedges": mon.posedge_text(),
        }
        await self.recover("OVL")
        self.rows.append(row)
        return row

    async def body(self) -> None:
        dut = cocotb.top
        await self.setup()
        self.mon.start()
        try:
            arm = await self._arm()
            ovl = await self._overlap(arm["pre"], arm["hold"])
        finally:
            self.mon.stop()
            dut.tb_cfg_flr_pf_active.value = 0
        await self.clear_counters()
        cocotb.log.info(
            "%s: N=%d M=%d: the single request gave pre=%d hold=%d clk_ref_i edges; with a second "
            "edge driven at ref edge %d (inside the pre-reset count) and a third at %d (inside the "
            "hold) rst_cool_no fell once with pre=%d hold=%d and did not fall again in the %d "
            "edges watched after the release; request edges seen %s",
            CHK,
            FLR_N,
            FLR_M,
            arm["pre"],
            arm["hold"],
            ovl["second_at"],
            ovl["third_at"],
            ovl["pre"],
            ovl["hold"],
            _REQUEUE_WATCH_REF,
            ovl["posedges"],
        )
