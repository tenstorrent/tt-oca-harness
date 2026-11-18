# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_remap_attr_rand_test - alias and SEP output remap windows, offsets and AxCACHE, seed-drawn.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_remap_attr_rand_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_remap_attr_rand_test_seq import smu_remap_attr_rand_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_remap_attr_rand_test(smu_base_test):
    """Every remap table at a drawn region: hits, misses at both edges, valid cleared."""

    use_shared_env = True
    required_evidence = (
        "CHK-NONVAC",
        "CHK-RMAPA-CACHE",
        "CHK-RMAPA-EDGE",
        "CHK-RMAPA-OUTPUT",
        "CHK-RMAPA-READBACK",
        "CHK-RMAPA-TRANSLATE",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_remap_attr_rand_test SEP=1 J2A SEP DM SBA")
        seq = smu_remap_attr_rand_test_seq(self)
        await seq.run()
        assert seq.done, "remap attribute scenario incomplete"
