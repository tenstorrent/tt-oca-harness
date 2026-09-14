# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary declares v1.1 with a misaligned length; the backup boots.

The ``minor != 0`` arm ACCEPTS the value and the 4-BYTE ALIGNMENT rule refuses it,
on the primary slot. ``validate_manifest_header``
(``bootrom/prod/src/manifest_load.c``) grades the length in two steps::

    minor != 0  ->  sizeof(manifest_t) <= manifest_length <= MANIFEST_MAX_SIZE
    then, for both minor arms  ->  manifest_length % 4 == 0

so ``sizeof(manifest_t) + 1`` = 1185 passes the range and fails the alignment, which
is ``MANIFEST_ERR_BAD_LENGTH``. The primary-side rejection returns into
``rom_manifest_boot``'s retry loop and the untouched backup recovers the boot.

WHY 1185 PINS THE ALIGNMENT RULE AND NOTHING ELSE. This is the only one of the three
refusing length arms whose stimulus is unambiguous without any appeal to a bound:

  * 1185 is INSIDE ``[sizeof(manifest_t), MANIFEST_MAX_SIZE]``, so the range rule
    ACCEPTED it -- neither its lower nor its upper bound can be the verdict;
  * the minor is set to 1, so the ``minor == 0`` exact-match rule is not in force.
    That is a real difference and not a cosmetic one: leave the minor at 0 and 1185
    is still refused, but by the exact-match arm, which is a DIFFERENT row
    (``..._minor_0_length_incorrect_test``);
  * nothing is left but ``manifest_length % 4 != 0``.

The shared base derives that arm from the declared pair and asserts the exclusions
rather than trusting this docstring -- see :mod:`sep_primary_manifest_length_fail_base`.

**THE MINOR-VERSION DIFFERENTIAL.** ``..._minor_nonzero_length_small_correct_test``
plants the same minor in the same slot with 1188 -- one byte class away, aligned --
and BOOTS from the primary. So the pair differs only in the low two bits of
``manifest_length`` and the outcome inverts from a failover to a primary boot.
Neither checker can pass on the other's log: that one requires ``MANIFEST_HASH_OK``
following the PRIMARY read and forbids every ``MANIFEST_ERR=``, this one requires a
primary ``MANIFEST_ERR=0x00030004`` followed by a backup read.

**THIS ROW SHARES ONE ERROR CODE WITH EVERY OTHER LENGTH ROW.** No length arm prints
a token -- ``SEP_MSG_INVALID_MANIFEST_LENGTH``
(``bootrom/prod/include/status_values.h``) is defined and emitted by nothing under
``bootrom/prod/src`` -- so the served ``(major, minor, length)`` bytes from the flash
BFM, 1, 1, 1185, are the run-time discriminator. That is stimulus-side evidence and
is recorded as such in this row's ``flow_deviation``.

Because 1185 exceeds ``sizeof(manifest_t)``, this row also gets the device-side
BEHAVIOUR check: ``load_manifest_extra`` would fetch one byte at
``primary_base + 1184`` for a slot that PASSED the header checks, so the absence of
any read beginning there is evidence the header was refused first.

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
class sep_firmware_primary_manifest_major_version_valid_minor_nonzero_length_small_incorrect_test(
        sep_primary_manifest_length_fail_base):
    """Primary is v1.1 with length 1185 -> refused on alignment -> the backup boots."""

    primary_minor = 1
    primary_length = mm.MANIFEST_SIZE + 1
