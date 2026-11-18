# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xbar_aperture_edge_burst_test - ext_in bursts across the SMU crossbar aperture edges.

The crossbar decodes a transaction on its first address against [base,
base + size) in a 57-bit sum (``hw/sys/smu/doc/index.adoc``, "SMU aperture
decode and routing"), so a multi-beat burst whose later beats leave the window
goes whole to the subordinate its first address selects. On the ``--dut smu``
production wrapper built with compile_smu_chiplet the SEP aperture is placed
over the SEP debug system bus at an unaligned base and size, at the carry edge
of the address space, wider than the SEP inbound space and adjacent to the SMC
window; the ext_in master issues single beats and INCR, WRAP and FIXED bursts
at each edge, and the leaf grades the port each one is counted at, the beat
count, RLAST, the write beats and the single write response. The leaf runs on
VCS only: it reads the crossbar target-port checker inputs by hierarchy.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_xbar_aperture_edge_burst_test --target compile_smu_chiplet --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xbar_aperture_edge_burst_test_seq import (
    STEPS,
    smu_xbar_aperture_edge_burst_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xbar_aperture_edge_burst_test(smu_base_test):
    """Bursts and singles at aperture edges are routed whole to one subordinate; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "INFO-DUT_TAG=WRAPPER smu_xbar_aperture_edge_burst_test SEP=1 aperture edge bursts"
        )
        seq = smu_xbar_aperture_edge_burst_test_seq(self)
        await seq.run()
        steps = tuple(seq.steps.get(step, False) for step in STEPS)
        assert all(steps), f"aperture edge burst incomplete s1..s11={steps}"
