# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CPU Debug Module: halt group 1 through dmcs2."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_jtag_dm_haltgroup_test_seq import (
    DMCS2_GROUP_SHIFT,
    HALT_GROUP_1,
    smc_jtag_dm_haltgroup_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_dm_haltgroup_test(smc_base_test):
    """dmcs2 puts harts into halt group 1, a halt in the group halts its other members, and a
    write with hgselect set is ignored."""

    required_evidence = (
        "CHK-DM-HALTGROUP1-MEMBERSHIP",
        "CHK-DM-HALTGROUP1-PROPAGATES",
        "CHK-DM-HGSELECT-IGNORED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_dm_haltgroup_test_seq("jtag_dm_haltgroup_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dm_ok, "Debug Module halt-group scenario failed"
        joined = HALT_GROUP_1 << DMCS2_GROUP_SHIFT
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=0,
            min_csr_accesses=0,
            proxy=False,
            details="CPU JTAG DMI: dmcs2 halt group 1 membership, propagation and hgselect",
            expected_bytes=b"".join(w.to_bytes(4, "big") for w in (joined, joined, joined, 0, 0)),
            observed_bytes=b"".join(w.to_bytes(4, "big") for w in seq.group_trace),
        )
