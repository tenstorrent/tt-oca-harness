# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The register blocks of the SMC peripherals no leaf writes.

Cycles the AVSBus controller, the three telemetry receivers, the OCTS system
timer, the eFuse interface controller, the DMA controller configuration and
the four log engines' region and enable registers against their generated RDL
contract, and restores each one. The eFuse data and program-enable bits are
held at their reset so nothing the sweep writes can arm a fuse burn, and the
system timer CTRL takes constrained patterns that keep CREDIT_VAL above
PULSE_WIDTH as its RDL requires.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_periph_regblock_sweep_test_seq import smc_periph_regblock_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
#   39 half-register cycles, 12 accesses each -- the reset read, 2x(half write
#     + readback) for the ones pattern, the same for the zeros pattern, two
#     restore writes and the restore read:
#       11 single-instance registers                                        132
#       2 constrained cycles of the OCTS system timer CTRL                   24
#       3 telemetry receivers x 3 registers                                 108
#       4 log engines x 4 registers                                         192
#   1 full-width cycle for the DMA configuration, whose block refuses a
#     sub-word write: the reset read, a write and a readback for each of the
#     ones and zeros patterns, the restore write and its readback              7
#   3 telemetry interrupt legs, 9 accesses each -- the idle INTR_STATUS read,
#     the INTR_TEST force write and readback, the release write and readback,
#     the pulse write and readback, the INTR_STATUS clear write and readback  27
#   the eFuse status leg: the idle read, the write of its three clears and
#     the readback                                                            3
PERIPH_REGBLOCK_SWEEP_MIN_CSR_ACCESSES = 493


@pyuvm.test()
class smc_periph_regblock_sweep_test(smc_base_test):
    """Cycle every unswept peripheral register against its RDL contract."""

    required_evidence = (
        "CHK-PERIPH-EFUSE-STATUS",
        "CHK-PERIPH-LOG-ENGINE-SWEEP",
        "CHK-PERIPH-REGBLOCK-COMPARES",
        "CHK-PERIPH-REGBLOCK-SINGLE-SWEEP",
        "CHK-PERIPH-TELEMETRY-SWEEP",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_periph_regblock_sweep_test_seq("smc_periph_regblock_sweep_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=PERIPH_REGBLOCK_SWEEP_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.registers_swept} peripheral register cycles, "
                f"{seq.intr_status_cleared} telemetry INTR_STATUS clears"
            ),
        )
