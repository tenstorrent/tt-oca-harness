# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""# deferred: no_dut_port
captured_straps_i to reset_unit STRAPS_LO/HI — DEFERRED.

`smc_wrapper` declares no `captured_straps_i` port, so `tb_top.sv` exports no
`tb_captured_straps` tap and the sequence has nothing to drive. It asserts on
the missing tap rather than passing, so the testcase cannot go green while the
stimulus does not exist. Enroll it when the wrapper carries the strap pins.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_captured_straps_test_seq import smc_captured_straps_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_captured_straps_test(smc_base_test):
    """Product strap pin; not the GPIO IRQ sibling."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_captured_straps_test_seq("captured_straps_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.idle_ok and seq.pat_a_ok and seq.pat_b_ok, (
            f"straps incomplete idle={seq.idle_ok} a={seq.pat_a_ok} b={seq.pat_b_ok}"
        )
