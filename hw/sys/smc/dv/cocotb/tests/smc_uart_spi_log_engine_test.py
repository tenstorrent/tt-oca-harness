# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS UART/SPI/log-engine CSR smoke."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_uart_spi_log_engine_test_seq import smc_uart_spi_log_engine_test_seq

# Fail-capable stimulus floor for the UART_LOG record, written out here rather
# than derived from the sequence's own register table on purpose: a floor
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
#   a bound, so a slower propagation legitimately issues more reads.
UART_LOG_MIN_CSR_ACCESSES = 12


@pyuvm.test()
class smc_uart_spi_log_engine_test(smc_base_test):
    """Run the UART/log-engine representative CSR precheck."""

    # No AUTO-COVERAGE-STAMP: this scenario records its own protocol VIP item
    # from measured counts below, so the base-test activity stamp would only add
    # a second, weaker record of the same traffic.
    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_spi_log_engine_test_seq("uart_spi_log_engine_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            csr_accesses=seq.accesses,
            # Not measured on this path -- and NOT because the reads are
            # unbounded. `csr_read` IS bounded: it leaves `allow_timeout` False,
            # and `SmcSysAxiDriver._timed_event` applies
            # `cfg.axi_timeout_ns` (50_000 ns) and raises on expiry
            # (env/smc_sys_axi_agent.py), so [TIMEOUT-MUST-FAIL] is satisfied by
            # the driver. `seq.timeouts` stays 0 only because it is incremented
            # exclusively by the two no-response-tolerating helpers
            # (`csr_read_bounded` / `csr_short_timeout`,
            # seq_lib/smc_csr_seq_utils.py), which this sequence never calls.
            # So this path takes no timeout reading at all and `n/a` is the
            # honest rendering: reporting a bound of zero would claim a
            # measurement this path never takes.
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
                "values taken from the MSR field descriptions plus the declared "
                "dsr_ni/ri_ni/dcd_ni tie-offs"
            ),
        )
