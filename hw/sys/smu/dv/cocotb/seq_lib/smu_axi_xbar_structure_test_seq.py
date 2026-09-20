# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP=0 elaboration: smu_axi_xbar must be absent (FAB_SMU_003 / Nightly).

Positive control: gen_no_sep IW converters resolve. Then u_smu_axi_xbar must
not exist under that generate arm. Does not drive the crossbar.
"""

from __future__ import annotations

import cocotb

from seq_lib.smu_compose_helpers import GenerateScope
from seq_lib.smu_tb_pins import smu_scope


class smu_axi_xbar_structure_test_seq:
    """Hierarchy-only: gen_no_sep converters present, xbar absent."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.pos_ok = False
        self.absent_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard
        wrap = smu_scope(dut)
        smu = wrap.u_smu if hasattr(wrap, "u_smu") else wrap
        sb.expect_true(
            "CHK-XBAR-POS-NO-GEN-SEP: gen_sep absent under SEP=0",
            not GenerateScope(smu, "gen_sep").exists(),
            evidence="CHK-XBAR-POS-NO-GEN-SEP",
        )
        gen = GenerateScope(smu, "gen_no_sep")
        if not gen.exists():
            raise AssertionError(f"missing hierarchical child gen_no_sep under {smu}")
        in_ok = gen.has("u_iw_conv_smc_in")
        out_ok = gen.has("u_iw_conv_smc_out")
        sb.expect_true(
            "CHK-XBAR-POS-IW: gen_no_sep u_iw_conv_smc_in/out resolve",
            in_ok and out_ok,
            evidence="CHK-XBAR-POS-IW",
        )
        self.pos_ok = in_ok and out_ok
        self._log("CHK-XBAR-POS: gen_no_sep u_iw_conv_smc_in/out resolve under SEP=0")

        xbar_present = gen.has("u_smu_axi_xbar")
        sb.expect_true(
            "CHK-XBAR-ABSENT-NO-SEP: smu_axi_xbar absent under gen_no_sep",
            not xbar_present,
            evidence="CHK-XBAR-ABSENT-NO-SEP",
        )
        self.absent_ok = not xbar_present
        self._log("CHK-XBAR-ABSENT-NO-SEP: smu_axi_xbar absent; gen_no_sep is direct SMC<->ext")
