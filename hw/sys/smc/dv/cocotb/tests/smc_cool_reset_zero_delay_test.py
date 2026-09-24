# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An FLR cool reset with no pre-reset delay programmed.

Signals an FLR with both counters at their reset 0 and requires the request to
latch with no cool following, then signals it again with the same pre-delay of
0 and a non-zero hold and requires the cool to run. A warm-domain scratch
register written before the cool has to read 0 after it.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cool_reset_zero_delay_test_seq import smc_cool_reset_zero_delay_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. The bounded polls add more.
#
#   the idle reads of ISOLATE_REQ_SMC_REG and both FLR counters               3
#   at least one SMC_REG poll for the deny leg's latch                        1
#   the request cleared and at least one poll of the clear                    2
#   both FLR counters written and read back                                   4
#   the warm-domain scratch written and read back                             2
#   the post-cool scratch read                                                1
#   the post-cool SMC_REG read, the clearing write and at least one poll      3
#   the hold counter cleared and read back                                    2
COOL_RESET_ZERO_DELAY_MIN_CSR_ACCESSES = 18


@pyuvm.test()
class smc_cool_reset_zero_delay_test(smc_base_test):
    """FLR with the pre-reset delay at 0: no cool without a hold, cool with one."""

    required_evidence = (
        "CHK-FLR-ZERO-DELAY-COOL",
        "CHK-FLR-ZERO-DELAY-DENY",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cool_reset_zero_delay_test_seq("smc_cool_reset_zero_delay_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=COOL_RESET_ZERO_DELAY_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"cool asserted {seq.assert_edges} clk_ref_i edge(s) after the FLR request "
                f"and held for {seq.hold_edges}"
            ),
        )
