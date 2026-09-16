# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_ext_axi_global_addr_smoke_test — SMU Tier A LOCAL↔GLOBAL equivalence.

The OSS `s_axi` is a LOCAL aperture (`0xC000_xxxx`), so `GLOBAL_BASE + offset`
returns DECERR; the GLOBAL leg needs a system-view master or the remap path.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_ext_axi_global_addr_smoke_test_seq import (
    smu_ext_axi_global_addr_smoke_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_ext_axi_global_addr_smoke_test(smu_base_test):
    """FAB_SMC_007 via J2A local + s_axi global; no Force / no sep_in."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_ext_axi_global_addr_smoke_test TierA FAB_SMC_007 SEP=0 J2A+s_axi"
        )
        seq = smu_ext_axi_global_addr_smoke_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok, f"global_addr incomplete s1={seq.s1_ok} s2={seq.s2_ok}"
