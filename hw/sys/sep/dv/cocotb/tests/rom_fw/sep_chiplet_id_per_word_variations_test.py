# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""``chiplet_id`` per-word match/mismatch across ``selector_bits[7:0]``.

A word must be checked when, and only when, its selector bit is set, and a
selected word that MATCHES must not refuse the slot. Representative cases only:
the exhaustive per-word selector cross is not attempted here.

THE STIMULUS, one run, two slots. ``selector_bits[7:0]`` is the chiplet_id byte
(``manifest_load.c``, ``sel & 0xFF``)::

    PRIMARY  byte 0x24 -- words 2 and 5 selected      -> refused on word 5
             word 2 = 0x00000000  selected, MATCHES the fuse map
             word 5 = 0xa5a5a5a5  selected, MISMATCHES
             words 0,1,3,4,6,7 = 0xa5a5a5a5, selectors CLEAR

    BACKUP   byte 0xff -- all eight selected, all eight = 0x00000000
             -> accepted, boots

``CID_IDX=0x00000005`` is this row's mapping evidence; what that index rules out,
the accepted slot's scope limit and the cross-domain control are in
:mod:`sep_device_id_variation_base`. The ``package_id`` selector byte is clear in
both slots over eight mismatching words, and ``PACKAGE_ID_MISMATCH`` is forbidden.

Needs ``+sep_smc_fuse_sense_done``: with any selector byte non-zero the ROM waits
for ``smc_fuse_sense_done`` before reading the SMC fuse map, and this testbench
has no SMC to raise it. Needs ``+sep_crypto_edn_force``: the recovering backup
runs a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_device_id_variation_base import sep_device_id_variation_base

_PRIMARY_MASK = 0x24
_PRIMARY_MATCH_WORDS = (2,)
_REJECT_INDEX = 5


@pyuvm.test()
class sep_chiplet_id_per_word_variations_test(sep_device_id_variation_base):
    """Primary: word 2 matches, word 5 refuses. Backup: all eight match and boot."""

    kind = "chiplet_id"
    primary_mask = _PRIMARY_MASK
    primary_match_words = _PRIMARY_MATCH_WORDS
    reject_index = _REJECT_INDEX

    defect_marker = fd.CHIPLET_MARKER
    defect_evidence = fd.device_id_required_markers("chiplet_id", _REJECT_INDEX)
