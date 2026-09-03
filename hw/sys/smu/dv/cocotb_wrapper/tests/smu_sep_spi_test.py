# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run the SEP OpenTitan SPI controller sequence under the OSS SMU wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_spi_seq import SmuSepSpiSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_spi_test(smu_base_test):
    """Require the SEP SPI transfer to clear every stage on-chip."""

    async def run_scenario(self) -> None:
        await SmuSepSpiSeq(self).run()
