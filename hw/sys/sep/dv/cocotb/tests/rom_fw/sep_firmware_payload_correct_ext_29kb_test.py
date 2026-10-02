# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A 29 KiB OCA payload staged after the manifest body in SEP SRAM boots.

The fill exceeds the staged manifest, so a ROM that sizes the DMA from the TOC or the
image extents fails.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_payload_size_base as psb

_PAYLOAD_BYTES = 29 * 1024
_REQUIRED, _FORBIDDEN = psb.accepted_markers(_PAYLOAD_BYTES, smc=False)


@pyuvm.test()
class sep_firmware_payload_correct_sep_sram_29kb_test(psb.PayloadSizeAcceptedTest):
    """A 29 KiB payload fits fixed OCA SEP-SRAM staging."""

    payload_bytes = _PAYLOAD_BYTES
    stage_in_smc = False
    required_markers = psb.PayloadSizeAcceptedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeAcceptedTest.forbidden_markers + _FORBIDDEN
