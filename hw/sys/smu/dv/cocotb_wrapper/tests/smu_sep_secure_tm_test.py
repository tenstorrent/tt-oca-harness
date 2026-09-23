# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_secure_tm_test - the SEP secure test-mode strap.

secure_tm_req_i is the TEST_EN strap the SEP latches into secure_tm_o once per
cold reset, when fuse sensing is done (hw/sys/sep/doc/test_mode.adoc). The leaf
runs three cold resets; in each the strap is changed while the reset is held,
after the SEP reset and sep_fuse_sense_done_o are observed low, and the output
is required to stay low until the fuse-sense-done edge, to carry the changed
value after it -- not the value present when the reset asserted -- and to
ignore the strap between sampling windows in both directions.

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
