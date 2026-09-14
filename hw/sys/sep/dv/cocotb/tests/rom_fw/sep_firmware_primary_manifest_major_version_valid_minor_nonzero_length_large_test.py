# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary declares v1.1 with a length above ``MANIFEST_MAX_SIZE``; backup boots.

The ``minor != 0`` arm REFUSED at its UPPER bound, on the primary slot. With a
non-zero minor version ``validate_manifest_header``
(``bootrom/prod/src/manifest_load.c``) grades the length as a RANGE::

    minor != 0  ->  sizeof(manifest_t) <= manifest_length <= MANIFEST_MAX_SIZE

``MANIFEST_MAX_SIZE`` is 2048 (``bootrom/prod/include/manifest.h``), so 2052 is
``MANIFEST_ERR_BAD_LENGTH`` and the untouched backup recovers the boot.

WHY ``MANIFEST_MAX_SIZE + 4`` PINS THE UPPER BOUND:

  * 2052 is 4-byte aligned, so the alignment check that follows cannot be the
    verdict -- the shared base asserts this rather than assuming it;
  * 2052 is far ABOVE ``sizeof(manifest_t)``, so the range rule's lower bound cannot
    be the verdict either;
  * the minor is set to 1, so the exact-match arm is not the rule in force. That is
    a real difference and not a cosmetic one: leave the minor at 0 and 2052 is still
    refused, but by the exact-match arm, which is a DIFFERENT row
    (``..._minor_0_length_incorrect_test``). The minor write is what makes the upper
    bound the only reachable reason.

**THE ARM IS DRIVEN TO BOTH OUTCOMES.** The same minor with length 1188 is ACCEPTED
-- ``..._minor_nonzero_length_small_correct_test`` -- so the range arm has an
accepted case and this refused one, which is what says the ROM compares against a
bound rather than refusing v1.x manifests generally.

**ONLY THE UPPER BOUND IS EXERCISED.** No row in this group declares a
``manifest_length`` below ``sizeof(manifest_t)`` at a non-zero minor, so the range
rule's LOWER bound is shown rejecting nowhere; a ROM that dropped it would pass
every row here. Recorded as a coverage gap rather than invented, since a
``minor != 0`` row below 1184 is not one of the approved matrix rows.

**A DISCLOSED SCOPE LIMIT ON THE BOUND ITSELF.** 2052 is refused by BOTH length arms
-- it is neither equal to ``sizeof(manifest_t)`` nor within the range -- so this row
says the value was rejected, not that the ROM compared against 2048. Nothing in this
group pins that boundary: an off-by-one ROM using ``>=`` (wrongly refusing exactly
2048) would pass every row in the group, because the group's only ACCEPTED
``minor != 0`` length is 1188, well below the bound. Closing that needs a
``manifest_length == MANIFEST_MAX_SIZE`` accept case, which is not one of the
approved matrix rows and is therefore recorded as a coverage gap rather than
invented here. ``sep_manifest_field_defect.assert_rom_manifest_bounds`` does read
the ``#define`` back out of the header and require it to equal the Python mirror, so
a raised C bound cannot silently turn 2052 into a legal length.

**THIS ROW SHARES ONE ERROR CODE WITH EVERY OTHER LENGTH ROW.** No length arm prints
a token, so the served ``(major, minor, length)`` bytes from the flash BFM -- 1, 1,
2052 -- are the run-time discriminator. That is stimulus-side evidence and is
recorded as such in this row's ``flow_deviation``. Because 2052 exceeds
``sizeof(manifest_t)``, this row additionally gets the device-side BEHAVIOUR check:
``load_manifest_extra`` would fetch 868 bytes at ``primary_base + 1184`` for a slot
that PASSED the header checks, so the absence of any read beginning there is
evidence the header was refused first. See
:mod:`sep_primary_manifest_length_fail_base`.

Needs ``+sep_crypto_edn_force``: the recovering backup runs a full RSA-3072 modexp on
OTBN.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_manifest_length_fail_base import (
    sep_primary_manifest_length_fail_base,
)


@pyuvm.test()
class sep_firmware_primary_manifest_major_version_valid_minor_nonzero_length_large_test(
        sep_primary_manifest_length_fail_base):
    """Primary is v1.1 with length 2052 -> refused -> the backup boots."""

    primary_minor = 1
    primary_length = mm.MANIFEST_MAX_SIZE + 4
