# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot the production ROM over the OpenTitan SPI host with the RX FIFO drained by CPU PIO.

The testlist picks the ``build_pio/`` ROM with ``+sep_boot_rom_hex``; the scenario is inherited.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test


@pyuvm.test()
class sep_rom_ot_pio_boot_test(sep_rom_ot_dma_boot_test):
    """Boot over the OT SPI host with the RX FIFO drained by CPU PIO."""
