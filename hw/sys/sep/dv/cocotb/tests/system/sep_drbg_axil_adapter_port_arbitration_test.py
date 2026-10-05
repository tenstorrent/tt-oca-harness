# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every legal AW/W/AR ordering at a drbg_axil64_lane_adapter port.

Run mode: no_cpu with +skip_fuse_sense. AW, W and AR are independent AXI channels
(IHI 0022 A3.3). In idle the adapter accepts each write half independently
until that half is pending, and accepts a read only when neither write half
is pending. Both accesses must retire under every ordering.

The fabric-driven leaves (`sep_drbg_axil_concurrent_*`) reach the DUT's own
adapters but can present only one of the three orderings -- the crossbar
delivers W a cycle after AW and re-serializes to that order whatever the
master does, which `CHK-CONCURRENT-CAL` measures on both sides. This leaf
drives a TB-owned second instance of the same module at its port, so all
three orderings are presentable to the cycle, and the vehicle's own reset
keeps cells independent.

Division of labour: this leaf grades the module's arbitration,
the fabric-driven leaves grade the SEP integration. Neither substitutes for
the other, and this one does not claim the integration.

CHK-PORT-ANCHOR: a plain read of the live CSRNG lane answers OKAY before the
vehicle is touched. This proves that the DUT lane is out of reset, and it gives
the scoreboard (fed from the AXI agent) a transaction, without which the
scoreboard refuses a pass.

CHK-PORT-CONTROL: a lone write, a lone read, and a write whose AW and W are
separated by the same gap the overlap cells use, all retire and answer OKAY.
The gapped leg is what excludes the channel separation itself as the cause of
an overlap-cell failure; without it that exclusion would rest on reading the
RTL. Both halves matter: an access the adapter rejects as unsupported is
answered SLVERR straight out of ST_IDLE with nothing forwarded, and retires
just as promptly as a real one, so the response code is what shows the
forwarding leg is alive. Without the controls every ordering would report as
stalled on a broken driver.

CHK-PORT-STIM: the ordering the port actually presented, read off
`tbadp_chan_o`, not the offsets requested. In `aw-then-ar` and `w-then-ar` the
cell must also reach the half-committed state: a cycle with AR valid, one write
half handshaken and the other pending. A cell that misses either is a stimulus
failure and is reported as one, not scored as coverage.

CHK-PORT-PROGRESS: both accesses retire -- BVALID and RVALID both seen.
The check is a bounded cycle count plus the longest run of
held-valids-with-no-ready, so a hang that `ASSERT_KNOWN` would miss still
fails the leaf.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_concurrent_rw_seq import LANE_ADDRS
from seq_lib.sep_drbg_adapter_port_seq import (
    GAP_CYCLES,
    ORDER_NAMES,
    PORT_ORDERS,
    RESP_OKAY,
    AdapterPortVehicle,
)


@pyuvm.test()
class sep_drbg_axil_adapter_port_arbitration_test(sep_base_test):
    """Under all three AW/W/AR orderings at the lane adapter's port, both accesses retire."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        # Anchor on the real DUT before touching the vehicle. Two reasons:
        # the scoreboard is fed from the AXI agent and a leaf that drove only
        # the TB vehicle would end with no positive evidence and could never
        # report a pass; and it confirms the DUT lane this module is
        # instantiated for is actually alive, so a green result here cannot
        # come from a design that never came out of reset.
        anchor = SepAxiAccessSeq(
            "tbadp_anchor_read",
            op=SepAxiOp.READ,
            addr=LANE_ADDRS["csrng"][0],
            length=4,
            size=2,
        )
        await self.start_seq(anchor)
        assert anchor.resp_code == RESP_OKAY, (
            f"CHK-PORT-ANCHOR FAIL: a plain read of the live CSRNG lane at "
            f"0x{LANE_ADDRS['csrng'][0]:08x} answered resp={anchor.resp_code}; "
            f"the DUT is not up, so nothing this leaf observes on the vehicle "
            f"would say anything about the design"
        )
        self.logger.info(
            "CHK-PORT-ANCHOR PASS: live CSRNG lane read 0x%08x = 0x%x (OKAY)",
            LANE_ADDRS["csrng"][0],
            anchor.rdata & 0xFFFFFFFF,
        )

        veh = AdapterPortVehicle()

        # Control first: a lone write and a lone read must retire. A vehicle
        # that cannot complete an access on its own would report every
        # ordering as stalled and imitate the defect exactly, so the stall
        # cells below are only evidence once this passes.
        ctl = await veh.run_control()
        for half, obs in ctl.items():
            assert obs["retired"], (
                f"CHK-PORT-CONTROL FAIL: the lone {half} did not retire at the "
                f"adapter port ({veh.summary(obs)}); with no channel overlap "
                f"nothing gates it, so the vehicle or the responder behind the "
                f"adapter is broken and the overlap cells below would prove "
                f"nothing"
            )
        # Retiring is not enough. An access the adapter rejects as unsupported
        # is answered SLVERR out of ST_IDLE with nothing forwarded, and retires
        # just as promptly -- so a control that only watched the valid would
        # accept a dead forwarding path. The response code is what separates
        # them, and OKAY can only come from the far side.
        for half, key in (
            ("write", "b_resp"),
            ("read", "r_resp"),
            ("gapped-write", "b_resp"),
        ):
            assert ctl[half][key] == RESP_OKAY, (
                f"CHK-PORT-CONTROL FAIL: the lone {half} retired with "
                f"resp={ctl[half][key]}, not OKAY ({veh.summary(ctl[half])}); "
                f"the adapter answered from its own reject path instead of "
                f"forwarding, so this control does not show the forwarding leg "
                f"is alive and the overlap cells below would prove nothing"
            )
        self.logger.info(
            "CHK-PORT-CONTROL PASS: lone write retired (%s); lone read retired "
            "(%s); gapped write, AW then W %d cycles later and no AR, retired "
            "(%s) -- so the channel separation the overlap cells use is not "
            "itself what stalls them",
            veh.summary(ctl["write"]),
            veh.summary(ctl["read"]),
            GAP_CYCLES,
            veh.summary(ctl["gapped-write"]),
        )

        fails: list[str] = []
        stim_fails: list[str] = []
        covered: list[str] = []
        arbitration_covered: list[str] = []

        for order, aw_off, w_off, ar_off in PORT_ORDERS:
            obs = await veh.run_order(order, aw_off, w_off, ar_off)
            summary = veh.summary(obs)

            if obs["presented"] != order:
                stim_fails.append(
                    f"[{order}] port presented {obs['presented']} for offsets "
                    f"aw+{aw_off} w+{w_off} ar+{ar_off}; {summary}"
                )
                self.logger.error("CHK-PORT-STIM FAIL: %s", stim_fails[-1])
                continue
            self.logger.info("CHK-PORT-STIM OK: %s presented at the port; %s", order, summary)

            if not obs["retired"]:
                fails.append(
                    f"[{order}] the write and/or the read did not retire within "
                    f"the bound: the port held its valids for "
                    f"{obs['max_stall_run']} consecutive cycles with aw_ready, "
                    f"w_ready and ar_ready ALL low, so no channel could retire "
                    f"and neither side may deassert VALID (AMBA IHI 0022 "
                    f"A3.2.1); {summary}"
                )
                self.logger.error("CHK-PORT-PROGRESS FAIL: %s", fails[-1])
                continue
            if obs["b_resp"] != RESP_OKAY or obs["r_resp"] != RESP_OKAY:
                fails.append(
                    f"[{order}] both accesses retired but a response was not "
                    f"OKAY (b_resp={obs['b_resp']} r_resp={obs['r_resp']}); "
                    f"{summary}"
                )
                self.logger.error("CHK-PORT-PROGRESS FAIL: %s", fails[-1])
                continue

            hs = obs["hs"]
            if any(hs[ch] is None for ch in ("aw", "w", "ar")):
                fails.append(
                    f"[{order}] response retired without all three recorded handshakes; {summary}"
                )
                self.logger.error("CHK-PORT-ARBITRATION FAIL: %s", fails[-1])
                continue
            # The rule in every ordering: AR is never accepted while one write
            # half has handshaken and the other is still pending, i.e. in the
            # cycles after the first write handshake up to the second.
            first_w, last_w = min(hs["aw"], hs["w"]), max(hs["aw"], hs["w"])
            if first_w < hs["ar"] <= last_w:
                fails.append(
                    f"[{order}] AR handshook at cycle {hs['ar']} while a write half "
                    f"was pending (AW={hs['aw']} W={hs['w']}); {summary}"
                )
                self.logger.error("CHK-PORT-ARBITRATION FAIL: %s", fails[-1])
                continue
            if order not in ("aw-then-ar", "w-then-ar"):
                arbitration_covered.append(order)
                self.logger.info(
                    "CHK-PORT-ARBITRATION OK: %s accepted no AR while a write half was "
                    "pending (AW=%d W=%d AR=%d)",
                    order,
                    hs["aw"],
                    hs["w"],
                    hs["ar"],
                )
            if order in ("aw-then-ar", "w-then-ar"):
                # The cell grades the half-committed state: AR valid while one
                # write half has handshaken and the other is still pending. That
                # state spans cycles first_w+1 .. last_w, so it exists only if
                # the halves handshook in different cycles and AR went valid by
                # last_w. A cell that never reached it is a stimulus miss.
                if not (first_w < last_w and obs["valid"]["ar"] <= last_w):
                    stim_fails.append(
                        f"[{order}] the half-committed state was not reached: "
                        f"AR valid at cycle {obs['valid']['ar']}, write halves "
                        f"handshook at AW={hs['aw']} W={hs['w']}, so no cycle "
                        f"had AR valid with one half accepted and the other "
                        f"pending; {summary}"
                    )
                    self.logger.error("CHK-PORT-STIM FAIL: %s", stim_fails[-1])
                    continue
                self.logger.info(
                    "CHK-PORT-STIM OK: %s reached the half-committed state "
                    "(AR valid=%d, first write half hs=%d, second hs=%d)",
                    order,
                    obs["valid"]["ar"],
                    first_w,
                    last_w,
                )
                # AR arrives while the leading half is pending and must wait
                # for both.
                if hs["ar"] <= max(hs["aw"], hs["w"]):
                    fails.append(
                        f"[{order}] AR handshook at cycle {hs['ar']} before both "
                        f"write halves were accepted (AW={hs['aw']} W={hs['w']}); "
                        f"{summary}"
                    )
                    self.logger.error("CHK-PORT-ARBITRATION FAIL: %s", fails[-1])
                    continue
                arbitration_covered.append(order)
                self.logger.info(
                    "CHK-PORT-ARBITRATION OK: %s held AR until both write halves "
                    "handshook (AW=%d W=%d AR=%d)",
                    order,
                    hs["aw"],
                    hs["w"],
                    hs["ar"],
                )

            covered.append(order)
            self.logger.info(
                "CHK-PORT-PROGRESS OK: %s retired both accesses with OKAY; %s",
                order,
                summary,
            )

        # A stimulus miss is reported before a DUT verdict: a cell that never
        # presented its ordering says nothing about the arbitration either way,
        # and must not be absorbed into a pass or a fail.
        assert not stim_fails, (
            f"CHK-PORT-STIM FAIL: {len(stim_fails)} ordering(s) were not "
            f"presented at the port, so the arbitration contract was not "
            f"exercised for them: {'; '.join(stim_fails)}"
        )
        self.logger.info(
            "CHK-PORT-STIM PASS: all %d ordering(s) presented at the port: %s; "
            "aw-then-ar and w-then-ar reached the half-committed state",
            len(ORDER_NAMES),
            ", ".join(ORDER_NAMES),
        )

        if fails:
            raise AssertionError(
                f"CHK-PORT-PROGRESS FAIL: {len(fails)} of {len(ORDER_NAMES)} "
                f"legal channel ordering(s) stalled the adapter or answered "
                f"non-OKAY: {'; '.join(fails)}"
            )
        assert len(covered) == len(ORDER_NAMES), (
            f"CHK-PORT-PROGRESS FAIL: covered {len(covered)} of "
            f"{len(ORDER_NAMES)} ordering(s): {covered}"
        )
        assert set(arbitration_covered) == set(ORDER_NAMES), (
            "CHK-PORT-ARBITRATION FAIL: read-acceptance ordering covered "
            f"{arbitration_covered}, expected every ordering {list(ORDER_NAMES)}"
        )
        self.logger.info(
            "CHK-PORT-ARBITRATION PASS: no AR accepted while a write half was pending in "
            "%s; in aw-then-ar and w-then-ar AR followed both write-half handshakes",
            ", ".join(ORDER_NAMES),
        )
        self.logger.info(
            "CHK-PORT-PROGRESS PASS: %d/%d ordering(s) retired both accesses with OKAY (%s)",
            len(covered),
            len(ORDER_NAMES),
            ", ".join(covered),
        )
