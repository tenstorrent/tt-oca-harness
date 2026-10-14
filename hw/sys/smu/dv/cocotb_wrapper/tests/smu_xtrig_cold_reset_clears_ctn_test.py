# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_cold_reset_clears_ctn_test - cold reset across the cross-trigger network.

Spec: dtp/doc/clk_rst.adoc, cross_trigger_port/doc/architecture.adoc, CTN/CTM/CTP RDL resets.
The SMU cold reset returns the programmed CTN registers to their RDL reset values, clears a
point-to-point request in REQ_ASSERTED and WAIT_ACK_DEASSERT, and holds dtp_stop_clks_o low.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xtrig_cold_reset_clears_ctn_test_seq import (
    smu_xtrig_cold_reset_clears_ctn_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xtrig_cold_reset_clears_ctn_test(smu_base_test):
    """CTN registers, CTP sender and clock-stop output across the SMU cold reset."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_xtrig_cold_reset_clears_ctn_test_seq(self).run()
