# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary declares v1.0 with a length that is not ``sizeof(manifest_t)``; backup boots.

The ``minor == 0`` arm REFUSED on the primary slot. With a zero minor version
``validate_manifest_header`` (``bootrom/prod/src/manifest_load.c``) demands
``manifest_length == sizeof(manifest_t)`` EXACTLY, so 1188 is
``MANIFEST_ERR_BAD_LENGTH`` and the untouched backup recovers the boot.

WHY ``sizeof(manifest_t) + 4`` PINS THE EXACT-MATCH RULE AND NOTHING ELSE:

  * 1188 is 4-byte aligned, so the alignment check that follows cannot be the
    verdict -- the shared base asserts this rather than assuming it;
  * 1188 is ABOVE ``sizeof(manifest_t)`` and inside ``[1184, MANIFEST_MAX_SIZE]``,
    so a ROM that implemented the minor-0 arm as a lower bound, or that applied the
    ``minor != 0`` range rule to a v1.0 manifest, would ACCEPT it. Only an exact
    equality rejects it. Choosing a length BELOW 1184 would have been refused by
    both arms and would therefore have discriminated nothing.

**THE MINOR-VERSION DIFFERENTIAL.** 1188 at minor 1 is ACCEPTED -- that is
``sep_firmware_primary_manifest_major_version_valid_minor_nonzero_length_small_correct_test``,
which plants the identical length in the identical slot and boots FROM the primary.
The two rows differ in one 16-bit field, ``manifest_version_minor``, and the outcome
inverts from a failover to a primary boot. Neither checker can pass on the other's
log: that one requires ``MANIFEST_HASH_OK`` following the PRIMARY read and forbids
every ``MANIFEST_ERR=``, this one requires a primary ``MANIFEST_ERR=0x00030004``
followed by a backup read. That pair is what makes the exact-match rule falsifiable
rather than merely satisfied.

**THIS ROW AND ITS UPPER-BOUND SIBLING SHARE ONE ERROR CODE.** Both length arms
return ``MANIFEST_ERR_BAD_LENGTH`` and neither prints a token, so on the console this
row is indistinguishable from ``..._minor_nonzero_length_large_test``. The
discriminator is the served ``(major, minor, length)`` bytes from the flash BFM --
1, 0, 1188 against that row's 1, 1, 2052 -- which is stimulus-side evidence and is
recorded as such in this row's ``flow_deviation``. See
:mod:`sep_primary_manifest_length_fail_base` for the full attribution argument.

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
class sep_firmware_primary_manifest_major_version_valid_minor_0_length_incorrect_test(
        sep_primary_manifest_length_fail_base):
    """Primary is v1.0 with length 1188 -> refused -> the backup boots."""

    primary_minor = 0
    primary_length = mm.MANIFEST_SIZE + 4
