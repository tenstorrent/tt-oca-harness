# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The manifest handed to BL1 must still hold the OCA magic after a successful boot.

``bl0_state.sep_sram_manifest_addr`` points BL1 at the manifest that BL0 authenticated
(``bootrom/prod/doc/memory-security.adoc``, ``bootrom/prod/doc/bl1-handoff.adoc``), and
``oca_boot.c`` stages that manifest body at SEP SRAM word 0. The ``[S29]`` ICCM ECC pad
runs after staging and validation. Its ``sep_dma_zero()`` fill must not take its source
from SEP SRAM word 0. The test reads ``sram_word0_probe_o`` (``tb_top.sv``) after the boot
and requires the OCA magic there.

``ICCM_PAD=`` is required: the ROM prints it only when the ``[S29]`` pad runs, so the test
cannot pass on a build that compiles the pad out. The non-secure image keeps the RSA
modexp out of the run; the contract is the hand-off fill, not the crypto.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# rom_handoff.c prints this only when the [S29] ICCM ECC pad runs after the
# manifest is staged.
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
            f"was handed a manifest that no longer parses. A [S29] ICCM pad fill "
            f"sourced from SEP SRAM word 0 (sep_dma_zero()) overwrites the staged body."
        )
        self.logger.info(
            "CHK-MANIFEST-INTACT PASS: SRAM word 0 = %r after hand-off (word0=0x%016x)",
            magic,
            word0,
        )
