# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A 29 KiB payload staged in SEP EXT SRAM is accepted and boots.

The mid-range legal EXT size: five times the packer's payload and still well
inside the 252 KiB the EXT path allows at the shipped ``payload_offset``. The BL1
body stays where the packer put it, so what grows is the fill between the end of
the image and the end of the payload.

What separates this from the 4 KiB member is not only the number. The fill now
exceeds the staged manifest, so a ROM that sized the DMA from the TOC region or
from the image extents instead of from ``payload_length`` would transfer too
little; ``PAYLOAD=0x00007400`` plus the device-side check that every declared
byte was actually served is what catches that.

NOT COVERED HERE, because the fill is zeros: the ROM's own zeroization of the
payload tail (``explicit_memzero`` in the entry loop, ``manifest_load.c``) is
unobservable when the bytes it clears were already zero. Establishing that would
need a non-zero fill and a read-back of the staged tail, which is a different
stimulus from the size decision this member is named for.

No failover: the slot is re-signed and otherwise untouched.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_payload_size_base as psb

_PAYLOAD_BYTES = 29 * 1024
_REQUIRED, _FORBIDDEN = psb.accepted_markers(_PAYLOAD_BYTES, smc=False)


@pyuvm.test()
class sep_firmware_payload_correct_ext_29kb_test(psb.PayloadSizeAcceptedTest):
    """29 KiB payload, EXT SRAM staging, accepted."""

    payload_bytes = _PAYLOAD_BYTES
    stage_in_smc = False
    required_markers = psb.PayloadSizeAcceptedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeAcceptedTest.forbidden_markers + _FORBIDDEN
