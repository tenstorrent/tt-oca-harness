# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CPU Debug Module: hawindow hart-array selection and halt-on-reset."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_jtag_dm_hawindow_resethalt_test_seq import (
    HALT_ON_RESET_HART,
    MASK_CASES,
    smc_jtag_dm_hawindow_resethalt_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_dm_hawindow_resethalt_test(smc_base_test):
    """hawindow bits 3:0 select the harts a hasel request reaches, hawindowsel reads 0, and
    setresethaltreq halts a hart that is reset-pulsed through CPU_CTRL."""

    required_evidence = (
        "CHK-DM-HAWINDOW-MASK",
        "CHK-DM-RESETHALTREQ-HALTS",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_dm_hawindow_resethalt_test_seq("jtag_dm_hawindow_resethalt_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dm_ok, "Debug Module hawindow and halt-on-reset scenario failed"
        expected = []
        for mask, _ in MASK_CASES:
            expected += [mask, 0]
        expected.append(1 << HALT_ON_RESET_HART)
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=0,
            min_csr_accesses=0,
            proxy=False,
            details="CPU JTAG DMI: hawindow hart selection and halt-on-reset through a core pulse",
            expected_bytes=b"".join(w.to_bytes(4, "big") for w in expected),
            observed_bytes=b"".join((w & 0xF).to_bytes(4, "big") for w in seq.haltsum_trace),
        )
