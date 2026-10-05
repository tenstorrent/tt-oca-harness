# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unsupported 64 KiB SMC-staging scaffold.

The OCA manifest has no payload-destination selector, the ROM stages payloads into SEP
SRAM, and shared payload helpers reject ``smc=True`` and ``stage_in_smc``. This file
defines the 64 KiB payload and expected marker geometry.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_payload_size_base as psb

_PAYLOAD_BYTES = 64 * 1024
_REQUIRED, _FORBIDDEN = psb.accepted_markers(_PAYLOAD_BYTES, smc=True)


@pyuvm.test()
class sep_firmware_payload_correct_smc_64kb_test(psb.PayloadSizeAcceptedTest):
    """64 KiB SMC-staging marker scaffold."""

    payload_bytes = _PAYLOAD_BYTES
    stage_in_smc = True
    required_markers = psb.PayloadSizeAcceptedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeAcceptedTest.forbidden_markers + _FORBIDDEN
