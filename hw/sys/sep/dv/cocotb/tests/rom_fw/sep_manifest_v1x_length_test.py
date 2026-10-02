# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""v1.x ``manifest_length``: the body size is accepted and body size + 1 refused, in one run.

Both slots declare v1.1, so a non-zero minor must neither relax nor tighten the length rule.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_manifest_length_fail_base import (
    sep_primary_manifest_length_fail_base,
)

_MINOR = 1


@pyuvm.test()
class sep_manifest_v1x_length_test(sep_primary_manifest_length_fail_base):
    """v1.1/body+1 refused on the primary; v1.1/body accepted on the backup."""

    primary_minor = _MINOR
    primary_length = fd.assert_consumer_body_size() + 1

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # Verify the signer on the untouched backup before the re-seal changes it.
        pm.verify_signing_key(buf, "backup")
        pm.verify_sealed(buf, "backup")
        return super().mutate_flash_image(buf)

    def prepare_backup(self, buf: bytearray) -> None:
        body = fd.assert_consumer_body_size()
        self._backup_served = fd.plant_manifest_length(
            self.logger, buf, "backup", minor=_MINOR, length=body
        )
        pm.reseal(buf, "backup")

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        fd.assert_served_field(
            self.logger,
            flash,
            "backup",
            mm.OFF_VERSION_MAJOR,
            self._backup_served,
            "backup manifest_version_major/minor + manifest_length",
        )
        self.logger.info(
            "CHK-V1X-LENGTH-BOUNDARY PASS: under v%d.%d the primary's %d was refused "
            "and the backup's %d was accepted and booted",
            mm.MANIFEST_MAJOR_VERSION,
            _MINOR,
            self.primary_length,
            fd.assert_consumer_body_size(),
        )
