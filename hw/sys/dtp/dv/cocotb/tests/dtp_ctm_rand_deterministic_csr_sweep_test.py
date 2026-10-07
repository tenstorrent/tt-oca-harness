# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_ctm_rand_deterministic_csr_sweep_test`."""

import pyuvm
from dtp_xtrig_base_test import dtp_xtrig_base_test
from env.dtp_types import DTP_FEATURE_XTRIG_CSR, DTP_FEATURE_XTRIG_DECODE
from seq_lib.dtp_xtrig_csr_test_seq import dtp_xtrig_csr_test_seq


@pyuvm.test()
class dtp_ctm_rand_deterministic_csr_sweep_test(dtp_xtrig_base_test):
    required_features = (DTP_FEATURE_XTRIG_CSR, DTP_FEATURE_XTRIG_DECODE)

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_xtrig_csr_test_seq,
            "ctm_csr_sweep",
            scenario="ctm_csr_sweep",
            specific_knob="DTP_CTM_RAND_DETERMINISTIC_CSR_SWEEP_TEST_LOOPS",
            group_knob="DTP_XTRIG_TEST_LOOPS",
        )
