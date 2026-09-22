# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""``package_id`` per-word match/mismatch across ``selector_bits[15:8]``.

A word must be checked when, and only when, its selector bit is set, and a
selected word that MATCHES must not refuse the slot.

The mirror of ``sep_chiplet_id_per_word_variations_test`` with the mask moved into
the upper selector byte, which the ROM reads as ``(sel >> 8) & 0xFF`` and indexes
0..7 into ``package_id`` (``manifest_load.c``)::

    PRIMARY  byte 0x48 -- words 3 and 6 selected      -> refused on word 6
             word 3 = 0x00000000  selected, MATCHES the fuse map
             word 6 = 0xa5a5a5a5  selected, MISMATCHES
             words 0,1,2,4,5,7 = 0xa5a5a5a5, selectors CLEAR

    BACKUP   byte 0xff -- all eight selected, all eight = 0x00000000
             -> accepted, boots

``PID_IDX=0x00000006`` carries the discrimination for the same reason the chiplet
row's ``CID_IDX`` does: word 3 is selected and lower, and words 0, 1, 2, 4 and 5
hold the same mismatching value with their bits clear.

The cross-domain control is stronger here because the chiplet loop runs FIRST over
eight mismatching words with its selector byte clear, so a ROM that fed
``(sel >> 8) & 0xFF`` to it would refuse the primary on the chiplet arm;
``CHIPLET_ID_MISMATCH`` is forbidden.

The index and the mask are deliberately not the chiplet row's, and not
``sep_firmware_manifest_primary_invalid_package_id_test``'s 0x14 / index 2
either, so no two of the four device-id rows can satisfy each other's
``*_IDX=`` assertion.

Needs ``+sep_smc_fuse_sense_done`` and ``+sep_crypto_edn_force``, for the reasons
given in ``sep_chiplet_id_per_word_variations_test``.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_device_id_variation_base import sep_device_id_variation_base

_PRIMARY_MASK = 0x48
_PRIMARY_MATCH_WORDS = (3,)
_REJECT_INDEX = 6


@pyuvm.test()
class sep_package_id_per_word_variations_test(sep_device_id_variation_base):
    """Primary: word 3 matches, word 6 refuses. Backup: all eight match and boot."""

    kind = "package_id"
    primary_mask = _PRIMARY_MASK
    primary_match_words = _PRIMARY_MATCH_WORDS
    reject_index = _REJECT_INDEX

    defect_marker = fd.PACKAGE_MARKER
    defect_evidence = fd.device_id_required_markers("package_id", _REJECT_INDEX)
