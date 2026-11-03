# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xbar_decerr_burst_response_test - multi-beat ext_in decode errors from the SMU crossbar.

An ext_in request that matches neither aperture is answered by the crossbar
itself with DECERR and reaches no subordinate (`hw/sys/smu/doc/index.adoc`,
"SMU aperture decode and routing"). On the `--dut smu` production wrapper
built with compile_smu_chiplet the ext_in master issues single-beat and burst
INCR, WRAP and FIXED reads and writes outside both apertures and at the bit-55
alias of the SMC window, and the leaf grades the beat count, RLAST, write-beat
acceptance, the single write response, the ID echo, the absence of a side
effect and the responder's recovery from held read data. The four-state AXI
rules and the need gates grade on VCS only.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_xbar_decerr_burst_response_test --target compile_smu_chiplet --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xbar_decerr_burst_response_test_seq import (
    smu_xbar_decerr_burst_response_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xbar_decerr_burst_response_test(smu_base_test):
    """ext_in misses get the full AXI4 DECERR response shape from the crossbar; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "INFO-DUT_TAG=WRAPPER smu_xbar_decerr_burst_response_test SEP=1 ext_in miss column"
        )
        seq = smu_xbar_decerr_burst_response_test_seq(self)
        await seq.run()
        steps = tuple(seq.steps.get(f"S{i}", False) for i in range(1, 10))
        assert all(steps), f"decerr burst response incomplete s1..s9={steps}"
