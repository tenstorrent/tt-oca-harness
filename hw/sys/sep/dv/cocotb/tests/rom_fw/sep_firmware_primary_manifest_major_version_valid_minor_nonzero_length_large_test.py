# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary declares v1.1 with the PQC body size as manifest_length; the backup boots.

The length is legal for the other variant only: the rule compares against the body
size the magic selects, not against any known body size.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_manifest_length_fail_base import (
    sep_primary_manifest_length_fail_base,
)


@pyuvm.test()
class sep_firmware_primary_manifest_major_version_valid_minor_nonzero_length_large_test(
    sep_primary_manifest_length_fail_base
):
    """Primary is OCAC v1.1 with length 36864 -> OCA_FAIL_MANIFEST_LENGTH -> the backup boots."""

    primary_minor = 1
    primary_length = mm.K.OCA_PQC_BODY_SIZE
