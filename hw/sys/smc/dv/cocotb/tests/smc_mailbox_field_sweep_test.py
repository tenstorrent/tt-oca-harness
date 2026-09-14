# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every readable mailbox register on both ports decodes.

The swept set is derived from the generated register map rather than listed,
so a register can only leave the sweep by leaving the map. See the sequence
docstring for why that matters.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_mailbox_field_sweep_test_seq import (
    EXPECTED_ACCESSES,
    smc_mailbox_field_sweep_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_field_sweep_test(smc_base_test):
    """Read every readable register of 4 mailboxes on each of the 2 ports."""

    required_evidence = (
        "CHK-MBOX-FIELD-COUNT",
        "CHK-MBOX-FIELD-DECODE",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_field_sweep_test_seq("smc_mailbox_field_sweep_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.MAILBOX,
            type(self).__name__,
            # Directed stimulus floor: every readable register of 4 mailboxes
            # on each of the 2 ports, plus the clock-gate accesses. Imported
            # from the sequence's map-derived constant rather than read from
            # `seq.accesses`, so it is independent of what the run did -- a
            # sweep that issued fewer reads than the register map has
            # registers fails here as well as in the sequence.
            min_csr_accesses=EXPECTED_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details="per-mailbox readable-register sweep x 4 mailboxes x 2 ports",
        )
