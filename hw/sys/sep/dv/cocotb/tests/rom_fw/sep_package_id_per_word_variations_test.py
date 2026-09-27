# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""``package_id`` per-word match/mismatch across ``selector_bits[15:8]``.

Primary: word 3 matches, word 6 refuses. Backup: all eight match and boot.
Needs ``+sep_smc_fuse_sense_done`` and ``+sep_crypto_edn_force``.
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
