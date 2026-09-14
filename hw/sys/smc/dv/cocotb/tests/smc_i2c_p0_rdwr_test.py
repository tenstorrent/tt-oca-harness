# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 host to I2C1 target on shared pads (+smc_i2c_shared_bus)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_p0_rdwr_test_seq import smc_i2c_p0_rdwr_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_p0_rdwr_test(smc_base_test):
    """Commercial P0 intent: internal dual-controller write/read proof."""

    required_evidence = (
        "CHK-I2C-P0-RDWR-READ",
        "CHK-I2C-P0-RDWR-WRITE",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_p0_rdwr_test_seq("i2c_p0_rdwr_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.transfer_ok, "I2C0→I2C1 P0 write transfer did not complete"
        # Both directions, because the claim names both. Without this the read
        # half could be dropped from the sequence and nothing would notice.
        assert seq.read_ok, "I2C0←I2C1 P0 read transfer did not complete"
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`.
            # It sits above what the write leg alone can issue (its ACQ drain
            # polls vary with timing) and below what a full run issues: the read
            # leg adds five unconditional writes -- two FIFO resets, the target TX
            # preload and the two FDATA entries -- plus at least two host-idle
            # polls and two RX polls, so the floor cannot be met by the write leg
            # alone and poll variance cannot make it flaky.
            min_csr_accesses=45,
            # The scoreboard's own per-bus tally, stamped by the driver that
            # completed each access, rather than `seq.accesses`, which the
            # sequence increments on dispatch regardless of what came back.
            csr_accesses=self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0),
            proxy=False,
            details=(
                "I2C0 host write to I2C1 target and read back on shared pads; "
                f"ACQ_words={[hex(w) for w in seq.acq_words[:5]]} "
                f"write_ok={seq.transfer_ok} read_ok={seq.read_ok}"
            ),
        )
