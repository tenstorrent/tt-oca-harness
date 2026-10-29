# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_R5_001 ANCHOR: smc_intr_status_partial_clear_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 2c5cab6ee3105067d2e928d1ca44ed1353f478deba6b19e22d927ece1209f4bb
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_R5_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb
"""Write-one-to-clear status registers cleared a few bits at a time.

On every I2C INTR_STATE, log-engine INTR_STATUS and telemetry-receiver
INTR_STATUS instance: raise the whole common mask through INTR_TEST, write back
half of it and require exactly that half to clear while the other half stays
set, then write the rest and require the register to read clear. The half the
write carries a zero over is the side of the oneToClear contract no leaf has
driven.

On I2C instances 1 and 2 the leaf then runs the same leg with the halves
swapped, so each of the 13 clearable bits is held set against a zero once and
cleared once per instance, and raises each of the 13 INTR_TEST sources alone,
requiring exactly that bit on the written instance and nothing on the other.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_intr_status_partial_clear_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_intr_status_partial_clear_test_seq import (
    smc_intr_status_partial_clear_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# Setup: the clock-gate read and write and the I2C1 / I2C2 reset reads (4).
# 10 status registers -- 3 I2C, 4 log engines, 3 telemetry receivers -- at 7
# SEP_IN AXI accesses each: the idle read, the INTR_TEST write and the raised
# read, the partial clear and its read, the rest and its read. The swapped pass
# on I2C1 and I2C2 at 6 each, and the single-source walk on I2C1 and I2C2 at 13
# sources x 6 accesses each.
INTR_STATUS_PARTIAL_CLEAR_MIN_CSR_ACCESSES = 4 + 10 * 7 + 2 * 6 + 2 * 13 * 6


@pyuvm.test()
class smc_intr_status_partial_clear_test(smc_base_test):
    """Clear write-one-to-clear status bits a few at a time, not all at once."""

    required_evidence = (
        "CHK-I2C1-INTR-TEST-SINGLE",
        "CHK-I2C12-W1C-SWAP-HOLD",
        "CHK-I2C2-INTR-TEST-SINGLE",
        "CHK-INTR-STATUS-PARTIAL-CLEAR",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_intr_status_partial_clear_test_seq("smc_intr_status_partial_clear_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            min_csr_accesses=INTR_STATUS_PARTIAL_CLEAR_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.registers} status registers, {seq.bits_held} bits held set against a zero"
            ),
        )
