# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS mailbox data/error depth test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_mailbox_data_error_test_seq import smc_mailbox_data_error_test_seq
from seq_lib.smc_mailbox_vip_utils import check_mailbox_irq_source
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_data_error_test(smc_base_test):
    """Run mailbox write/read data and illegal access response checks."""

    required_evidence = (
        "CHK-MAILBOX-FIFO-DATA",
        "CHK-MAILBOX-IRQ-ASSERT",
        "CHK-MAILBOX-IRQ-CLEAR",
        "CHK-MAILBOX-IRQ-IDLE",
        "CHK-MAILBOX-IRQ-SOURCE",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_data_error_test_seq("mailbox_data_error_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_mailbox_irq_source(mask=0x2)
        assert "CHK-MAILBOX-FIFO-DATA" in seq.chk_seen, (
            f"missing CHK evidence token: CHK-MAILBOX-FIFO-DATA (seen={sorted(seq.chk_seen)})"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.MAILBOX,
            type(self).__name__,
            # Directed stimulus floor: 22 SEP_IN AXI mailbox FIFO/illegal-access
            # CSR accesses. Literal here, not read from `seq.accesses`.
            min_csr_accesses=22,
            csr_accesses=seq.accesses,
            proxy=False,
            # The IRQ leg observes the aggregate `tb_mailbox_irq_any` (an OR of
            # peripheral_interrupts[7:0] in tb_top.sv), so it proves assert/clear
            # on the aggregate, not that mask 0x2 is the source that raised it
            # ([MERGED-EVIDENCE]): seq_lib/smc_mailbox_vip_utils.py, shared with
            # smc_mailbox_irq_test / smc_mailbox_event_irq_test, has no per-bit
            # probe.
            details=(
                "Mailbox FIFO data flow (outbound->inbound and inbound->"
                "outbound payloads compared) and illegal-access SLVERR "
                "checked; aggregate mailbox IRQ assert/clear observed"
            ),
        )
