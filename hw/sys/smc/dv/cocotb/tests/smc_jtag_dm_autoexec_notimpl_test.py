# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CPU Debug Module: abstractauto widths, auto-execution across a cmderr clear and the
not-implemented DMI registers."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_jtag_dm_autoexec_notimpl_test_seq import (
    JUNK_WHILE_ERR,
    X8_PATTERN,
    smc_jtag_dm_autoexec_notimpl_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_dm_autoexec_notimpl_test(smc_base_test):
    """abstractauto holds 4 data and 16 progbuf bits, a data0 access re-executes the stored
    command once cmderr is cleared, and the not-implemented DMI registers read 0."""

    required_evidence = (
        "CHK-DM-AUTOEXEC-FIELD-WIDTHS",
        "CHK-DM-AUTOEXEC-REEXEC-AFTER-CLEAR",
        "CHK-DM-NOT-IMPL-DMI-FULL",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_dm_autoexec_notimpl_test_seq("jtag_dm_autoexec_notimpl_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dm_ok, "Debug Module abstractauto scenario failed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=0,
            min_csr_accesses=0,
            proxy=False,
            details="CPU JTAG DMI: abstractauto widths and auto-execution across a cmderr clear",
            expected_bytes=b"".join(
                w.to_bytes(4, "big") for w in (X8_PATTERN, JUNK_WHILE_ERR, X8_PATTERN)
            ),
            observed_bytes=b"".join(w.to_bytes(4, "big") for w in seq.data0_trace),
        )
