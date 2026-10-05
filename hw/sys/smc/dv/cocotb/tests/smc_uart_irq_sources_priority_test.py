# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART 16550 IRQ source priority."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_irq_sources_priority_test_seq import (
    _INTR_FIFO_ERR,
    _INTR_LSR,
    _INTR_MODEM,
    _INTR_RDR,
    _INTR_THRE,
    _INTR_TIMEOUT,
    smc_uart_irq_sources_priority_test_seq,
)
from smc_base_test import smc_base_test

# Expected IIR.INTERRUPT_ID per source, from uart_16550_main.rdl reg IIR (the
# same table the sequence quotes). Written out here as the testcase-level golden
# so the gate does not simply re-read whatever the sequence decided to expect.
EXPECTED_SOURCE_IDS = {
    "MODEM": _INTR_MODEM,
    "THRE": _INTR_THRE,
    "RDR": _INTR_RDR,
    "LSR": _INTR_LSR,
    "FIFO": _INTR_FIFO_ERR,
    "TIMEOUT": _INTR_TIMEOUT,
}
EXPECTED_PRIORITY_PAIRS = 6


@pyuvm.test()
class smc_uart_irq_sources_priority_test(smc_base_test):
    """UART0 IER gating, natural clears, and multi-source IIR priority."""

    required_evidence = (
        "CHK-UART-IRQ-CLR-MSR",
        "CHK-UART-IRQ-CLR-RDR",
        "CHK-UART-IRQ-CLR-THRE",
        "CHK-UART-IRQ-GATE-FIFO",
        "CHK-UART-IRQ-GATE-LSR",
        "CHK-UART-IRQ-GATE-MODEM",
        "CHK-UART-IRQ-GATE-RDR",
        "CHK-UART-IRQ-GATE-THRE",
        "CHK-UART-IRQ-MAP-TIMEOUT",
        "CHK-UART-IRQ-PRI-FIFO_vs_LSR",
        "CHK-UART-IRQ-PRI-LSR_vs_RDR",
        "CHK-UART-IRQ-PRI-LSR_vs_TO",
        "CHK-UART-IRQ-PRI-RDR_vs_THRE",
        "CHK-UART-IRQ-PRI-THRE_vs_MODEM",
        "CHK-UART-IRQ-PRI-TO_vs_RDR",
        "CHK-UART-MSR-SINGLE-DELTA",
    )
    min_evidence = 16

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_irq_sources_priority_test_seq("uart_irq_prio_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.clear_ok, "IRQ clear-path phase did not complete"
        # Gate on the MEASURED interrupt ids. Every source's mapped id must be
        # the encoding the RDL assigns it, and every priority contest's observed
        # winner must be the one the RDL's priority ranking requires.
        assert set(seq.gate_map_ids) == set(EXPECTED_SOURCE_IDS), (
            f"source mapping ran for {sorted(seq.gate_map_ids)}, expected "
            f"{sorted(EXPECTED_SOURCE_IDS)}"
        )
        for name, expected_id in EXPECTED_SOURCE_IDS.items():
            gated_id, mapped_id = seq.gate_map_ids[name]
            assert mapped_id == expected_id, (
                f"{name}: forced source produced IIR id 0x{mapped_id:x}, the RDL "
                f"assigns this source 0x{expected_id:x}"
            )
            assert gated_id != expected_id, (
                f"{name}: the source was still reported (id 0x{expected_id:x}) "
                f"while its enable/force was cleared"
            )
        assert len(seq.priority_ids) == EXPECTED_PRIORITY_PAIRS, (
            f"{len(seq.priority_ids)} priority contests ran, expected {EXPECTED_PRIORITY_PAIRS}"
        )
        for name, (got, want) in seq.priority_ids.items():
            assert got == want, (
                f"{name}: IIR reported id 0x{got:x}, the RDL priority ranking requires 0x{want:x}"
            )
        # OBSERVED count from the scoreboard's per-bus tally, not the sequence's
        # own counter; the floor is an independent literal.
        measured_csr = self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            # Stimulus floor: it sits below the run-to-run minimum because the bounded IIR polls are
            # timing-dependent.
            min_csr_accesses=150,
            csr_accesses=measured_csr,
            proxy=False,
            details=(
                f"IRQ source ids {seq.gate_map_ids}; RDL-ranked priority winners {seq.priority_ids}"
            ),
        )
