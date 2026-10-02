# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A 4 KiB OCA payload staged after the manifest body in SEP SRAM boots.

4 KiB cannot hold the BL1 body at the shipped offset, so it is packed behind the TOC
and the ROM must locate it from the TOC entry, not from the shipped layout.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_payload_size_base as psb

_PAYLOAD_BYTES = 4 * 1024
_REQUIRED, _FORBIDDEN = psb.accepted_markers(_PAYLOAD_BYTES, smc=False)


@pyuvm.test()
class sep_firmware_payload_correct_sep_sram_4kb_test(psb.PayloadSizeAcceptedTest):
    """A 4 KiB payload fits fixed OCA SEP-SRAM staging."""

    payload_bytes = _PAYLOAD_BYTES
    stage_in_smc = False
    required_markers = psb.PayloadSizeAcceptedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeAcceptedTest.forbidden_markers + _FORBIDDEN
