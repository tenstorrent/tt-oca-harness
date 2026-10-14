# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Delayed fuse reset gating on fuse sense done and ext_boot_seq_done_i.

Sources: port_table.adoc, clk_rst.adoc, smu-smc.adoc (eFuse Interface).
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib._one_shot import _OneShot
from seq_lib.smc_efuse_fuse_reset_gate_test_seq import smc_efuse_fuse_reset_gate_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_fuse_reset_gate_test(smc_base_test):
    """Observe smc_fuse_reset_n_delayed_o per clock edge against sense done and ext_boot."""

    required_evidence = (
        "CHK-FRST-16-STAGE",
        "CHK-FRST-BOOT-DROP",
        "CHK-FRST-COLD-REARM",
        "CHK-FRST-EARLY-BOOT",
        "CHK-FRST-HELD-LOW",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_fuse_reset_gate_test_seq("smc_efuse_fuse_reset_gate_test_seq")

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
                "per-edge sampling of the delayed fuse reset against sense done and the boot "
                "gate across cold resets with STATUS polled over SEP_IN (eFuse bank is the DV "
                "model)"
            ),
        )
