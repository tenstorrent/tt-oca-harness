# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A broken UART character arriving while the receive FIFO is off.

With FCR.FIFO_ENABLE clear the character travels through the receiver buffer
register, which has its own copy of the error flags. A parity disagreement and
a word length disagreement are each sent down it, and the receive trigger
level is then programmed above the FIFO depth.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uart_rbr_error_path_test_seq import smc_uart_rbr_error_path_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_rbr_error_path_test(smc_base_test):
    """A broken character must carry its flags through the register path too."""

    required_evidence = (
        "CHK-UART-RBR-CLEAN",
        "CHK-UART-RBR-ERRORS",
        "CHK-UART-RXILVL-UNSUPPORTED",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_rbr_error_path_test_seq("uart_rbr_error_path_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
