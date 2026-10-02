# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest declares v1.0 with exactly the body size; it boots.

The primary declares v1.0 with the body size - 4 and ``oca_check_manifest_length``
refuses it with ``OCA_FAIL_MANIFEST_LENGTH`` before RSA, so one run shows the length
rule refuse and accept.
"""

from __future__ import annotations

import struct

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_manifest_length_fail_base import (
    sep_primary_manifest_length_fail_base,
)


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_valid_minor_0_length_correct_test(
    sep_primary_manifest_length_fail_base
):
    """Primary v1.0 length body-4 is refused; the v1.0 body-size backup is accepted and boots."""

    primary_minor = 0
    primary_length = fd.assert_consumer_body_size() - 4

    def prepare_backup(self, buf: bytearray) -> None:
        length = fd.assert_consumer_body_size(buf, "backup")
        version = mm.manifest_version(buf, "backup")
        assert version == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"backup manifest version is {version[0]}.{version[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the accepted side would not be the v1.0 rule"
        )
        self._backup_served = struct.pack("<HHI", *version, length)
        self.logger.info(
            "CHK-STIMULUS-BACKUP-LENGTH: backup declares v%d.%d manifest_length %d == the "
            "body size",
            *version,
            length,
        )

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
