# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_ctp_pad_test - cross-trigger port pads at the SMU boundary.

The DTP cross-trigger network owns all four CTP pad groups of smu_wrapper.
This leaf programs it through the SMC peripheral window: it checks the wire-OR
pad directions it resets to and the five outputs the network ties off, swaps
one lane to point-to-point and checks the enables move on that lane alone,
runs the four-phase handshake in both directions, and routes a trigger through
the cross trigger matrix to a second port and to an internal cross-trigger
lane at xtrig_ctm_src_req_o.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_xtrig_ctp_pad_test --target compile_smu_chiplet_no_sep
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xtrig_ctp_pad_seq import smu_xtrig_ctp_pad_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xtrig_ctp_pad_test(smu_base_test):
    """CTP pad direction, handshake and matrix routing at the SMU pads."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_xtrig_ctp_pad_seq(self).run()
