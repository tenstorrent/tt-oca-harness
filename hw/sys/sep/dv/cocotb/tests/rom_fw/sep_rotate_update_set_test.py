# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ROTATE_UPDATE (``STRAPS_HI[26]``) makes the ROM's first manifest attempt read the backup slot.

The primary slot is erased, so a ROM that ignores the strap still boots by failover;
the checks pin the read order.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# Must match +sep_straps_hi in the testlist entry.
_STRAPS_HI_ROTATE = 0x0400_0000
_ROTATE_UPDATE_BIT = 26

_SPI_PATH_MARKER = "BOOT_SPI"
_STRAPS_HI_ECHO = f"STRAPS_HI=0x{_STRAPS_HI_ROTATE:08x}"
_ROTATE_ECHO = "SPI_ROTATE=1"
_STRAP_ROTATE_ECHO = " rotate=1"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_MANIFEST_OK = "MANIFEST_OK"
# Printed only on the second attempt, so its absence proves the first attempt booted.
_SECOND_ATTEMPT = "MANIFEST_BACKUP"
_ANY_SLOT_ERROR = "MANIFEST_ERR="


@pyuvm.test()
class sep_rotate_update_set_test(sep_rom_ot_dma_boot_test):
    """ROTATE_UPDATE=1 with only 0x41000 programmed: first attempt boots it."""

    # Replaces the parent tuple, which requires the unrotated MANIFEST_SRC=0x00001000.
    required_markers = (
        _SPI_PATH_MARKER, _STRAPS_HI_ECHO, _ROTATE_ECHO, _STRAP_ROTATE_ECHO,
        _BACKUP_SRC, _MANIFEST_OK,
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _PRIMARY_SRC, _SECOND_ATTEMPT, _ANY_SLOT_ERROR, "MANIFEST_ALL_FAILED",
    )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        start, end = mm.erase_slot(buf, "primary")
        assert mm.slot_is_erased(buf, "primary"), (
            "primary slot is not fully erased after erase_slot()"
        )
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-ROTATE: primary span 0x%06x..0x%06x erased to 0x%02x "
            "(%d bytes); the only bootable slot is 0x%06x: %s",
            start, end, mm.ERASED_BYTE, end - start, mm.BACKUP_MANIFEST_OFFSET,
            mm.describe(buf, "backup"),
        )
        assert (_STRAPS_HI_ROTATE >> _ROTATE_UPDATE_BIT) & 1, (
            f"the strap word this test injects (0x{_STRAPS_HI_ROTATE:08x}) does "
            f"not set rotate_update (bit {_ROTATE_UPDATE_BIT})"
        )
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info("CHK-SPI-TXNS:\n%s",
                         ev.summarize(flash.get_transactions(), self._image_len))

    def check_transport(self, console: list[str], flash) -> None:
        rds = ev.reads(flash.get_transactions())
        assert rds, "flash BFM served no read transactions; nothing was fetched over SPI"

        # Use the first read in either slot, not read[0], so an ID probe cannot decide it.
        p_idx = ev.slot_read_indices(rds, "primary", self._image_len)
        b_idx_all = ev.slot_read_indices(rds, "backup", self._image_len)
        assert b_idx_all, (
            f"no read landed in the backup slot span; the rotated slot was never "
            f"fetched. Reads: {[hex(ev.read_span(t)[0]) for t in rds]}"
        )
        first_slot_read = min(p_idx + b_idx_all)
        assert first_slot_read in b_idx_all, (
            f"the first slot read was read[{first_slot_read}], inside the PRIMARY "
            f"span: with rotate_update set the first manifest fetch must be the "
            f"rotated slot at 0x{mm.BACKUP_MANIFEST_OFFSET:06x}"
        )

        assert not p_idx, (
            f"reads {p_idx} landed inside the primary slot span "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:06x}..0x{mm.BACKUP_MANIFEST_OFFSET:06x}: "
            f"the ROM interrogated the unrotated address, so this boot is a "
            f"failover rather than a rotation"
        )

        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert b_hit is not None, (
            f"no SPI read covered 0x{mm.BACKUP_MANIFEST_OFFSET:x}"
        )
        b_idx, b_txn = b_hit
        b_magic = ev.bytes_at(b_txn, mm.BACKUP_MANIFEST_OFFSET, 4)
        assert b_magic == mm.MANIFEST_MAGIC, (
            f"device returned {b_magic!r} at 0x{mm.BACKUP_MANIFEST_OFFSET:x}, "
            f"expected {mm.MANIFEST_MAGIC!r}"
        )
        self.logger.info(
            "CHK-ROTATE-ADDR: first slot read is read[%d] in the rotated slot, "
            "read[%d] returned %r at 0x%06x, and no read touched the primary span",
            first_slot_read, b_idx, b_magic, mm.BACKUP_MANIFEST_OFFSET,
        )
