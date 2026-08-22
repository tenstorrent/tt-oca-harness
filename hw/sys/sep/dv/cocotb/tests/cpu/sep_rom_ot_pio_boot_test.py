# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP ROM boot over the OpenTitan SPI host, CPU PIO drain (PyUVM).

The drain-method sibling of ``sep_rom_ot_dma_boot_test``: same production Boot
ROM sources, same OpenTitan ``spi_host``, same flash image and same PASS
criteria. The only difference is how the bytes leave the controller's RX FIFO.

``boot_flash.h`` picks that at build time, so the two are separate ROM binaries
rather than a runtime switch:

    BOOT_OT_SPI_USE_PIO=0  ->  ot_spi_flash_read_dma()  (SECURE_DMA handshake)
    BOOT_OT_SPI_USE_PIO=1  ->  ot_spi_flash_read()      (CPU programmed I/O)

Why this test exists as its own entry rather than a variant of the DMA one: the
two read the same bytes but reach them through different hardware. The DMA path
arms the secure DMA and waits on an RX-watermark trigger; the PIO path has the
CPU poll the FIFO status and copy words itself. A regression in either is
invisible to the other, and ``build_ot_pio/boot_rom.elf`` does not even contain
``ot_spi_flash_read_dma`` -- the linker drops it -- so the DMA test genuinely
cannot cover this code.

Everything else is inherited. This subclass exists to redirect the ROM images at
``build_ot_pio/``; the scenario, the flash BFM wiring and the BOOT_SPI /
WAIT_SMC_MANIFEST path assertions all come from the parent, which is the point of
keeping those as class data there.
"""

from __future__ import annotations

import os

import pyuvm

from cpu.sep_rom_ot_dma_boot_test import _ROM_DIR, sep_rom_ot_dma_boot_test


@pyuvm.test()
class sep_rom_ot_pio_boot_test(sep_rom_ot_dma_boot_test):
    """Boot over the OT SPI host with the RX FIFO drained by CPU PIO."""

    # Must stay in step with +sep_boot_rom_hex in the testlist, which points at
    # this same directory's boot_rom.vmem.
    rom_build_dir = os.path.join(_ROM_DIR, "build_ot_pio")
