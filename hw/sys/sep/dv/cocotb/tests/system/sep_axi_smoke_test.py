# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP no-CPU AXI smoke test (PyUVM)."""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_axi_smoke_seq import sep_axi_smoke_seq


@pyuvm.test()
class sep_axi_smoke_test(sep_base_test):
    """SEP no-CPU AXI smoke: read SEP_LOCAL_BASE_ADDR and write/read-back four
    SEP_CPU_CTRL registers over the CPU LSU bus."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        seq = sep_axi_smoke_seq("smoke_seq")
        await self.start_seq(seq)
