# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS UART/SPI/log-engine CSR smoke."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_spi_log_engine_test_seq import smc_uart_spi_log_engine_test_seq
from smc_base_test import smc_base_test

# Fail-capable stimulus floor for the UART_LOG record, written out here rather
# than derived from the sequence's own register table: a floor
# computed from `len(UART_LOG_READS)` would shrink together with a sequence that
# silently stopped issuing reads, which is exactly the failure this floor exists
# to catch. Composition (smc_uart_spi_log_engine_test_seq):
#   5 RDL-reset registers (UART_LOG_ENGINE_CTRL, UART_IIR, UART_LSR,
#     LOG_ENGINE_CTRL, LOG_ENGINE_INTR_STATUS)
# + 1 UART_LOG_ENGINE_CTRL.CTRL.UART_EN write (routes the CTS pad to the pin)
# + 2 x UART_MSR (first read = DCTS|CTS, second read = DCTS cleared)
# + 2 x UART_MSR per test-driven CTS pad level (the transition read carrying
#     DCTS=1, then the read proving DCTS cleared), for pad=1 and pad=0
#   => 12 minimum. It is a floor, not an equality: the pad-follow legs poll with
#   a bound, so a slower propagation issues more reads.
UART_LOG_MIN_CSR_ACCESSES = 12


@pyuvm.test()
class smc_uart_spi_log_engine_test(smc_base_test):
    """Run the UART/log-engine representative CSR precheck."""

    required_evidence = (
        "CHK-UART-LOG-COUNT",
        "CHK-UART-LOG-LOG_ENGINE_CTRL",
        "CHK-UART-LOG-LOG_ENGINE_INTR_STATUS",
        "CHK-UART-LOG-UART_IIR",
        "CHK-UART-LOG-UART_LOG_ENGINE_CTRL",
        "CHK-UART-LOG-UART_LSR",
        "CHK-UART-MSR-CTS-PAD0",
        "CHK-UART-MSR-CTS-PAD1",
        "CHK-UART-MSR-DELTA-CLEAR",
        "CHK-UART-MSR-DELTA-CLEAR-PAD0",
        "CHK-UART-MSR-DELTA-CLEAR-PAD1",
        "CHK-UART-MSR-FIRST",
    )
    min_evidence = 12

    # This scenario records its own protocol VIP item from the measured counts
    # below, so the base-test activity stamp is off.
    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_spi_log_engine_test_seq("uart_spi_log_engine_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            csr_accesses=seq.accesses,
            # No timeout statistic is published. `csr_read` leaves `allow_timeout`
            # False and `SmcSysAxiDriver._timed_event` raises on expiry after
            # `cfg.axi_timeout_ns` (env/smc_sys_axi_agent.py), so
            # [TIMEOUT-MUST-FAIL] is carried by the driver; `seq.timeouts` is
            # incremented only by `csr_read_bounded` / `csr_short_timeout`
            # (seq_lib/smc_csr_seq_utils.py), which this sequence never calls, so
            # `None` renders `n/a` rather than an unmeasured 0.
            timeouts=None,
            min_csr_accesses=UART_LOG_MIN_CSR_ACCESSES,
            details=(
                f"{seq.accesses} SEP_IN AXI accesses of the UART/log-engine CSR "
                "window, each returning OKAY with rdata value-compared by the "
                "SYS-AXI scoreboard: UART_LOG_ENGINE_CTRL, UART_IIR, UART_LSR, "
                "LOG_ENGINE_CTRL and LOG_ENGINE_INTR_STATUS against their RDL "
                f"reset constants, then {seq.msr_reads} UART_MSR reads proving "
                "CTS = ~cts_ni at BOTH pad levels this test drives on UART0 CTS "
                "pad 14 (via the top-level tb_gpio_ext_drive_* pins, not a pad "
                "default) and DCTS set->clear in both directions, all expected "
                "values taken from the MSR field descriptions, every compare "
                "masked to the CTS/DCTS bits this test drives"
            ),
        )
