# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An EXT payload one KiB past the SEP SRAM capacity is refused; the backup boots.

The size comes from this design's 256 KiB SEP SRAM, not the 62 KiB in the name, and
the ROM must refuse it with ``MANIFEST_ERR_PAYLOAD_TOO_LARGE`` before the fetch.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_payload_size_base as psb

_CAPACITY = psb.ext_payload_capacity(psb.shipped_payload_offset("primary"))
_PAYLOAD_BYTES = (_CAPACITY // 1024 + 1) * 1024
_REQUIRED, _FORBIDDEN = psb.refused_markers(psb.shipped_payload_bytes("backup"))


@pyuvm.test()
class sep_firmware_payload_incorrect_ext_62kb_test(psb.PayloadSizeRefusedTest):
    """Over-capacity EXT payload: primary refused, backup boots."""

    payload_bytes = _PAYLOAD_BYTES
    stage_in_smc = False
    required_markers = psb.PayloadSizeRefusedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeRefusedTest.forbidden_markers + _FORBIDDEN
