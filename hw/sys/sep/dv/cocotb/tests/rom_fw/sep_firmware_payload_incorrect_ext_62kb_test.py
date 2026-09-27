# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An OCA payload one KiB past fixed SEP-SRAM staging is refused; the backup boots.

The size is derived from the generated SEP SRAM map and the OCA body size. The ROM
must report ``OCA_BOOT_ERR_STAGE_OVERFLOW`` before fetching the primary payload.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_payload_size_base as psb

_CAPACITY = psb.payload_staging_capacity()
_PAYLOAD_BYTES = (_CAPACITY // 1024 + 1) * 1024
_REQUIRED, _FORBIDDEN = psb.refused_markers(psb.shipped_payload_bytes("backup"))


@pyuvm.test()
class sep_firmware_payload_exceeds_sep_sram_fixed_test(psb.PayloadSizeRefusedTest):
    """One-KiB-over OCA staging payload: primary refused, backup boots."""

    payload_bytes = _PAYLOAD_BYTES
    stage_in_smc = False
    required_markers = psb.PayloadSizeRefusedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeRefusedTest.forbidden_markers + _FORBIDDEN
