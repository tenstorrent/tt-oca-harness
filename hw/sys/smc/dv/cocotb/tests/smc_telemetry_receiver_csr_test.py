# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS P1 coverage-gap: TELEMETRY_RECEIVER 0/1/2 CSR precheck."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_telemetry_receiver_csr_test_seq import smc_telemetry_receiver_csr_test_seq


@pyuvm.test()
class smc_telemetry_receiver_csr_test(smc_base_test):
    """U4-6: TELEMETRY CSR reset + INTR_TEST -> tb_telemetry_irq_any."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_receiver_csr_test_seq("smc_telemetry_receiver_csr_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.telemetry_irq_ok and seq.telemetry_atb_ok, (
            f"U4-6 telemetry failed: irq={seq.telemetry_irq_ok} "
            f"atb={seq.telemetry_atb_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "U4-6: TELEMETRY CTRL reset + INTR_TEST IRQ + ATB "
                f"message->PROBE_ID (irq={seq.telemetry_irq_ok} "
                f"atb={seq.telemetry_atb_ok})"
            ),
        )
