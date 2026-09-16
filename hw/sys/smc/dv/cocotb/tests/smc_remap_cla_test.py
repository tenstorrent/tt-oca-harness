# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS ALIAS_REMAP translation + MMODE/ALIAS sweep + CLA."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_remap_cla_test_seq import (
    EXPECTED_JTAG_ACCESSES,
    smc_remap_cla_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor for the SEP_IN AXI CSR traffic, written out here as an
# independent constant. It is NOT read back from the sequence's own
# counter: a floor that shrinks with the sequence cannot catch a sequence that
# silently stops short. Composition: 32 remap-table reset reads + 9 CLA aperture
# accesses + 18 remap-programming/filter accesses + 82 CLA full-aperture reset
# reads (32 + 9 + 18 + 82 = 141).
#
# The 82 is the software-owned subset of the 137 registers in the generated
# CLA map -- the remaining registers are hardware-driven and cannot be held
# to an RDL reset (`Timestamp` @0x200 is a free-running counter and never
# reads its generated reset of 0x0). The sequence additionally asserts
# `len(CLA_RESET_SWEEP) >= 82`, so a generated map that lost rows fails there
# rather than quietly lowering this floor.
REMAP_CLA_MIN_CSR_ACCESSES = 141


@pyuvm.test()
class smc_remap_cla_test(smc_base_test):
    """ALIAS_REMAP address translation, remap-table reset sweep, CLA window."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_remap_cla_test_seq("smc_remap_cla_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # The OBSERVED count is the scoreboard's per-bus tally, stamped by the
        # driver that completed each access -- not `seq.accesses`, which is the
        # sequence counting itself and cannot see a mis-bound analysis path.
        measured_csr = self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0)
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            min_csr_accesses=REMAP_CLA_MIN_CSR_ACCESSES,
            csr_accesses=measured_csr,
            # JTAG-AXI fabric traffic is reported in its own field; the observed
            # count is measured inside record_protocol_vip from the scoreboard's
            # tally, and this is the exact expectation checked against it.
            fabric_accesses=EXPECTED_JTAG_ACCESSES,
            min_fabric_accesses=EXPECTED_JTAG_ACCESSES,
            fabric_access_label="jtag_axi_accesses",
            fabric_bus="JTAG AXI",
            # No access on this path runs with allow_timeout, so an expiry raises
            # in the AXI driver and control cannot reach here with a timeout
            # counted: nothing measures timeouts, and None renders as n/a.
            timeouts=None,
            proxy=False,
            details=(
                "ALIAS_REMAP_0 address translation proven at the SYS_OUT landing "
                "site; MMODE/ALIAS reset sweep; CLA allow and in-window-hole window"
            ),
        )
