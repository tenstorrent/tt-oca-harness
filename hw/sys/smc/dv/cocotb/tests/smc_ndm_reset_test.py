# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""NDM request pin to REQUEST/IRQ to PROCESS CSR to process_o."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_ndm_reset_test_seq import smc_ndm_reset_test_seq


@pyuvm.test()
class smc_ndm_reset_test(smc_base_test):
    """Per-cluster NDM handshake without Force or firmware."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ndm_reset_test_seq("ndm_reset_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # WHERE THE TEETH ARE. Three plausible-looking asserts belong nowhere
        # near this gate, because none of them can add a failure mode
        # ([NO-ALWAYS-PASS-CHECKER]):
        #   * `count == seq.request_port_width` restated an assert the sequence
        #     had already made, and both of its sides are RTL-sourced (see the
        #     provenance note in the sequence: `tb_ndmreset_request` is a
        #     hard-coded `[3:0]` at `tb_top.sv:149`, not the DUT's parameterised
        #     port, and `ndm_reset.rdl` supplies no expected count at all).
        #   * `all_request_readback == (1 << count) - 1` restated the compare
        #     `csr_read(..., expected=all_mask)` had already handed to the
        #     scoreboard.
        #   * `bits_swept == list(range(count))` is loop integrity over a
        #     straight-line `for bit in range(count)`.
        #
        # The fail-capable, DUT-sensitive content of this testcase lives in the
        # sequence: the `expected=`-bearing NDMRESET_REQUEST readbacks (now
        # driven across every physical line, so an under-reported count fails
        # too), the bounded `_await_pins` handshakes which raise on expiry, and
        # the PROCESS write-to-`process_o` path. Only the one check that is NOT
        # a restatement is kept here.
        count = seq.cluster_count
        assert count is not None, (
            "the sequence never recorded NDMRESET_CLUSTER_COUNT, so no leg "
            "below ran against a measured cluster count"
        )
        assert seq.bits_swept, (
            f"the per-cluster handshake swept no bits at all "
            f"(cluster_count={count}); every per-bit REQUEST/PROCESS claim in "
            f"this testcase would be vacuous"
        )
