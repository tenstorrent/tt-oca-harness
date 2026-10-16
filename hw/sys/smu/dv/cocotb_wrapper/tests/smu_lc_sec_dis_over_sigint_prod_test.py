# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_lc_sec_dis_over_sigint_prod_test - a PROD security-disable match opens every debug path.

Spec: hw/sys/sep/doc/security_disable.adoc, hw/sys/sep/doc/lifecycle_controller.adoc.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_lc_sec_dis_over_sigint_prod_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_lc_sec_dis_over_sigint_prod_test_seq import (
    smu_lc_sec_dis_over_sigint_prod_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_lc_sec_dis_over_sigint_prod_test(smu_base_test):
    """A token match in PROD opens the debug paths and keeps them open under a sigint injection."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_lc_sec_dis_over_sigint_prod_test SEP=1 "
            "PROD token match over an integrity error"
        )
        await smu_lc_sec_dis_over_sigint_prod_test_seq(self).run()
