# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secondary chiplet, valid published manifest: the SMC-SRAM boot completes.

THE STIMULUS. ``STRAPS_LO[25]`` left clear, so ``boot_from_spi()`` is false and
``straps.primary_chiplet && straps.boot_recovery`` is false as well -- the ROM
lands on the ``else`` arm of the ``rom_main.c`` boot-mode branch and prints
``BOOT_SECONDARY``. The SMC then publishes manifest offset 0x1000 in scratch[8],
which is where the packed SMC image really carries ``TBL1``, and the ROM loads
from ``0x4006_1000``.

WHAT THIS ROW ADDS OVER ``sep_rom_non_secure_boot_test``, which already reaches
BL1 through the same transport. That test requires ``COLD``,
``MANIFEST_HASH_OK``, ``PLD_HASH_OK``, ``BL1`` and ``FUSE_CHK`` and forbids
nothing, so it is satisfied by any of the three boot-mode arms: it would pass
unchanged on a part that took the RECOVERY arm, because recovery and secondary
converge into the same ``WAIT_SMC_MANIFEST`` loop one line later. This row is
about WHICH arm ran. It requires ``BOOT_SECONDARY`` and ``STRAP primary=0``,
forbids ``BOOT_SPI``, ``BOOT_RECOVERY``, ``STRAP primary=1`` and both
``SPI_INIT`` markers, and asserts the strap echo PRECEDES the branch.

AND THE SINGLE-ATTEMPT PROPERTY, which is what the row shares with its invalid
sibling and which no SPI-path row can establish: ``rom_manifest_boot`` gives the
SMC path ``num_retries = 0``, so ``MANIFEST_PRIMARY`` and the published
``MANIFEST_SRC=`` must each appear exactly once and ``MANIFEST_BACKUP`` must not
appear at all. A booting run does not entail that on its own -- the SPI path also
boots from its first slot -- so the count is asserted rather than inferred.

THE OUTCOME EVIDENCE. ``MANIFEST_OK`` says the ROM accepted the published
manifest, and ``FUSE_CHK`` is printed by BL1 and by nothing in the ROM, so it is
the transfer of control. The bare string ``BL1`` is deliberately not the
transfer evidence: the ROM itself prints ``BL1_COPIED`` and ``BL1_JUMP=``, so a
substring match on it would be satisfied without any handoff. The cold_scratch[0]
PASS verdict is the independent second half.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_secondary_chiplet_base import (
    ALL_FAILED,
    DEFAULT_MANIFEST_OFFSET,
    MANIFEST_OK,
    sep_secondary_chiplet_base,
)

# manifest_load.c / rom_handoff.c: the ROM accepted the manifest and handed off.
_HASH_MARKERS = ("MANIFEST_HASH_OK", "PLD_HASH_OK")
_HANDOFF_MARKERS = ("BL1_COPIED", "BL1_JUMP=")
# Printed by BL1 after the handoff and by nothing in the ROM.
_BL1_MARKER = "FUSE_CHK"
# Any slot rejection at all: this member's manifest is the valid one.
_MANIFEST_ERR = "MANIFEST_ERR="


@pyuvm.test()
class sep_firmware_secondary_chiplet_bootcode_test(sep_secondary_chiplet_base):
    """Secondary arm + a valid SMC manifest at 0x1000 -> MANIFEST_OK -> BL1."""

    manifest_offset = DEFAULT_MANIFEST_OFFSET
    expect_boot = True
    extra_required = _HASH_MARKERS + (MANIFEST_OK,) + _HANDOFF_MARKERS + (_BL1_MARKER,)
    extra_forbidden = (_MANIFEST_ERR, ALL_FAILED)

    def check_outcome(self, console, status_seq, fw_done, fw_pass) -> None:
        i_src = self._index_of(console, self.src_echo)
        i_ok = self._index_of(console, MANIFEST_OK)
        i_copy = self._index_of(console, "BL1_COPIED")
        i_jump = self._index_of(console, "BL1_JUMP=")
        i_bl1 = self._index_of(console, _BL1_MARKER)

        # CHK-SECONDARY-BOOT: acceptance, copy, jump and then BL1's own line, in
        # that order. Presence alone would be satisfied by a console in which BL1
        # spoke before the ROM had accepted anything.
        assert i_src < i_ok < i_copy < i_jump < i_bl1, (
            f"boot sequence is out of order: published read@{i_src} -> "
            f"{MANIFEST_OK}@{i_ok} -> BL1_COPIED@{i_copy} -> BL1_JUMP=@{i_jump} -> "
            f"{_BL1_MARKER}@{i_bl1}. Console: {console}"
        )
        assert fw_done, (
            f"firmware never signalled completion; a valid published manifest must "
            f"reach BL1 and report PASS. cold_scratch[1]: "
            f"{[hex(v) for v in status_seq]}"
        )
        assert fw_pass, (
            "firmware signalled FAIL on the valid published manifest, so the "
            "secondary-chiplet boot did not complete"
        )
        self.logger.info(
            "CHK-SECONDARY-BOOT: %s@%d, handoff at BL1_JUMP=@%d, BL1 spoke at "
            "%s@%d, cold_scratch[0] verdict PASS",
            MANIFEST_OK, i_ok, i_jump, _BL1_MARKER, i_bl1,
        )
