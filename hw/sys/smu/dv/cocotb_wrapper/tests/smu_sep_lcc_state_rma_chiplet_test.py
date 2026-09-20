# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_lcc_state_rma_chiplet_test - one image of the smu_sep_lcc_state_matrix_test body.

RMA_CHIPLET image (`assets/sep_efuse_shadow_lc_rma_chiplet.preload`); feat_ctrl is all-ones by state, so the demote leg is a stay-open check.
The testlist entry supplies the preload image and the contract plusargs; the
body in `smu_sep_lcc_state_matrix_test.py` runs them.
"""

from __future__ import annotations

import pyuvm
from smu_sep_lcc_state_matrix_test import smu_sep_lcc_state_matrix_test


@pyuvm.test()
class smu_sep_lcc_state_rma_chiplet_test(smu_sep_lcc_state_matrix_test):
    """RMA_CHIPLET image (`assets/sep_efuse_shadow_lc_rma_chiplet.preload`)."""
