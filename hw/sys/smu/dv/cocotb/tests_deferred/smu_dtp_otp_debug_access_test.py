# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_otp_debug_access_test — DEFERRED (needs_real_lcc / needs SEP=1 / no Force).

Was: OTP lifecycle Force. Re-enable with legal TB pin / frontdoor / real LCC.
See testlists/deferred.toml (needs_real_lcc, sep1).
"""

from __future__ import annotations

import pyuvm
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_otp_debug_access_test(smu_base_test):
    """Deferred: needs_real_lcc — requires SEP=1 (SEP=0 ties feat_ctrl='0')."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smu_dtp_otp_debug_access_test deferred: OTP lifecycle Force removed. See testlists/deferred.toml."
        )
