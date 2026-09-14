# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP CLA-debug consumer and SMC producer under the SMU wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_cla_sep_cpu_debug_seq import SmuClaSepCpuDebugSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_cla_sep_cpu_debug_test(smu_base_test):
    """Classify the CLA-debug pair by the SEP terminal loop."""

    async def run_scenario(self) -> None:
        await SmuClaSepCpuDebugSeq(self).run()
