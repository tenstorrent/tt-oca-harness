# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_secure_tm_test - the SEP secure test-mode strap.

secure_tm_req_i is a strap the SEP eFuse wrapper samples once per cold reset,
at the rising edge of its fuse-sense-done, and secure_tm_o is that sample. The
leaf drives the strap through three cold resets at two different values and
requires the output to carry the sampled value and to ignore the strap between
sampling windows, which is what separates a latch from a wire.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sep_secure_tm_test --target compile_smu_chiplet_sep_rtl
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_secure_tm_seq import smu_sep_secure_tm_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_secure_tm_test(smu_base_test):
    """secure_tm_req_i sampled into secure_tm_o across cold reset."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_sep_secure_tm_seq(self).run()
