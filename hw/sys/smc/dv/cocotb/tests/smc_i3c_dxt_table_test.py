# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DAT and DCT accesses on every I3C instance through its CSR window.

On each of the six I3C instances, DAT entry 0 is written with a pattern of its
own over the fields `DAT_structure.rdl` declares, and all six are read back
after all six are written. Each entry is then restored. DCT entry 0, which only
dynamic address assignment writes, is read twice on every instance, and the two
reads must agree.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i3c_dxt_table_test_seq import smc_i3c_dxt_table_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i3c_dxt_table_test(smc_base_test):
    """Write/read the DAT and read the DCT of all six I3C instances."""

    required_evidence = (
        "CHK-I3C-DAT-TABLE-RW",
        "CHK-I3C-DCT-TABLE-READ",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i3c_dxt_table_test_seq("smc_i3c_dxt_table_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dat_checked == 6, f"{seq.dat_checked} DAT entries checked, expected 6"
        assert seq.dct_checked == 6, f"{seq.dct_checked} DCT entries checked, expected 6"
