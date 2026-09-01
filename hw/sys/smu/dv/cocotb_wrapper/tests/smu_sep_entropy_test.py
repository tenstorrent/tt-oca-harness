# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP firmware entropy bring-up with the chain proven to deliver."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_entropy_seq import SmuSepEntropySeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_entropy_test(smu_base_test):
    """Require real entropy to reach the DRBG after a firmware bring-up."""

    async def run_scenario(self) -> None:
        await SmuSepEntropySeq(self).run()
