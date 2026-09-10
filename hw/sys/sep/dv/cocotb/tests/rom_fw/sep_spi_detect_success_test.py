# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Single SPI flash detected at the primary address (PyUVM).

This ROM has no SPI device-detect step -- ``ot_spi_init`` only writes CSRs and
polls ``STATUS.READY`` (``src/sep_ot_spi.c:166-179``), and
``SEP_MSG_SPI_DETECTED_DEFAULT`` (``include/status_values.h:43``) is referenced
nowhere in the repo. Detection is therefore asserted operationally: the device
answered at ``PRIMARY_MANIFEST_OFFSET`` with the ``TBL1`` magic and the ROM reached
``MANIFEST_OK``. Do not "fix" this by asserting a detect status -- the ROM cannot
print one.

Forbidding every backup-span read and every ``MANIFEST_ERR=`` is what separates
this from the primary-fail/backup-success sibling; a silent failover also reaches
``MANIFEST_OK``.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# rom_spi_init() failure makes the ROM skip the primary slot outright
# (manifest_load.c:547-550), so the subject of this test never happens.
_SPI_INIT_OK = "SPI_INIT_OK"
_SPI_INIT_ERR = "SPI_INIT_ERR="

_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
# Any slot rejection at all. On a clean primary detect there must be none.
_ANY_MANIFEST_ERR = "MANIFEST_ERR="
_ALL_FAILED = "MANIFEST_ALL_FAILED"
# Controller-failure route to the backup; forbidding it keeps this an address
# decision.
_SPI_INIT_FAILED_SKIP = "SPI init failed, using backup manifest"


@pyuvm.test()
class sep_spi_detect_success_test(sep_rom_ot_dma_boot_test):
    """Flash answers at the primary address; the ROM boots from it, no failover."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (_SPI_INIT_OK,)
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _BACKUP_SRC,
        _ANY_MANIFEST_ERR,
        _ALL_FAILED,
        _SPI_INIT_ERR,
        _SPI_INIT_FAILED_SKIP,
    )

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

    def check_transport(self, console: list[str], flash) -> None:
        txns = flash.get_transactions()
        image_len = self._image_len
        rds = ev.reads(txns)
        # No reads recorded => every check below is vacuous.
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
            idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            magic,
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
