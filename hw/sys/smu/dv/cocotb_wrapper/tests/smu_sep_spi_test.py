# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run the SEP OpenTitan SPI host transfer under the OSS SMU wrapper, graded at the SMC pads."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_spi_seq import SmuSepSpiSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_spi_test(smu_base_test):
    """Require the SEP SPI transfer to clear on-chip and to reach the SMC pads as mapped."""

    async def run_scenario(self) -> None:
        await SmuSepSpiSeq(self).run()
