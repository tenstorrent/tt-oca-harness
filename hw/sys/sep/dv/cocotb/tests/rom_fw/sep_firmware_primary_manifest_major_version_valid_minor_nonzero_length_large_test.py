# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary declares v1.1 with a length above ``MANIFEST_MAX_SIZE``; backup boots.

Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_manifest_length_fail_base import (
    sep_primary_manifest_length_fail_base,
)


@pyuvm.test()
class sep_firmware_primary_manifest_major_version_valid_minor_nonzero_length_large_test(
        sep_primary_manifest_length_fail_base):
    """Primary is v1.1 with length 2052 -> refused -> the backup boots."""

    primary_minor = 1
    primary_length = mm.MANIFEST_MAX_SIZE + 4
