# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CPU Debug Module: sbcs capability and haltsum idle readbacks."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_jtag_dm_sbcs_haltsum_test_seq import smc_jtag_dm_sbcs_haltsum_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_dm_sbcs_haltsum_test(smc_base_test):
    """sbcs capabilities are fixed under an all-ones write; haltsum reads 0 and ignores writes."""

    required_evidence = (
        "CHK-SBCS-VERSION",
        "CHK-SBCS-ASIZE",
        "CHK-SBCS-ACCESS-CAPS",
        "CHK-SBCS-CAPS-WRITE-ALL-ONES",
        "CHK-HALTSUM0-IDLE",
        "CHK-HALTSUM1-IDLE",
        "CHK-HALTSUM-WRITE-IGNORED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_dm_sbcs_haltsum_test_seq("jtag_dm_sbcs_haltsum_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dm_ok, "Debug Module sbcs/haltsum scenario failed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=0,
            # JTAG DMI only: the sbcs / haltsum compares carry the fail-capability.
            min_csr_accesses=0,
            proxy=False,
            details="CPU JTAG DMI: sbcs capability and haltsum idle readbacks",
            expected_bytes=bytes([1]),
            observed_bytes=bytes([1 if seq.dm_ok else 0]),
        )
