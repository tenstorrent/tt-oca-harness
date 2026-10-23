# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_W2T_010 ANCHOR: smc_gpio_pad_enable_walk_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 3d0201cf329d14595dccfaef9bf57982d71c8c9d54c10481ce90dda0da37d9b6
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_W2T_VPLAN_DETAIL_ADDITIONS.md @ artifact_revision 4 ENV: cocotb
"""GPIO DATA_CTRL / DATA_CTRL_ENABLE per-pad control observed at 56 pads.

Every GPIO interface the bench does not drive itself takes a DATA_CTRL field
walk, TX output and enable, the three direction encodings, RX capture into
pad2core from a bench pad drive, interface_enable clear, and the three
use_reg_* overrides; each pad is observed through `tb_core2pad_o`,
`tb_core2pad_en_o` and `tb_pad2core_en_o`, and every register is restored.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_gpio_pad_enable_walk_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_pad_enable_walk_test_seq import (
    CHECKERS,
    WALKED_COUNT,
    smc_gpio_pad_enable_walk_test_seq,
)
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-GPIO-DIR",
    "CHK-GPIO-FIELD-RB",
    "CHK-GPIO-IFACE-CLEAR",
    "CHK-GPIO-RX-IN",
    "CHK-GPIO-TX-OUT",
    "CHK-GPIO-USE-REG",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_gpio_pad_enable_walk_test(smc_base_test):
    """Per-pad DATA_CTRL / DATA_CTRL_ENABLE control walked on 56 GPIO pads."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_pad_enable_walk_test_seq("smc_gpio_pad_enable_walk_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert len(seq.walked) == WALKED_COUNT, f"{len(seq.walked)} pads walked"
        assert sorted(CHECKERS) == list(REQUIRED), "checker set differs from required_evidence"
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
