# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART FIFO trigger, reset, and THRE."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_fifo_basic_trigger_reset_test_seq import (
    _INTR_ID_RDR,
    smc_uart_fifo_basic_trigger_reset_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_fifo_basic_trigger_reset_test(smc_base_test):
    """UART0 loopback FIFO trigger levels + RX/TX FIFO reset."""

    required_evidence = (
        "CHK-UART-FIFO-RST-RX",
        "CHK-UART-FIFO-RST-TX",
        "CHK-UART-FIFO-TRIG-1B",
        "CHK-UART-FIFO-TRIG-32B",
        "CHK-UART-FIFO-TRIG-4B",
        "CHK-UART-FIFO-TRIG-ABOVE-DEPTH",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_fifo_basic_trigger_reset_test_seq("uart_fifo_basic_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.reset_ok, "RX/TX FIFO reset phase did not complete"
        assert seq.above_depth_ok, "above-depth RX FIFO trigger checks did not complete"
        # Gate on the MEASURED interrupt ids of each trigger cell: below the
        # programmed level the RCVR-data-available id must be absent, at the
        # level it must be present, and after popping back below it must be gone
        # again. Both cells run the same three legs against different levels, so
        # a tied-off FCR.RCVR_TRIGGER fails one of them.
        for label in ("1B", "4B", "32B"):
            ids = seq.trigger_ids.get(label)
            assert ids is not None, f"trigger cell {label} produced no samples"
            pre_id, trig_id, below_id = ids
            assert pre_id != _INTR_ID_RDR, (
                f"{label}: IIR id 0x{pre_id:x} below the programmed trigger "
                f"level, expected anything but RECEIVED_DATA_READY "
                f"(0x{_INTR_ID_RDR:x})"
            )
            assert trig_id == _INTR_ID_RDR, (
                f"{label}: IIR id 0x{trig_id:x} at the programmed trigger level, "
                f"expected RECEIVED_DATA_READY (0x{_INTR_ID_RDR:x})"
            )
            assert below_id != _INTR_ID_RDR, (
                f"{label}: IIR id 0x{below_id:x} after popping back below the "
                f"trigger level, expected RECEIVED_DATA_READY to have cleared"
            )
        # OBSERVED count from the scoreboard's per-bus tally, not the sequence's
        # own counter; the floor is an independent literal.
        measured_csr = self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            # Stimulus floor: it sits below the run-to-run minimum because the FIFO trigger polls
            # are timing-dependent.
            min_csr_accesses=100,
            csr_accesses=measured_csr,
            proxy=False,
            details=(
                f"FIFO trigger-level ids {seq.trigger_ids}; threshold 32 stayed "
                f"inactive at depth 31 and fired at 32, while thresholds 64 "
                f"through 4096 stayed inactive for an empty 32-entry FIFO; "
                f"RX/TX FIFO reset before/after LSR contrast"
            ),
        )
