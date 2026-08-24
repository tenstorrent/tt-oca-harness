# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ss_reset_complete_i CSR and SS0 warm_reset_n. No firmware."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_ss_reset_complete_test_seq import smc_ss_reset_complete_test_seq


@pyuvm.test()
class smc_ss_reset_complete_test(smc_base_test):
    """Pin→CSR complete + SW warm SS0; not the FW handshake binary."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ss_reset_complete_test_seq("ss_reset_complete_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert (
            seq.idle_ok and seq.drop_ok and seq.restore_ok and seq.warm_ok
        ), (
            f"ss complete incomplete idle={seq.idle_ok} drop={seq.drop_ok} "
            f"restore={seq.restore_ok} warm={seq.warm_ok}"
        )
