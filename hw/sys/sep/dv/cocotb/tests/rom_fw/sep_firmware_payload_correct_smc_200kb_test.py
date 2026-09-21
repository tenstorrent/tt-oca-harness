# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A 200 KiB payload staged in the SMC SRAM window is accepted and boots.

The largest legal size in the group, and the one that pins the upper end of the
accepted range. 200 KiB leaves only 52 KiB of headroom under
``validate_manifest_header``'s bound (0x1000 + 0x32000 against the 256 KiB SEP
SRAM), so this member is the closest an accepted payload gets to the boundary the
refused members sit past. Together they bracket it: 200 KiB in and 253 KiB out.

Not a boundary test by itself. The exact bound belongs to the refused members,
which assert the error code; this one asserts that a size this far up the range is
still accepted and still boots, which is the claim a ROM with an over-tight bound
would fail.

It is also the costliest member by a wide margin. About half the run's simulated
time is the serial flash read and most of the rest is the ROM zeroing the payload
tail, so the device-side check that every declared byte really was served is what
makes that cost buy evidence rather than a long boot.

WHAT THE STAGED COPY PROVES, AT THIS SIZE. Only the TOC region and the BL1 body --
about 2 KiB of the 200 -- are bound by a digest the ROM verifies, because
``payload_hashed_length`` stays at the packer's value and the fill is zeros. The
size is therefore established by the declared length, the destination, and the
bytes the device served, not by a digest over the whole staged region. See the
scope limit in ``sep_payload_size_base``.

No failover: the slot is re-signed and otherwise untouched.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_payload_size_base as psb

_PAYLOAD_BYTES = 200 * 1024
_REQUIRED, _FORBIDDEN = psb.accepted_markers(_PAYLOAD_BYTES, smc=True)


@pyuvm.test()
class sep_firmware_payload_correct_smc_200kb_test(psb.PayloadSizeAcceptedTest):
    """200 KiB payload, SMC SRAM staging, accepted."""

    payload_bytes = _PAYLOAD_BYTES
    stage_in_smc = True
    required_markers = psb.PayloadSizeAcceptedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeAcceptedTest.forbidden_markers + _FORBIDDEN
