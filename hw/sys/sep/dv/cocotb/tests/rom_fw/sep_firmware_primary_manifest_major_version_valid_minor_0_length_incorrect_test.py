# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary declares v1.0 with manifest_length one word above the body size; the backup boots."""

from __future__ import annotations

import pyuvm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_manifest_length_fail_base import (
    sep_primary_manifest_length_fail_base,
)


@pyuvm.test()
class sep_firmware_primary_manifest_major_version_valid_minor_0_length_incorrect_test(
    sep_primary_manifest_length_fail_base
):
    """Primary is v1.0 with length body+4 -> OCA_FAIL_MANIFEST_LENGTH -> the backup boots."""

    primary_minor = 0
    primary_length = fd.assert_consumer_body_size() + 4
