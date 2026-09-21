# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An EXT payload one KiB past the SRAM capacity is refused; the backup boots.

The fixed over-capacity case. The primary declares a payload that
``payload_offset + payload_length`` puts outside SEP EXT SRAM, so
``validate_manifest_header`` returns ``MANIFEST_ERR_PAYLOAD_TOO_LARGE`` before the
staging block runs (``manifest_load.c``), ``rom_manifest_boot`` falls over to the
backup, and the backup boots.

THE SIZE IS THIS DESIGN'S BOUNDARY, NOT THE REFERENCE'S. The reference testcase
names 62 KiB because the design it was written for has a 64 KiB SEP SRAM with a
0x1100 heap reserve at the top, leaving 59.75 KiB usable; 62 KiB is a round value
its author chose 2.25 KiB above that, and its ROM's own destination bound is
tighter still, since it also subtracts the staged manifest. This design's SEP SRAM
is 256 KiB
(``OCH_SEP_TOP_SEP_SRAM_SIZE``) with no heap reserve in the ROM's bound, so the
usable payload at the shipped ``payload_offset`` is 252 KiB and 62 KiB is a
perfectly legal size here. Keeping the literal would invert the testcase: the ROM
would accept it, boot, and the member would report a pass for the opposite of what
its name claims. The stimulus is therefore the first whole KiB past THIS design's
capacity, 253 KiB, taken from :func:`sep_payload_size_base.ext_payload_capacity`
rather than written down, and cross-checked against the header the ROM compiles
with so a future SRAM resize moves the stimulus instead of quietly legalising it.
The mutated field, the failover and the expected terminal outcome are the
reference's; the numeric boundary is this design's.

THE REFUSAL IS NOT THE REFERENCE'S TOKEN, AND DELIBERATELY SO. The reference
expects ``WARNING: INVALID_ENCRYPTED_PAYLOAD_LENGTH``, which its ROM emits from an
entirely different arm: ``payload_hashed_length != payload_length`` on an
ENCRYPTED payload. Its image is encrypted and its generator rewrites
``payload_length`` without ``payload_hashed_length``, so its oversized slot is
refused on that inconsistency before its own capacity test is reached -- its
pattern list puts the warning ahead of any ``MANIFEST_VALIDATED``, which is how
one can tell. This port aims at the capacity decision the matrix row names, so it
requires ``MANIFEST_ERR_PAYLOAD_TOO_LARGE`` and FORBIDS the hashed-length tokens.
The reference's actual arm is covered here by the
``*_payload_invalid_payload_hash_length_test`` and
``*_toc_payload_size_mismatch_test`` families instead.

WHY THE MATERIAL IS NOT PRODUCED. The refusal is upstream of the payload fetch, so
the declared length is the whole stimulus and the quarter-megabyte behind it is
never read. The device record is what proves that rather than assumes it: no flash
read may begin at the primary's payload offset. A ROM that checked the length after
transferring it would pass every console check here and fail that one.

The slot is re-signed, so the declared size is the only thing wrong with it. A
stale signature would also be refused, on the same failover path, by a slot error
the console cannot tell apart from this one -- which is why the error code is
required exactly and every other length refusal is forbidden.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_payload_size_base as psb

_CAPACITY = psb.ext_payload_capacity(psb.shipped_payload_offset("primary"))
# The first whole KiB past the capacity: the tightest KiB-granular violation, and
# so the value a bound one KiB too loose would wrongly accept. The reference's
# 62 KiB sits further above its own limit; this is the stricter choice.
_PAYLOAD_BYTES = (_CAPACITY // 1024 + 1) * 1024
_REQUIRED, _FORBIDDEN = psb.refused_markers(psb.shipped_payload_bytes("backup"))


@pyuvm.test()
class sep_firmware_payload_incorrect_ext_62kb_test(psb.PayloadSizeRefusedTest):
    """Over-capacity EXT payload: primary refused, backup boots."""

    payload_bytes = _PAYLOAD_BYTES
    stage_in_smc = False
    required_markers = psb.PayloadSizeRefusedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeRefusedTest.forbidden_markers + _FORBIDDEN
