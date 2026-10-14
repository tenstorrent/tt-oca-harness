# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_reset_release_sync_test - reset deassertion synchronization.

Measured against `hw/sys/smu/doc/port_table.adoc`: the `rst_cold_ni` row states "Asynchronous assertion, synchronous
deassertion", and the `rst_cold_stable_ref_clk_no` / `rst_primary_ref_clk_no` /
`rst_primary_smc_clk_no` rows name the domain each output is synchronized to.
Those two statements are what the checks below require,
on the `--dut smu` production wrapper built with compile_smu_chiplet:
rst_cold_ni is released at a random phase that lies on no clock edge, and the
deassertion of rst_cold_stable_ref_clk_no and rst_primary_ref_clk_no is
required to land on a clk_ref_i rising edge while the SMC and DTP primary-reset
inputs deassert together on a clk_smu_i rising edge, none at the release
instant.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_reset_release_sync_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_reset_release_sync_seq import smu_reset_release_sync_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_reset_release_sync_test(smu_base_test):
    """Cold and primary reset deassertions are clock-edge aligned."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_reset_release_sync_seq(self).run()
