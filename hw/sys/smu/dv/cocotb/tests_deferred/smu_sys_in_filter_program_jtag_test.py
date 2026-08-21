# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sys_in_filter_program_jtag_test — DEFERRED (needs_real_lcc / needs SEP=1 / no Force).

Was Force-based JTAG2AXI / feat_ctrl ungating under SEP=0. Use
smu_lcc_helpers + SEP=1 eFuse LCC when available (#3538).
See testlists/deferred.toml (needs_real_lcc, sep1).
"""

from __future__ import annotations

import pyuvm

from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sys_in_filter_program_jtag_test(smu_base_test):
    """Deferred: needs_real_lcc — requires SEP=1 (SEP=0 ties feat_ctrl='0')."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smu_sys_in_filter_program_jtag_test deferred: Force ungating removed. "
            "Needs SEP=1 (gen_no_sep ties feat_ctrl='0'); use eFuse→LCC + smu_lcc_helpers. "
            "See testlists/deferred.toml (needs_real_lcc, sep1)."
        )
