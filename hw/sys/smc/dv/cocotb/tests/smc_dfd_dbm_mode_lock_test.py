# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walk the debug-bus mux modes, then latch the CLA lock and prove it holds.

Programs every value of the 2-bit `Dbmmode` field into every one of the 64 mux
identifiers, then sets `CDbgClaCtrlStatus.ClaLock` as the last act of the run
and requires a further write whose data has the bit clear to leave it set.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_dbm_mode_lock_test_seq import smc_dfd_dbm_mode_lock_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. No polling, every leg
# directed.
#
#   DEBUG_CTRL force_clk_en write                                             1
#   4 modes x 64 identifiers, plus one readback per mode                    260
#   restore: DEBUG_BUS_MUX, DEBUG_CTRL                                        2
#   the lock: read before, the set write, the readback, the clear-attempt
#     write, the readback after it                                            5
#                                                                         ------
#                                                                            268
DBM_MODE_LOCK_MIN_CSR_ACCESSES = 268


@pyuvm.test()
class smc_dfd_dbm_mode_lock_test(smc_base_test):
    """Program every debug-bus mux mode, then latch the CLA lock and hold it."""

    required_evidence = (
        "CHK-CLA-LOCK-LATCHED",
        "CHK-DBM-MODE-SWEEP",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_dbm_mode_lock_test_seq("dbm_mode_lock_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=DBM_MODE_LOCK_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"mux modes {seq.modes_programmed} over {seq.mux_writes} writes, CLA lock "
                f"held {seq.lock_held}"
            ),
        )
