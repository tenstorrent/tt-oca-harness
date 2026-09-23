# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary declares v1.0 with a length that is not ``sizeof(manifest_t)``; backup boots.

A minor-0 manifest must be exactly 1184 bytes, so the aligned length 1188 is BAD_LENGTH.
Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_manifest_length_fail_base import (
    sep_primary_manifest_length_fail_base,
)


@pyuvm.test()
class sep_firmware_primary_manifest_major_version_valid_minor_0_length_incorrect_test(
        sep_primary_manifest_length_fail_base):
    """Primary is v1.0 with length 1188 -> refused -> the backup boots."""

    primary_minor = 0
    primary_length = mm.MANIFEST_SIZE + 4
