# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP ROM boot over the OpenTitan SPI host, CPU PIO drain (PyUVM).

Same ROM sources, ``spi_host``, flash image and PASS criteria as
``sep_rom_ot_dma_boot_test``; only the RX FIFO drain differs. ``boot_flash.h`` selects it
at build time:

    BOOT_OT_SPI_USE_PIO=0  ->  ot_spi_flash_read_dma()  (SECURE_DMA handshake)
    BOOT_OT_SPI_USE_PIO=1  ->  ot_spi_flash_read()      (CPU programmed I/O)

The PIO path has the CPU poll FIFO status and copy words, and ``build_pio/boot_rom.elf``
does not link ``ot_spi_flash_read_dma``, so the DMA test cannot cover this code.

The testlist selects the ``build_pio/`` ROM through ``+sep_boot_rom_hex``; the scenario and
checks are inherited unchanged.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test


@pyuvm.test()
class sep_rom_ot_pio_boot_test(sep_rom_ot_dma_boot_test):
    """Boot over the OT SPI host with the RX FIFO drained by CPU PIO."""
