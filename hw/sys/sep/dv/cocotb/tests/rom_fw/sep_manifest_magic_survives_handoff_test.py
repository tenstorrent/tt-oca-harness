# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The manifest handed to BL1 must still parse after a successful boot (PyUVM).

FEATURE UNDER TEST. ``bl0_state.sep_sram_manifest_addr`` points BL1 at the
manifest BL0 authenticated, and ``doc/memory-security.adoc`` and
``doc/bl1-handoff.adoc`` both say BL1 consumes it. That is a contract about the
bytes in SEP SRAM at hand-off, and nothing inside the ROM re-reads them, so it
holds only if something checks.

WHY IT DID NOT HOLD. ``sep_dma_zero()`` needs a source address even for a fill,
and it used to take the first word of SEP SRAM -- which is exactly where
``oca_boot.c`` stages the manifest body. The comment claimed the word was
"consumed before any payload is staged there", true of the ``[S16]`` ICCM clear
and false of the ICCM ECC pad at ``[S29]``, which runs after staging and
validation and is in the default build. So an ordinary successful boot zeroed
``body[0..3]`` -- the OCA magic -- and handed BL1 a manifest returning
``OCA_FAIL_MAGIC``. The ROM reported a clean boot throughout.

WHAT MAKES THIS TESTABLE WITHOUT BL1 COOPERATION. ``sram_word0_probe_o``
(``tb_top.sv``) is a continuous assign from SEP SRAM word 0, the 64 bits holding
the magic. Reading it after the boot completes asks the memory what BL1 would
read, without needing a BL1 that parses manifests.

``ICCM_PAD=`` IS REQUIRED, NOT INCIDENTAL. It is printed only when the ``[S29]``
pad actually runs, which needs ``ROM_ICCM_CLEAR_ENABLE=1``,
``ROM_ICCM_CLEAR_FULL=0`` and a BL1 that lands in ICCM. Without that marker this
testcase would pass on a build where the destructive path was compiled out, and
would be asserting nothing. It is listed first for that reason.

The non-secure image is deliberate: the defect is in the hand-off fill, not in
the crypto, and the signed image would add an RSA-3072 modexp to every run of a
testcase that does not exercise it.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# Printed by rom_handoff.c only when the [S29] ICCM ECC pad runs -- the call
# site whose fill used to land on the staged manifest.
_ICCM_PAD = "ICCM_PAD="
# Printed immediately before the jump, so the pad is known to have run as part
# of a hand-off rather than of an aborted attempt.
_BL1_JUMP = "BL1_JUMP="


@pyuvm.test()
class sep_manifest_magic_survives_handoff_test(sep_rom_ot_dma_boot_test):
    """Boot normally, then require SEP SRAM word 0 to still hold the OCA magic."""

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _ICCM_PAD,
        _BL1_JUMP,
    )

    def check_transport(self, console, flash) -> None:
        """Read SEP SRAM word 0 after the boot and require the magic intact."""
        word0 = self.rd(cocotb.top.sram_word0_probe_o)
        # mem[] is 64 bits little-endian, so byte 0 of SRAM is the low byte.
        magic = (word0 & 0xFFFF_FFFF).to_bytes(4, "little")

        expected = bytes(mm.MANIFEST_MAGIC)
        assert magic == expected, (
            f"SEP SRAM word 0 is {magic!r} (word0=0x{word0:016x}), expected "
            f"{expected!r}. bl0_state.sep_sram_manifest_addr points here, so BL1 "
            f"was handed a manifest that no longer parses. The [S29] ICCM pad "
            f"filled from the staged body -- see sep_dma_zero()."
        )
        self.logger.info(
            "CHK-MANIFEST-INTACT PASS: SRAM word 0 = %r after hand-off (word0=0x%016x)",
            magic,
            word0,
        )
