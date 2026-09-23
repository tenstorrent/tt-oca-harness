# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Test that a chiplet_id word is checked only when its selector bit is set.

Primary selects word 2 (match) and word 5 (mismatch) and is refused on word 5; backup matches all.
Needs +sep_smc_fuse_sense_done (no SMC in this TB) and +sep_crypto_edn_force (RSA-3072 on OTBN).
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
