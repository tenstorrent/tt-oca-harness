# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_i3c_mem_port_connectivity_test — FAB_SMC_031 local peripheral delivery."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_i3c_mem_port_connectivity_test_seq import (
    smu_i3c_mem_port_connectivity_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_i3c_mem_port_connectivity_test(smu_base_test):
    """FAB_SMC_031 delivery-only via J2A; no Force / no sep_in."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_i3c_mem_port_connectivity_test TierC FAB_SMC_031 SEP=1 J2A"
        )
        seq = smu_i3c_mem_port_connectivity_test_seq(self)
        await seq.run()
        assert seq.s1_ok and len(seq.observed) == 5, (
            f"i3c_mem incomplete s1={seq.s1_ok} observed={seq.observed}"
        )
