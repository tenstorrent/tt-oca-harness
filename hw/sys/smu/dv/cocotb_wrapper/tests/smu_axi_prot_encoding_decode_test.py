# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_prot_encoding_decode_test — SMU Tier A AxPROT S9 (SEP=1 J2A + s_axi)."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_prot_encoding_decode_test_seq import (
    smu_axi_prot_encoding_decode_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_prot_encoding_decode_test(smu_base_test):
    """Inbound allow_ns=0 eight-way AxPROT (S9); S1–S8 need sep_in_master."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_axi_prot_encoding_decode_test TierA S9 SEP=1 J2A")
        seq = smu_axi_prot_encoding_decode_test_seq(self)
        await seq.run()
        assert seq.matrix_ok, "S9 AxPROT matrix incomplete"
