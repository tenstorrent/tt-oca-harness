# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS P1 coverage-gap round 3: per-mailbox 6-field sweep x 4 outbound."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_mailbox_field_sweep_test_seq import smc_mailbox_field_sweep_test_seq


@pyuvm.test()
class smc_mailbox_field_sweep_test(smc_base_test):
    """P1 coverage-gap round 3: per-mailbox 6-field sweep x 4 outbound."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_field_sweep_test_seq("smc_mailbox_field_sweep_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.MAILBOX,
            type(self).__name__,
            # Directed stimulus floor: 27 SEP_IN AXI per-mailbox field-sweep
            # accesses. Literal here, not read from `seq.accesses`.
            min_csr_accesses=27,
            csr_accesses=seq.accesses,
            proxy=False,
            details="P1 coverage-gap round 3: per-mailbox 6-field sweep x 4 outbound",
        )
