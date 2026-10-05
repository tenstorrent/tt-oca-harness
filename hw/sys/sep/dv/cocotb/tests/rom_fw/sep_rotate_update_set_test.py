# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The ROTATE_UPDATE strap swaps the order in which the ROM tries the manifest slots.

``STRAPS_HI[26]`` makes ``rom_manifest_boot()`` (``oca_boot.c``) rotate the slot index,
so the first attempt reads ``BACKUP_MANIFEST_OFFSET`` (0x41000) and prints
``MANIFEST_BACKUP``; the label follows the slot. The primary slot is erased, so a ROM that
ignored the strap would still boot after a BAD_MAGIC failover. The order is therefore
asserted three ways: ``MANIFEST_SRC=0x00041000`` appears and ``MANIFEST_SRC=0x00001000``
does not; ``MANIFEST_BACKUP`` appears and ``MANIFEST_PRIMARY`` and ``MANIFEST_ERR=`` do
not; and no flash read lands in the primary slot's span. ``STRAPS_HI=0x04000000`` is
required, so the run is attributable to this strap.

The image is unsigned and the OTP is the inherited TEST_DEV: slot selection runs before
the crypto chain.
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
_ROTATE_ECHO = "SPI_ROTATE=1"  # rom_main.c
_STRAP_ROTATE_ECHO = " rotate=1"  # boot_straps.c
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_MANIFEST_OK = "MANIFEST_OK"
# The slot label, which follows the slot rather than the retry counter, so on a
# rotated boot the first attempt is the backup. MANIFEST_PRIMARY appearing would
# mean the ROM read 0x1000, which this test erased.
_BACKUP_SLOT_LABEL = "MANIFEST_BACKUP"
_PRIMARY_SLOT_LABEL = "MANIFEST_PRIMARY"
_ANY_SLOT_ERROR = "MANIFEST_ERR="


@pyuvm.test()
class sep_rotate_update_set_test(sep_rom_ot_dma_boot_test):
    """ROTATE_UPDATE=1 with only 0x41000 programmed: first attempt boots it."""

    # Replaces, not extends: the inherited tuple requires MANIFEST_SRC=0x00001000,
    # which under rotation is precisely what must NOT happen.
    required_markers = (
        _SPI_PATH_MARKER,
        _STRAPS_HI_ECHO,
        _ROTATE_ECHO,
        _STRAP_ROTATE_ECHO,
        _BACKUP_SRC,
        _BACKUP_SLOT_LABEL,
        _MANIFEST_OK,
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _PRIMARY_SRC,
        _PRIMARY_SLOT_LABEL,
        _ANY_SLOT_ERROR,
        "MANIFEST_ALL_FAILED",
    )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        start, end = mm.erase_slot(buf, "primary")
        assert mm.slot_is_erased(buf, "primary"), (
            "primary slot is not fully erased after erase_slot()"
        )
        # The rotated-to slot must be intact, or a failure would be attributable
        # to a damaged image rather than to the slot order.
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-ROTATE: primary span 0x%06x..0x%06x erased to 0x%02x "
            "(%d bytes); the only bootable slot is 0x%06x: %s",
            start,
            end,
            mm.ERASED_BYTE,
            end - start,
            mm.BACKUP_MANIFEST_OFFSET,
            mm.describe(buf, "backup"),
        )
        assert (_STRAPS_HI_ROTATE >> _ROTATE_UPDATE_BIT) & 1, (
            f"the strap word this test injects (0x{_STRAPS_HI_ROTATE:08x}) does "
            f"not set rotate_update (bit {_ROTATE_UPDATE_BIT})"
        )
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

    def check_transport(self, console: list[str], flash) -> None:
        rds = ev.reads(flash.get_transactions())
        assert rds, "flash BFM served no read transactions; nothing was fetched over SPI"

        # CHK-ROTATE-FIRST-READ: the device's own record of which slot was
        # interrogated first, measured at the flash model rather than taken from
        # the ROM's account of itself. Indexed on the first read that lands in
        # EITHER slot, not on read[0], so an unrelated controller access (an ID
        # probe, a re-init read) cannot decide the verdict.
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

        # CHK-ROTATE-NO-PRIMARY-READ: the unrotated address was never touched at
        # all. A fallback boot would show reads in both spans; this shows one.
        assert not p_idx, (
            f"reads {p_idx} landed inside the primary slot span "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:06x}..0x{mm.BACKUP_MANIFEST_OFFSET:06x}: "
            f"the ROM interrogated the unrotated address, so this boot is a "
            f"failover rather than a rotation"
        )

        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert b_hit is not None, f"no SPI read covered 0x{mm.BACKUP_MANIFEST_OFFSET:x}"
        b_idx, b_txn = b_hit
        b_magic = ev.bytes_at(b_txn, mm.BACKUP_MANIFEST_OFFSET, 4)
        assert b_magic == mm.MANIFEST_MAGIC, (
            f"device returned {b_magic!r} at 0x{mm.BACKUP_MANIFEST_OFFSET:x}, "
            f"expected {mm.MANIFEST_MAGIC!r}"
        )
        self.logger.info(
            "CHK-ROTATE-ADDR: first slot read is read[%d] in the rotated slot, "
            "read[%d] returned %r at 0x%06x, and no read touched the primary span",
            first_slot_read,
            b_idx,
            b_magic,
            mm.BACKUP_MANIFEST_OFFSET,
        )
