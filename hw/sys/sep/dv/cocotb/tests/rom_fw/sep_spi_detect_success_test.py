# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Flash answers at the primary address and the ROM boots from it without failover.

The ROM emits no SPI detect status, so detection is the primary-offset ``TBL1`` read plus
``MANIFEST_OK``.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# An SPI init failure skips the primary slot, which removes the subject of this test.
_SPI_INIT_OK = "SPI_INIT_OK"
_SPI_INIT_ERR = "SPI_INIT_ERR="

_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_ANY_MANIFEST_ERR = "MANIFEST_ERR="
_ALL_FAILED = "MANIFEST_ALL_FAILED"
# Controller-failure route to the backup, as opposed to an address decision.
_SPI_INIT_FAILED_SKIP = "SPI init failed, using backup manifest"


@pyuvm.test()
class sep_spi_detect_success_test(sep_rom_ot_dma_boot_test):
    """Flash answers at the primary address; the ROM boots from it, no failover."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (_SPI_INIT_OK,)
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _BACKUP_SRC, _ANY_MANIFEST_ERR, _ALL_FAILED, _SPI_INIT_ERR,
        _SPI_INIT_FAILED_SKIP,
    )

    def log_transport(self, flash) -> None:
        self.logger.info("CHK-SPI-TXNS:\n%s",
                         ev.summarize(flash.get_transactions(), self._image_len))

    def check_transport(self, console: list[str], flash) -> None:
        txns = flash.get_transactions()
        image_len = self._image_len
        rds = ev.reads(txns)
        assert rds, (
            f"flash BFM served no read transactions, so nothing was fetched over "
            f"SPI and the boot did not come from this device. All {len(txns)} "
            f"transactions: {[hex(t['opcode']) for t in txns]}"
        )

        hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        assert hit is not None, (
            f"no SPI read covered the primary manifest address "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:x}; the ROM never interrogated the "
            f"address this testcase is about"
        )
        idx, txn = hit
        magic = ev.bytes_at(txn, mm.PRIMARY_MANIFEST_OFFSET, 4)
        assert magic == mm.MANIFEST_MAGIC, (
            f"device returned {magic!r} at 0x{mm.PRIMARY_MANIFEST_OFFSET:x}, "
            f"expected {mm.MANIFEST_MAGIC!r}: the primary address did not answer "
            f"with a manifest, so 'detected at the primary address' is not what "
            f"this run showed"
        )
        self.logger.info(
            "CHK-DETECT-PRIMARY: read[%d] at 0x%06x returned magic %r",
            idx, mm.PRIMARY_MANIFEST_OFFSET, magic,
        )

        # Without this, the primary-fail/backup-success run would also pass here.
        backup_hits = ev.slot_read_indices(rds, "backup", image_len)
        assert not backup_hits, (
            f"device served {len(backup_hits)} read(s) inside the backup slot span "
            f"(read indices {backup_hits}): the primary alone did not serve this "
            f"boot, so this is a failover result and not a primary detect"
        )
        self.logger.info(
            "CHK-NO-FAILOVER: no read inside the backup span; %d reads, all primary",
            len(rds),
        )
