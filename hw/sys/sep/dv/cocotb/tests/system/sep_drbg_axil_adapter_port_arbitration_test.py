# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every legal AW/W/AR ordering at a drbg_axil64_lane_adapter port.

no_cpu / +skip_fuse_sense. AW, W and AR are independent AXI channels
(IHI 0022 A3.3) and a master may not deassert a VALID before its handshake
completes (A3.2.1). An adapter that gates its write side on `ar_valid` while
gating its read side on `aw_valid`/`w_valid` can therefore hold all three
readys low with no way out: neither side can back off, and the port stays held
until reset.

The fabric-driven leaves (`sep_drbg_axil_concurrent_*`) reach the DUT's own
adapters but can present only one of the three orderings -- the crossbar
delivers W a cycle after AW and re-serializes to that order whatever the
master does, which `CHK-CONCURRENT-CAL` measures on both sides. This leaf
drives a TB-owned second instance of the same module at its port, so all
three orderings are presentable to the cycle, and the vehicle's own reset
clears a wedge between cells so each verdict is independent.

Division of labour, deliberately: this leaf grades the MODULE's arbitration,
the fabric-driven leaves grade the SEP integration. Neither substitutes for
the other, and this one does not claim the integration.

CHK-PORT-CONTROL: a lone write and a lone read retire AND answer OKAY. Both
halves matter: an access the adapter rejects as unsupported is answered SLVERR
straight out of StIdle with nothing forwarded, and retires just as promptly as
a real one, so the response code is what shows the forwarding leg is alive. With no channel
overlap nothing in the adapter gates them, so this is what makes a stall below
attributable to the overlap rather than to the vehicle or to the responder
behind the adapter. Without it every ordering would report as stalled on a
broken driver and imitate the defect.

CHK-PORT-STIM: the ordering the port actually presented, read off
`tbadp_chan_o`, not the offsets requested. A cell whose presentation does not
match is a stimulus failure and is reported as one, not scored as coverage.

CHK-PORT-PROGRESS: both accesses retire -- BVALID and RVALID both seen. A
stall here is a stable, legal `1'b0` on all three readys, which no X-check and
no protocol assertion sees, so the check is a bounded cycle count plus the
longest run of held-valids-with-no-ready, which is the stall signature itself.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_drbg_adapter_port_seq import (
    ORDER_NAMES,
    RESP_OKAY,
    PORT_ORDERS,
    AdapterPortVehicle,
)


@pyuvm.test()
class sep_drbg_axil_adapter_port_arbitration_test(sep_base_test):
    """All three AW/W/AR orderings at the lane adapter's own port."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        veh = AdapterPortVehicle(self)

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
        # is answered SLVERR out of StIdle with nothing forwarded, and retires
        # just as promptly -- so a control that only watched the valid would
        # accept a dead forwarding path. The response code is what separates
        # them, and OKAY can only come from the far side.
        for half, key in (("write", "b_resp"), ("read", "r_resp")):
            assert ctl[half][key] == RESP_OKAY, (
                f"CHK-PORT-CONTROL FAIL: the lone {half} retired with "
                f"resp={ctl[half][key]}, not OKAY ({veh.summary(ctl[half])}); "
                f"the adapter answered from its own reject path instead of "
                f"forwarding, so this control does not show the forwarding leg "
                f"is alive and the overlap cells below would prove nothing"
            )
        self.logger.info(
            "CHK-PORT-CONTROL PASS: lone write retired (%s); lone read retired (%s)",
            veh.summary(ctl["write"]),
            veh.summary(ctl["read"]),
        )

        fails: list[str] = []
        stim_fails: list[str] = []
        covered: list[str] = []

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

            covered.append(order)
            self.logger.info(
                "CHK-PORT-PROGRESS OK: %s retired both accesses; %s", order, summary
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
            "CHK-PORT-STIM PASS: all %d ordering(s) presented at the port: %s",
            len(ORDER_NAMES),
            ", ".join(ORDER_NAMES),
        )

        if fails:
            raise AssertionError(
                f"CHK-PORT-PROGRESS FAIL: {len(fails)} of {len(ORDER_NAMES)} "
                f"legal channel ordering(s) stalled the adapter with no channel "
                f"able to retire: {'; '.join(fails)}"
            )
        self.logger.info(
            "CHK-PORT-PROGRESS PASS: %d/%d ordering(s) retired both accesses (%s)",
            len(covered),
            len(ORDER_NAMES),
            ", ".join(covered),
        )
