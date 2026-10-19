# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC CPU Debug Module: hart halt, GPR access and program-buffer store through the DMI."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_jtag_dm_halt_progbuf_test_seq import smc_jtag_dm_halt_progbuf_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_dm_halt_progbuf_test(smc_base_test):
    """A halted hart executes a program-buffer store that lands in CPU_CTRL.SCRATCH[0]."""

    required_evidence = (
        "CHK-DM-ACT-DMSTATUS",
        "CHK-DM-ACT-RESET-HELD",
        "CHK-DM-CAP-READBACK",
        "CHK-DM-GPR-DATA",
        "CHK-DM-HALTSUM0",
        "CHK-DM-HART-HALT",
        "CHK-DM-OTHER-HART-RUNS",
        "CHK-DM-PROGBUF-IMPEBREAK",
        "CHK-DM-PROGBUF-REGS",
        "CHK-DM-PROGBUF-STORE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_dm_halt_progbuf_test_seq("jtag_dm_halt_progbuf_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dm_ok, "Debug Module halt and program-buffer scenario failed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=0,
            min_csr_accesses=0,
            proxy=False,
            details="CPU JTAG DMI: hart halt and program-buffer store into CPU_CTRL.SCRATCH[0]",
            expected_bytes=(seq.expected_scratch).to_bytes(8, "big"),
            observed_bytes=seq.scratch_after.to_bytes(8, "big"),
        )
