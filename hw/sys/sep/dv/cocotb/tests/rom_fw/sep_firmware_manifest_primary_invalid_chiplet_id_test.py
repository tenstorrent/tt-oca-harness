# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary enables chiplet_id constraints it does not satisfy; the backup boots.

``selector_bits[0..7]`` each enable the ``usage_constraints.chiplet_id`` word of
the same index. For every enabled word the ROM reads the SMC fuse map at
``SMC_FUSE_MAP_CHIPLET_ID_OFFSET + i*4`` and refuses the slot on the first
disagreement with ``CHIPLET_ID_MISMATCH`` and
``MANIFEST_ERR_LC_USAGE_CONSTRAINT`` (``bootrom/prod/src/manifest_load.c``). The
reference expects that verdict on the primary and a completed boot from the
backup.

WHY THE STIMULUS IS A SELECTOR MASK AND NOTHING ELSE. The stimulus needs both
``selector_bits`` and eight ``chiplet_id`` words of ``0xa5a5a5a5``. The shipped
image already carries exactly those eight words, with the selector clear
(``bootrom/prod/configs/secure_boot_test.yaml``), so setting the selector is
enough and writing the array would be a no-op.
``sep_manifest_mutate.verify_device_id_layout`` anchors that against the real
bytes rather than trusting the config.

WHY THE MASK IS FIXED, AND WHY 0x28. Every value in ``1..0xff`` exercises the
same arm, so the choice only decides which word the rejection is attributed to,
and drawing it at random would make that unpredictable. 0x28 enables words 3 and 5, which makes word 3 the
lowest enabled one: a NON-ZERO index. Roughly half the range has bit 0
set, and any such mask makes ``CID_IDX=0x00000000`` unfalsifiable by a ROM that
always reported word 0, leaving the selector-to-word mapping unchecked. Fixing the
mask is what lets :func:`assert_device_id_mismatch` assert the exact index.

WHAT THE FUSE SIDE IS NOT ALLOWED TO CLAIM. The SMC fuse map is served by the
testbench's flat ``axi_sim_mem``, which never has these words written, so the
value the ROM reads there is a property of the model and not of the part
(``dv/docs/how_to_add_a_testcase.md``). This testcase therefore asserts the
manifest's own word and the fact that the two DIFFERED -- the comparison the ROM
performs -- and never asserts what the fuse map returned.

MARKER SUBSTITUTION. ``SEP_MSG_INVALID_CHIPLET_ID`` is defined in
``bootrom/prod/include/status_values.h`` and emitted nowhere, so the debug
console token is the only per-reason evidence available.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_usage_constraint_base import sep_primary_usage_constraint_base

# Fixed rather than drawn, so the echoed index is assertable.
_SELECTOR_MASK = 0x28
_REJECT_INDEX = 3


@pyuvm.test()
class sep_firmware_manifest_primary_invalid_chiplet_id_test(
        sep_primary_usage_constraint_base):
    """Primary enables chiplet_id words 3 and 5 -> refused -> the backup boots."""

    defect_marker = fd.CHIPLET_MARKER
    defect_evidence = fd.device_id_required_markers("chiplet_id", _REJECT_INDEX)

    def plant(self, buf: bytearray, slot: str) -> None:
        index = fd.plant_device_id_defect(buf, slot, "chiplet_id", _SELECTOR_MASK)
        assert index == _REJECT_INDEX, (
            f"selector mask 0x{_SELECTOR_MASK:02x} makes word {index} the lowest "
            f"enabled one, but this testcase asserts {_REJECT_INDEX}"
        )
        self.logger.info(
            "CHK-STIMULUS-CHIPLET-ID: %s selector_bits[0..7] = 0x%02x, so the ROM "
            "must read chiplet_id words %s and refuse on word %d; every enabled "
            "word carries the shipped 0x%08x",
            slot, _SELECTOR_MASK,
            [i for i in range(8) if _SELECTOR_MASK & (1 << i)], index,
            0xA5A5A5A5,
        )

    def check_constraint_evidence(self, console: list[str]) -> None:
        fd.assert_device_id_mismatch(self.logger, console, "chiplet_id",
                                     _REJECT_INDEX)
