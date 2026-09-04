# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_ctm_four_phase_test — DEFERRED (needs CT peer / no Force).

Product-pin remap is enrolled as smu_xtrig_ctm_remap_test. Full four-phase
needs DTP-driven src_req or dst_ack (old path Forced internal nets).
Not ported.
"""

from __future__ import annotations

import pyuvm
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xtrig_ctm_four_phase_test(smu_base_test):
    """Deferred: needs_real_stimulus (no Force)."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smu_xtrig_ctm_four_phase_test deferred: CTM src_req/dst_ack Force inject removed. "
            "Not ported (needs_real_stimulus)."
        )
