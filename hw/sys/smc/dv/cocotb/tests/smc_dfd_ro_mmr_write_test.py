# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write every read-only MMR of the DFD blocks and require the write to be ignored.

Writes every register of the `cla`, `dst`, `dst_sink` and `funnel` sub-blocks
that the generated map gives no software-writable field (35 in the current map), with the CLA disarmed, and holds
each one that reads the same value twice running to returning it again.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_ro_mmr_write_test_seq import smc_dfd_ro_mmr_write_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
#   the CDbgClaCtrlStatus disarmed precheck                                   1
#   35 read-only registers in the current map, 4 accesses each: the settle
#     read, the before read, the write, and the read after it               140
#                                                                         ------
#                                                                            141
RO_MMR_WRITE_MIN_CSR_ACCESSES = 141


@pyuvm.test()
class smc_dfd_ro_mmr_write_test(smc_base_test):
    """Write every read-only DFD MMR and hold the DUT to the read-only contract."""

    required_evidence = (
        "CHK-DFD-RO-MMR-HELD",
        "CHK-DFD-RO-MMR-UNDECLARED",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_ro_mmr_write_test_seq("ro_mmr_write_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=RO_MMR_WRITE_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"{seq.registers_written} read-only registers written, {seq.held} held "
                f"their value, {seq.free_running} free-running"
            ),
        )
