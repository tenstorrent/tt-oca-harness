# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary address blank, backup address serves the boot (PyUVM).

STIMULUS. The primary slot's whole flash span is erased to 0xFF and the backup is
left untouched, so one device answers at both addresses but only the backup holds a
boot slot. Erasing the SPAN rather than just the 1184-byte header matters: a slot's
payload is fetched at a manifest-relative offset, so
leaving the primary payload would leave a half-populated address.

The backup boots standalone because both slots carry ``payload_offset = 0x1000``
and the ROM resolves it as ``src_addr + payload_offset``, so the backup at 0x41000 fetches its payload from
0x42000.

This ROM has no SPI detect/retry status -- ``SEP_MSG_SPI_TRY_BACKUP``
(``include/status_values.h:44``) is referenced nowhere in the repo -- and no device
probe (``src/sep_ot_spi.c:166-179``). So "no-detect" is per-address blankness, and
the failover is asserted as the ordered pair ``MANIFEST_ERR=`` carrying the
bad-magic code then ``MANIFEST_SRC=0x00041000``, which pins both the reason and
the destination.

``"SPI init failed, using backup manifest"`` is forbidden because that is the
``spi_status`` skip path, which reaches the backup
because the CONTROLLER died. Without that forbid, a broken-controller run would
look like a passing address failover -- the most likely false pass here.

Order is asserted on both the console and the device log, not mere presence. Slot
identity is asserted on ``MANIFEST_SRC=`` and device addresses, never on the
``MANIFEST_PRIMARY`` / ``MANIFEST_BACKUP`` label: the ROM derives the label from the
retry counter but the offset from the possibly-rotated slot index, so under ``rotate_update`` they disagree.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# An erased slot fails the identifier check in
# the manifest header check, which runs before the hash
# check, so the verdict is deterministically BAD_MAGIC.
MANIFEST_ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")

_SPI_INIT_OK = "SPI_INIT_OK"
_SPI_INIT_ERR = "SPI_INIT_ERR="
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_PRIMARY_ERR = f"MANIFEST_ERR=0x{MANIFEST_ERR_BAD_MAGIC:08x}"
_MANIFEST_OK = "MANIFEST_OK"
_ALL_FAILED = "MANIFEST_ALL_FAILED"
# Controller-failure route to the backup; see the docstring.
_SPI_INIT_FAILED_SKIP = "SPI init failed, using backup manifest"


@pyuvm.test()
class sep_spi_primary_fail_backup_test(sep_rom_ot_dma_boot_test):
    """Primary address blank -> ROM fails over to the backup address and boots."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _SPI_INIT_OK,
        _PRIMARY_ERR,
        _BACKUP_SRC,
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _ALL_FAILED,
        _SPI_INIT_ERR,
        _SPI_INIT_FAILED_SKIP,
    )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        start, end = mm.erase_slot(buf, "primary")
        # Self-check both halves: a changed slot layout would otherwise erase the
        # wrong bytes, or a damaged backup would fail for an unintended reason.
        assert mm.slot_is_erased(buf, "primary"), (
            "primary slot is not fully erased after erase_slot()"
        )
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-SPI: primary span 0x%06x..0x%06x erased to 0x%02x "
            "(%d bytes); backup intact: %s",
            start,
            end,
            mm.ERASED_BYTE,
            end - start,
            mm.describe(buf, "backup"),
        )
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

    def check_transport(self, console: list[str], flash) -> None:
        txns = flash.get_transactions()

        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        # --- console ordering ------------------------------------------------
        i_psrc = index_of(_PRIMARY_SRC)
        i_perr = index_of(_PRIMARY_ERR)
        i_bsrc = index_of(_BACKUP_SRC)
        i_ok = index_of(_MANIFEST_OK)
        # Presence is already guaranteed by required_markers; these are the
        # sequence claims, which that mechanism cannot express.
        assert i_psrc < i_perr < i_bsrc < i_ok, (
            f"failover sequence is out of order: {_PRIMARY_SRC}@{i_psrc} -> "
            f"{_PRIMARY_ERR}@{i_perr} -> {_BACKUP_SRC}@{i_bsrc} -> "
            f"{_MANIFEST_OK}@{i_ok}. A backup read that did not follow a primary "
            f"rejection is not a failover. Console: {console}"
        )
        self.logger.info(
            "CHK-FAILOVER-ORDER: primary@%d -> BAD_MAGIC@%d -> backup@%d -> OK@%d",
            i_psrc,
            i_perr,
            i_bsrc,
            i_ok,
        )

        # --- device evidence -------------------------------------------------
        rds = ev.reads(txns)
        assert rds, (
            f"flash BFM served no read transactions; nothing was fetched over SPI. "
            f"All {len(txns)} transactions: {[hex(t['opcode']) for t in txns]}"
        )

        # CHK-PRIMARY-BLANK: the device was addressed at the primary slot and
        # answered blank. This is the "no-detect" half of the stimulus, measured at
        # the device rather than inferred from the ROM's complaint.
        p_hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        assert p_hit is not None, (
            f"no SPI read covered 0x{mm.PRIMARY_MANIFEST_OFFSET:x}: the ROM never "
            f"interrogated the primary address, so it did not fail over FROM it"
        )
        p_idx, p_txn = p_hit
        # Every byte the device returned for this read, not just the 4 magic bytes:
        # the ROM fetches the whole 1184-byte manifest here, so checking the lot
        # makes the device-side claim ("this address is blank") as strong as the
        # stimulus self-check already guarantees, instead of resting on it.
        p_all = bytes(p_txn["data_out"])
        assert ev.all_erased(p_all), (
            f"device returned non-erased bytes in the {len(p_all)}-byte read at "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:x} (first 16: {p_all[:16].hex()}), "
            f"expected all 0x{mm.ERASED_BYTE:02x}: the primary address was not "
            f"blank, so the rejection came from something other than no-detect"
        )

        # CHK-BACKUP-DETECT: the backup address answered with a real manifest.
        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert b_hit is not None, (
            f"no SPI read covered 0x{mm.BACKUP_MANIFEST_OFFSET:x}: the ROM never "
            f"read the backup address, so the boot came from somewhere else"
        )
        b_idx, b_txn = b_hit
        b_magic = ev.bytes_at(b_txn, mm.BACKUP_MANIFEST_OFFSET, 4)
        assert b_magic == mm.MANIFEST_MAGIC, (
            f"device returned {b_magic!r} at 0x{mm.BACKUP_MANIFEST_OFFSET:x}, "
            f"expected {mm.MANIFEST_MAGIC!r}"
        )

        # CHK-DEVICE-ORDER: the two addresses were interrogated in the failover
        # order, per the device's own record. Independent of the console.
        assert p_idx < b_idx, (
            f"device served the backup address (read[{b_idx}]) before the primary "
            f"(read[{p_idx}]): the transaction order is not a failover"
        )
        self.logger.info(
            "CHK-ADDR-FAILOVER: read[%d] 0x%06x returned blank, then read[%d] "
            "0x%06x returned %r -- same device, two addresses, in order",
            p_idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            b_idx,
            mm.BACKUP_MANIFEST_OFFSET,
            b_magic,
        )
