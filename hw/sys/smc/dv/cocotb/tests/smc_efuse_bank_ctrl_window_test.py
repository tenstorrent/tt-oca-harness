# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SHIM control window forwarding and efuse_bank_ctrl per-channel handshake counts.

Sources: smu-smc.adoc (eFuse Interface), efuse_shim_ctrl.rdl, efuse_interface_ctrl.rdl.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib._one_shot import _OneShot
from seq_lib.smc_efuse_bank_ctrl_window_test_seq import smc_efuse_bank_ctrl_window_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_bank_ctrl_window_test(smc_base_test):
    """Count bank-control channel edges for idle traffic, window reads, writes and re-sense."""

    required_evidence = (
        "CHK-BANKCTRL-IDLE",
        "CHK-WINDOW-READ",
        "CHK-WINDOW-WRITE",
        "CHK-BANKCTRL-ORDER",
        "CHK-INITTIME-RESENSE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_bank_ctrl_window_test_seq("smc_efuse_bank_ctrl_window_test_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= seq.access_floor, (
            f"{seq.accesses} SEP_IN accesses, the sequence computed a floor of {seq.access_floor}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            min_csr_accesses=seq.access_floor,
            csr_accesses=self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0),
            proxy=False,
            details=(
                "SHIM control window reads and writes with efuse_bank_ctrl channel edge counts "
                "(eFuse bank is the DV model)"
            ),
        )
