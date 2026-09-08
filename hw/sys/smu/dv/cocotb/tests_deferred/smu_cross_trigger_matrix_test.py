# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_cross_trigger_matrix_test — DEFERRED (needs_real_lcc / needs SEP=1 / no Force).

Needs a legal TB pin, frontdoor stimulus, or real LCC for the CTM matrix.
Not ported (needs_real_lcc, sep1).
"""

from __future__ import annotations

import pyuvm
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_cross_trigger_matrix_test(smu_base_test):
    """Deferred: needs_real_lcc — requires SEP=1 (SEP=0 ties feat_ctrl='0')."""

    async def run_scenario(self) -> None:
        raise AssertionError("smu_cross_trigger_matrix_test deferred: CTM Force matrix removed.")
