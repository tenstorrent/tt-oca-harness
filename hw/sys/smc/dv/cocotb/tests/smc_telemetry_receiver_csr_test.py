# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS TELEMETRY_RECEIVER 0/1/2 CSR precheck."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_telemetry_receiver_csr_test_seq import smc_telemetry_receiver_csr_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_receiver_csr_test(smc_base_test):
    """U4-6: TELEMETRY CSR reset + INTR_TEST -> tb_telemetry_irq_any."""

    required_evidence = (
        "CHK-TELEMETRY-RECEIVER-1-ATB",
        "CHK-TELEMETRY-RECEIVER-2-ATB",
        "CHK-TELEMETRY-RECEIVER-CSR",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_receiver_csr_test_seq("smc_telemetry_receiver_csr_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.probe_id_readback == 0x05, (
            f"TELEMETRY_0 TELEMETRY_PROBE_ID read back "
            f"{seq.probe_id_readback!r}; the ATB message this testcase framed "
            f"carried probe_id 0x05"
        )
        assert seq.status_non_empty is not None and not (seq.status_non_empty & 0x1), (
            f"TELEMETRY_0 STATUS still reports EMPTY "
            f"({seq.status_non_empty!r}) after the ATB message"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            # Structural CSR-access floor for the declared stimulus, written out
            # here as an independent constant. The reset sweep alone is 21 reads
            # (3 receivers x 7 register types); the receiver 1/2 INTR_ENABLE
            # write/readback/restore legs add 8; the receiver 0 IRQ and ATB
            # halves add the remainder. A run that stopped after the sweep
            # fails this floor.
            min_csr_accesses=40,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "U4-6: TELEMETRY receiver 0 reset values + INTR_TEST IRQ rise "
                f"in {seq.irq_rise_cycles} cycle(s) and clear in "
                f"{seq.irq_fall_cycles}; ATB message read back probe_id "
                f"0x{seq.probe_id_readback:02x} with STATUS "
                f"0x{seq.status_non_empty:08x}. Receivers "
                f"{seq.quiet_receivers_proved} take no ATB stimulus: their "
                f"claim is reset values plus an INTR_ENABLE "
                f"write/readback/restore, not message reception."
            ),
        )
