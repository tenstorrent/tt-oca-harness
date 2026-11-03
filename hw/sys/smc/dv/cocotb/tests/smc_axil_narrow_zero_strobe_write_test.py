# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_SEP_SCN_006 ANCHOR: smc_axil_narrow_zero_strobe_write_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: b32eaa21a08f9bf4474335e824b910f1c8842a360b9ef27e7fc7cdff28aaa092
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_SEP_SCN_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""Narrow and zero-strobe writes over SEP_IN to the 64-bit AXI-Lite register links.

Plain CPU_CTRL registers, reset-unit 32-bit registers on the 64-bit link, the base
configuration, WSTRB 0x00 writes, the core 3 watchdog byte-enable rule, the mutexes, the
mailbox window, the zeroer start, ISOLATE_REQ_SMC_REG, RESET_CTRL, SEMA and the lock
registers take the strobe patterns of the contract. The stated behaviours are CHK lines;
every unstated strobe semantics is an OBS line that is never compared.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_axil_narrow_zero_strobe_write_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_axil_narrow_zero_strobe_write_test_seq import (
    CHECKERS,
    smc_axil_narrow_zero_strobe_write_test_seq,
)
from smc_base_test import smc_base_test

REQUIRED = tuple(sorted(CHECKERS))


@pyuvm.test()
class smc_axil_narrow_zero_strobe_write_test(smc_base_test):
    """Narrow and zero-strobe writes to plain, watchdog, mutex, mailbox, zeroer and lock registers."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_axil_narrow_zero_strobe_write_test_seq(
            "smc_axil_narrow_zero_strobe_write_test_seq"
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert len(CHECKERS) == len(REQUIRED), "checker set differs from required_evidence"
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
