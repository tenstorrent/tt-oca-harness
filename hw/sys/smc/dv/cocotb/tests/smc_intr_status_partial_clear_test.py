# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write-one-to-clear status registers cleared a few bits at a time.

On every I2C INTR_STATE, log-engine INTR_STATUS and telemetry-receiver
INTR_STATUS instance: raise the whole common mask through INTR_TEST, write back
half of it and require exactly that half to clear while the other half stays
set, then write the rest and require the register to read clear. The half the
write carries a zero over is the side of the oneToClear contract no leaf has
driven.
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
# 10 status registers -- 3 I2C, 4 log engines, 3 telemetry receivers -- at 7
# SEP_IN AXI accesses each: the idle read, the INTR_TEST write and the raised
# read, the partial clear and its read, the rest and its read.
INTR_STATUS_PARTIAL_CLEAR_MIN_CSR_ACCESSES = 10 * 7


@pyuvm.test()
class smc_intr_status_partial_clear_test(smc_base_test):
    """Clear write-one-to-clear status bits a few at a time, not all at once."""

    required_evidence = ("CHK-INTR-STATUS-PARTIAL-CLEAR",)
    min_evidence = 1

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
