# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: UART_LOG_ENGINE 1/2/3 CSR sweep (TC_SMC_P1CG_08).

Existing UART tests only touch UART_LOG_ENGINE_0 (0xC000_A000). RTL
exposes 4 UART/LOG-engine wrap instances. This test reads the CTRL /
UART / LOG_ENGINE registers of the remaining 3 instances.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# CTRL / UART / LOG_ENGINE base registers of each wrap reset to 0 per RDL
# (uart_log_engine_ctrl.rdl UART_EN, uart_16550_main.rdl, log_engine.rdl) ->
# composite reset 0x0 (RDL-traceable, G3 spec-anchored; identical on Verilator
# and VCS). Asserting it verifies per-instance decode AND spec-defined reset
# content, not merely an OKAY response.
UART_WRAP_READS = [
    ("UART_LOG_WRAP_1_CTRL",        0xC000_A400, 0x0),
    ("UART_LOG_WRAP_1_UART",        0xC000_A500, 0x0),
    ("UART_LOG_WRAP_1_LOG_ENGINE",  0xC000_A600, 0x0),
    ("UART_LOG_WRAP_2_CTRL",        0xC000_A800, 0x0),
    ("UART_LOG_WRAP_2_UART",        0xC000_A900, 0x0),
    ("UART_LOG_WRAP_2_LOG_ENGINE",  0xC000_AA00, 0x0),
    ("UART_LOG_WRAP_3_CTRL",        0xC000_AC00, 0x0),
    ("UART_LOG_WRAP_3_UART",        0xC000_AD00, 0x0),
    ("UART_LOG_WRAP_3_LOG_ENGINE",  0xC000_AE00, 0x0),
]


class smc_uart_multi_instance_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for name, addr, expected in UART_WRAP_READS:
            await self.csr_read(name, addr, expected=expected)
        assert self.accesses == len(UART_WRAP_READS), (
            "UART multi-instance precheck mismatch"
        )
