# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS AVSBus clock/config bounded VIP test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_avsbus_clock_config_proxy_test_seq import (
    AVSBUS_TIMEOUT_READS,
    EXPECTED_ACCESSES,
    smc_avsbus_clock_config_proxy_test_seq,
)
from seq_lib.smc_sideband_vip_utils import check_sideband_observability


@pyuvm.test()
class smc_avsbus_clock_config_proxy_test(smc_base_test):
    """AVS_CFG answers with AVS_CG_EN cleared and stops answering when set."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_clock_config_proxy_test_seq("avsbus_clock_config_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Re-derive the verdict from the measurements, not from the sequence's
        # own access counters: the positive control must have answered on every
        # window, and the gated bound must actually exceed the slowest healthy
        # round-trip (otherwise the negative leg would hold on an awake AVSBus).
        n = len(AVSBUS_TIMEOUT_READS)
        assert len(seq.ungated_latencies_ns) == n, (
            f"positive control covered {len(seq.ungated_latencies_ns)}/{n} "
            f"AVS_CFG windows: {seq.ungated_latencies_ns}"
        )
        healthy = max(seq.ungated_latencies_ns.values())
        # `gated_bound_ns > healthy` was asserted here. It is
        # `max(400, 4*healthy) > healthy`, which has NO counterexample for any
        # non-negative healthy -- true by construction because the bound is
        # DERIVED from `healthy`, so it could not fail on any RTL, while its
        # message claimed it guarded the negative leg against holding on an
        # awake AVSBus ([NO-ALWAYS-PASS-CHECKER]). The guard it described is
        # structural, not checkable.
        #
        # What IS checkable, and was missing: that the negative leg's own
        # timeout mechanism and bound do not expire on a responsive window. The
        # sequence now runs `csr_short_timeout` at exactly `gated_bound_ns` on
        # all three addresses while UNGATED; a `csr_short_timeout` that expired
        # unconditionally would previously have made the whole negative leg
        # pass vacuously.
        assert seq.ungated_same_bound_ok == n, (
            f"the same-bound ungated control covered "
            f"{seq.ungated_same_bound_ok}/{n} AVS_CFG windows, so the gated "
            f"leg's {seq.gated_bound_ns} ns bound is not shown to be "
            f"satisfiable by a responsive window (slowest healthy round-trip "
            f"measured: {healthy} ns)"
        )
        # `gated_timeouts == n` and `value_checks >= EXPECTED_VALUE_CHECKS` are
        # both already enforced inside the sequence (and `gated_timeouts` is
        # incremented immediately after `assert self.timeouts == before + 1`).
        # Restating them here adds no failure mode; the sequence-side asserts
        # are the ones with teeth.
        await check_sideband_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            # Directed stimulus floor: the AVSBus clock/config CSR accesses this
            # scenario issues. Literal here, not read from `seq.accesses`.
            min_csr_accesses=EXPECTED_ACCESSES,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=True,
            details=(
                "AVS_CFG windows answer with AVS_CG_EN cleared (positive "
                "control, latency measured) and stop answering with AVS_CG_EN "
                "set, bound derived from that measurement"
            ),
        )
