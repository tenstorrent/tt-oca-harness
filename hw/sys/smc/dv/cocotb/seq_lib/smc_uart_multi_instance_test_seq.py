# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""P1 coverage-gap: UART_LOG_ENGINE 1/2/3 CSR sweep (TC_SMC_P1CG_08).

Existing UART tests only touch UART_LOG_ENGINE_0 (smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR", 0)). RTL
exposes 4 UART/LOG-engine wrap instances. This test reads the CTRL /
UART / LOG_ENGINE registers of the remaining 3 instances.
"""

from __future__ import annotations

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

# CTRL / UART / LOG_ENGINE base registers of each wrap reset to 0 per RDL
# (uart_log_engine_ctrl.rdl UART_EN, uart_16550_main.rdl, log_engine.rdl) ->
# composite reset 0x0 (RDL-traceable, G3 spec-anchored; identical on Verilator
# and VCS). Asserting it verifies per-instance decode AND spec-defined reset
# content, not merely an OKAY response.
UART_WRAP_READS = [
    (
        "UART_LOG_WRAP_1_CTRL",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR", 1
        ),
        0x0,
    ),
    (
        "UART_LOG_WRAP_1_UART",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR", 1),
        0x0,
    ),
    (
        "UART_LOG_WRAP_1_LOG_ENGINE",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR", 1),
        0x0,
    ),
    (
        "UART_LOG_WRAP_2_CTRL",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR", 2
        ),
        0x0,
    ),
    (
        "UART_LOG_WRAP_2_UART",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR", 2),
        0x0,
    ),
    (
        "UART_LOG_WRAP_2_LOG_ENGINE",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR", 2),
        0x0,
    ),
    (
        "UART_LOG_WRAP_3_CTRL",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR", 3
        ),
        0x0,
    ),
    (
        "UART_LOG_WRAP_3_UART",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR", 3),
        0x0,
    ),
    (
        "UART_LOG_WRAP_3_LOG_ENGINE",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR", 3),
        0x0,
    ),
]


class smc_uart_multi_instance_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for name, addr, expected in UART_WRAP_READS:
            await self.csr_read(name, addr, expected=expected)
        assert self.accesses == len(UART_WRAP_READS), "UART multi-instance precheck mismatch"
