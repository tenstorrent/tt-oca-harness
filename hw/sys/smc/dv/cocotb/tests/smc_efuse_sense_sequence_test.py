# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_011 ANCHOR: smc_efuse_sense_sequence_test
# DV-TESTCASE-CONTRACT-REVISION: 3 RECORD-SHA256: 105f1cdf375d81c7f7bb3ce5e131696ec9fde34e522301505090a3d3c177a711
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/docs/SMC_VPLAN.adoc section 467 `smc_efuse_sense_sequence_test` ENV: cocotb
"""Automatic fuse sense sequence after a deliberate cold reset.

Sources: smu-smc.adoc (eFuse Interface), efuse_interface_ctrl.rdl, efuse architecture.adoc.

Also reads one SMC_EFUSE_MAP shadow register, chosen non-zero on the fuse image, before the
cold reset, during the strobe stream and after sense done.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib._one_shot import _OneShot
from seq_lib.smc_efuse_sense_sequence_test_seq import smc_efuse_sense_sequence_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_sense_sequence_test(smc_base_test):
    """Observe the request, the 256 strobes, sense done and the hand-over per clock edge,
    with one shadow register read before, during and after the sense."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-SENSE-DONE-LOW",
        "CHK-SENSE-DONE-OFFSET",
        "CHK-SENSE-REQ-HANDOVER",
        "CHK-SENSE-REQ-LATENCY",
        "CHK-SENSE-SHADOW-POSTSENSE",
        "CHK-SENSE-SHADOW-PRESENSE",
        "CHK-SENSE-STROBE-COUNT",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_sense_sequence_test_seq("smc_efuse_sense_sequence_test_seq")

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
                "per-edge sampling of the sense request, response strobes and sense done after "
                "a cold reset with STATUS polled over SEP_IN (eFuse bank is the DV model)"
            ),
        )
