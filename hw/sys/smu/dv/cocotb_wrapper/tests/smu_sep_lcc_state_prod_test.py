# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_lcc_state_prod_test - one image of the smu_sep_lcc_state_matrix_test body.

PROD image (`assets/sep_efuse_shadow_lc_prod.preload`); the discriminating closed-to-open demote case.
The testlist entry supplies the preload image and the contract plusargs; the
body in `smu_sep_lcc_state_matrix_test.py` runs them.
"""

from __future__ import annotations

import pyuvm
from smu_sep_lcc_state_matrix_test import smu_sep_lcc_state_matrix_test


@pyuvm.test()
class smu_sep_lcc_state_prod_test(smu_sep_lcc_state_matrix_test):
    """PROD image (`assets/sep_efuse_shadow_lc_prod.preload`)."""
