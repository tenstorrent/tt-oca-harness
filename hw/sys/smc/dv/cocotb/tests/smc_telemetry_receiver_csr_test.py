# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS TELEMETRY_RECEIVER 0/1/2 CSR precheck."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_telemetry_atb_capture_test_seq import BUFFER_EMPTY_BM, _word
from seq_lib.smc_telemetry_receiver_csr_test_seq import (
    RX_BEATS,
    smc_telemetry_receiver_csr_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_receiver_csr_test(smc_base_test):
    """U4-6: TELEMETRY CSR reset, INTR_TEST -> tb_telemetry_irq_any, one beat per receiver."""

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
        want = _word(RX_BEATS[0])
        assert seq.rx_data.get(0) == want, (
            f"TELEMETRY_0 TELEMETRY_DATA read back {seq.rx_data.get(0)!r}; the ATB beat this "
            f"testcase sent reads as 0x{want:08x}"
        )
        assert not (seq.rx_status[0] & BUFFER_EMPTY_BM), (
            f"TELEMETRY_0 STATUS still reports EMPTY (0x{seq.rx_status[0]:08x}) after the ATB beat"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            # Structural CSR-access floor for the declared stimulus, written out
            # here as an independent constant. The reset sweep alone is 18 reads
            # (3 receivers x 6 register types); the receiver 1/2 INTR_ENABLE
            # write/readback/restore legs add 8; the receiver 0 IRQ leg and the
            # three ATB beat legs add the remainder. A run that stopped after
            # the sweep fails this floor.
            min_csr_accesses=40,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "U4-6: TELEMETRY receivers 0-2 reset values + INTR_TEST IRQ rise "
                f"in {seq.irq_rise_cycles} cycle(s) and release in "
                f"{seq.irq_fall_cycles}; receivers {seq.quiet_receivers_proved} stored "
                "INTR_ENABLE; each receiver read back its own ATB beat through "
                "TELEMETRY_DATA: "
                + ", ".join(f"rx{rx}=0x{seq.rx_data[rx]:08x}" for rx in sorted(seq.rx_data))
            ),
        )
