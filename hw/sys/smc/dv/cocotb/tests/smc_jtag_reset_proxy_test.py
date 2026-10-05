# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS JTAG-adjacent reset pin-level test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib._one_shot import _OneShot
from seq_lib.smc_jtag_reset_proxy_test_seq import smc_jtag_reset_proxy_test_seq
from seq_lib.smc_jtag_vip_utils import check_cpu_jtag_pin_vip
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_reset_proxy_test(smc_base_test):
    """Run JTAG-adjacent CSR health checks plus CPU JTAG pin checks."""

    required_evidence = (
        "CHK-CPU-JTAG-DTMCS",
        "CHK-CPU-JTAG-IDCODE",
        "CHK-CPU-JTAG-SCAN-ACTIVITY",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_reset_proxy_test_seq("jtag_reset_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_cpu_jtag_pin_vip()
        # The reset-proxy CSR reads carry expected values, so require the
        # scoreboard to have compared them: otherwise a run that lost the
        # SEP_IN analysis path would skip every compare and still pass.
        assert self.env.scoreboard.sys_axi_value_checks_seen >= 5, (
            "fewer than 5 SEP_IN AXI value compares reached the scoreboard: the "
            "CHIP_CONFIG / SCRATCH_COLD expectations across the cool reset were "
            "not checked"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            # The scoreboard's own per-bus tally, stamped by the driver that
            # completed each access, rather than `seq.accesses`, which the
            # sequence increments on dispatch regardless of what came back.
            csr_accesses=self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0),
            # Directed stimulus floor: 8 SEP_IN AXI JTAG reset-proxy CSR
            # accesses. Literal here, not read from `seq.accesses`.
            min_csr_accesses=8,
            proxy=True,
            details=(
                "CPU JTAG TCK/TMS/TDI/reset driven and TDO checked; cool reset "
                "observed asserted and released, SCRATCH_COLD_2 cleared to its "
                "generated reset by it, and writable again afterwards"
            ),
        )
