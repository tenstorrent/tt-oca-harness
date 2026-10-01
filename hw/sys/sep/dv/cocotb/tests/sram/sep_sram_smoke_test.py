# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP SRAM smoke test over the CPU LSU AXI path."""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_sram_smoke_seq import sep_sram_smoke_seq


@pyuvm.test()
class sep_sram_smoke_test(sep_base_test):
    """Write/read the OSS behavioral SRAM responder through SEP's local fabric."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        seq = sep_sram_smoke_seq("sram_smoke_seq")
        await self.start_seq(seq)
