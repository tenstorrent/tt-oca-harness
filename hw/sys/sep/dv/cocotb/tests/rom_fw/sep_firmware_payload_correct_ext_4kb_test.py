# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A 4 KiB payload staged in SEP EXT SRAM is accepted and boots.

The smallest legal size in the group, and the only member whose payload is
SMALLER than the one the packer ships: 4096 bytes cannot hold the BL1 body at the
packer's offset of 4096, so ``repack_payload`` packs it directly behind the TOC
region. That makes this member the one that also proves the ROM locates the image
from the TOC entry rather than from the shipped layout -- a ROM that assumed
offset 4096 would read past the payload and fail the body digest.

Legal for a reason this member asserts rather than assumes: 0x1000 +
0x1000 is far inside the 256 KiB SEP SRAM, so all three of the ROM's bounds
(``sep_payload_size_base``) pass, and ``PAYLOAD=0x00001000`` on the console is the
ROM echoing the length it accepted.

No failover: the slot is re-signed and otherwise untouched, so a backup read would
mean the primary was refused for something this member does not model.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_payload_size_base as psb

_PAYLOAD_BYTES = 4 * 1024
_REQUIRED, _FORBIDDEN = psb.accepted_markers(_PAYLOAD_BYTES, smc=False)


@pyuvm.test()
class sep_firmware_payload_correct_ext_4kb_test(psb.PayloadSizeAcceptedTest):
    """4 KiB payload, EXT SRAM staging, accepted."""

    payload_bytes = _PAYLOAD_BYTES
    stage_in_smc = False
    required_markers = psb.PayloadSizeAcceptedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeAcceptedTest.forbidden_markers + _FORBIDDEN
