# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_efuse_reg_sanity_test — DEFERRED (needs_real_lcc / needs SEP=1 / no Force).

Needs SEP=1 eFuse LCC ungating through smu_lcc_helpers; SEP=0 ties
feat_ctrl='0'.
Not ported (needs_real_lcc, sep1).
"""

from __future__ import annotations

import pyuvm
from smu_base_test import smu_base_test


@pyuvm.test()
class smc_efuse_reg_sanity_test(smu_base_test):
    """Deferred: needs_real_lcc — requires SEP=1 (SEP=0 ties feat_ctrl='0')."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_efuse_reg_sanity_test deferred: Force ungating removed. "
            "Needs SEP=1 (gen_no_sep ties feat_ctrl='0'); use eFuse→LCC + smu_lcc_helpers. "
            "Not ported (needs_real_lcc, sep1)."
        )
