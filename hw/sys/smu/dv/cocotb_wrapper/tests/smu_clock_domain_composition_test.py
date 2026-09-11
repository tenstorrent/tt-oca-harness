# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_clock_domain_composition_test - secondary clock and reset domains (SEP=1).

Closes SMU-CLK-DOMAINS.S2, SMU-CLK-DOMAINS.S3 and SMU-CLK-DOMAINS.S4 against
SMU_SPEC.md "Clock and Reset", on the `--dut smu` production wrapper built with
compile_smu_chiplet_sep_rtl: the telemetry, SEP-watchdog and peripheral clocks
are read at their consumers for identity with the wrapper pins and for a toggle
rate that matches their own period rather than clk_smu_i, their resets are read
released at the consumers, and the SMC cold reset is then asserted through the
DTP IC_RESET override so that the primary and peripheral resets fall while
rst_telemetry_ni stays released and clk_telemetry_i keeps running.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_clock_domain_composition_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_clock_domain_composition_seq import smu_clock_domain_composition_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_clock_domain_composition_test(smu_base_test):
    """Per-domain clock and reset identity, rate and independence from clk_smu_i."""

    use_shared_env = True
    require_distinct_ref_smu = True

    async def run_scenario(self) -> None:
        await smu_clock_domain_composition_seq(self).run()
