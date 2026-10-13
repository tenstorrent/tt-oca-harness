# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_debug_control_fields_test - PTAP DEBUG_CONTROL fields through the SMU primary TAP.

Contract: SMU_MISC_XTRIG_019, anchor smu_dtp_debug_control_fields_test.
Spec: jtag_ptap/doc/architecture.adoc (PTAP DEBUG_CONTROL fields), dtp/doc/clk_rst.adoc (Clock Stop).
Bits 3:0 store the shifted-in value and reset to 0, bit 4 ignores shifted-in data and follows the
clock-stop request, and TRST, Test-Logic-Reset and power-on reset clear jtag_clock_stop.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_debug_control_fields_test_seq import smu_dtp_debug_control_fields_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_debug_control_fields_test(smu_base_test):
    """DEBUG_CONTROL reset values, storage, read-only bit 4, stop latency and reset clearing."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_dtp_debug_control_fields_test_seq(self).run()
