# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Recovery boot: PRIMARY_CHIPLET=1 + BOOT_RECOVERY=1 takes the SMC-SRAM path.

``boot_from_spi()`` is ``primary_chiplet && !boot_recovery``, so the recovery strap
diverts a primary chiplet from flash to the SMC-SRAM manifest. The ROM's boot-mode
branch has three arms and this testcase pins the middle one::

    if (boot_from_spi(&straps))                                -> BOOT_SPI
    else if (straps.primary_chiplet && straps.boot_recovery)   -> BOOT_RECOVERY
    else                                                       -> BOOT_SECONDARY

``primary_chiplet`` is ``STRAPS_LO[25]`` and ``boot_recovery`` is ``STRAPS_LO[19]``. The
testbench builds that word from ``+sep_boot_from_spi`` and ``+sep_straps_lo``, and the ROM
echoes it, so ``STRAPS_LO=0x02080000`` and ``STRAP primary=1 recovery=1`` show that the
ROM saw the intended combination.

``BOOT_SECONDARY`` is forbidden because both non-SPI arms wait for the same SMC manifest
and print nearly identical consoles; without it, a recovery strap that did nothing would
still pass.

The ROM can drive the SPI host and the flash holds a bootable image, so zero flash reads
shows that the ROM declined a working device.
"""

from __future__ import annotations

import pyuvm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# Must match +sep_straps_lo combined with +sep_boot_from_spi in the testlist.
_STRAPS_LO_RECOVERY = 0x0208_0000
_BOOT_RECOVERY_BIT_LO = 19

_STRAPS_LO_ECHO = f"STRAPS_LO=0x{_STRAPS_LO_RECOVERY:08x}"
_STRAP_PRIMARY_ECHO = "STRAP primary=1"  # boot_straps.c:32
_STRAP_RECOVERY_ECHO = " recovery=1"  # boot_straps.c:33
_RECOVERY_MARKER = "BOOT_RECOVERY"  # rom_main.c:635
_WAIT_SMC = "WAIT_SMC_MANIFEST"  #
# smc_sram_base (0x4006_0000, sep_smc_interface.h:57,162-164) + the manifest
# offset the responder publishes in SMC scratch[8] (0x1000).
#
# NOTE ON WHAT THE PROCEDURE SAYS: TP004 step 3 describes the offset as published
# in "SMC scratch 13/14". This ROM does not read those -- SMC_SCRATCH_SEP_SAFE_
# SRAM_START/SIZE (sep_smc_interface.h:103-104) are declared and never used --
# and takes the offset from SMC_SCRATCH_MANIFEST_ADDR_IDX = 8
# The implementation follows the ROM.
_SMC_MANIFEST_SRC = "MANIFEST_SRC=0x40061000"
_MANIFEST_OK = "MANIFEST_OK"
# Printed by BL1 after the handoff and by nothing in the ROM, so it is the
# transfer-of-control evidence the procedure asks for ("BL1 reached"). The bare
# string "BL1" is not the marker: the ROM itself prints BL1_COPIED and
# BL1_JUMP=, so a substring match on it would be satisfied without any handoff.
# The scoreboard's fw_done && fw_pass gate is the independent second half.
_BL1_MARKERS = ("FUSE_CHK",)

# The two arms this run must NOT have taken.
_SPI_MARKER = "BOOT_SPI"
_SECONDARY_MARKER = "BOOT_SECONDARY"
# Would mean the SPI controller was brought up despite the recovery strap.
_SPI_INIT_MARKERS = (">>SPI_INIT", "SPI_INIT_OK")


@pyuvm.test()
class sep_boot_recovery_test(sep_rom_ot_dma_boot_test):
    """Recovery strap set: the ROM ignores flash and boots the SMC-SRAM manifest."""

    # Replaces the inherited SPI-path tuple entirely: every marker in it is one
    # this run must not produce.
    required_markers = (
        _STRAPS_LO_ECHO,
        _STRAP_PRIMARY_ECHO,
        _STRAP_RECOVERY_ECHO,
        _RECOVERY_MARKER,
        _WAIT_SMC,
        _SMC_MANIFEST_SRC,
        _MANIFEST_OK,
    ) + _BL1_MARKERS
    forbidden_markers = (
        _SPI_MARKER,
        _SECONDARY_MARKER,
        "MANIFEST_ALL_FAILED",
    ) + _SPI_INIT_MARKERS

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # The flash is left bootable; see the module docstring. This
        # hook only records that, and self-checks the strap word.
        assert (_STRAPS_LO_RECOVERY >> _BOOT_RECOVERY_BIT_LO) & 1, (
            f"the combined strap word (0x{_STRAPS_LO_RECOVERY:08x}) does not set "
            f"boot_recovery (STRAPS_LO bit {_BOOT_RECOVERY_BIT_LO})"
        )
        self.logger.info(
            "CHK-STIMULUS-RECOVERY: STRAPS_LO=0x%08x sets primary_chiplet[25] "
            "and boot_recovery[19]; flash left intact and bootable so that "
            "declining to read it is a real observation",
            _STRAPS_LO_RECOVERY,
        )
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

    def check_transport(self, console: list[str], flash) -> None:
        txns = flash.get_transactions()

        # CHK-RECOVERY-NO-SPI: the device side of the claim. The console can only
        # say the ROM intended the SMC path; this says the flash was never
        # addressed, which is the procedure's "no SPI flash reads attempted".
        rds = ev.reads(txns)
        assert not rds, (
            f"the flash model served {len(rds)} read transaction(s) at "
            f"{[hex(ev.read_span(t)[0]) for t in rds]}: the recovery path must not "
            f"fetch from SPI at all"
        )
        self.logger.info(
            "CHK-RECOVERY-NO-SPI: flash model saw %d transaction(s), 0 reads",
            len(txns),
        )

        # CHK-RECOVERY-ORDER: the strap echo precedes the branch decision, so the
        # BOOT_RECOVERY arm is the consequence of the strap the ROM read rather
        # than a coincidence.
        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        i_straps = index_of(_STRAPS_LO_ECHO)
        i_branch = index_of(_RECOVERY_MARKER)
        i_wait = index_of(_WAIT_SMC)
        i_src = index_of(_SMC_MANIFEST_SRC)
        i_ok = index_of(_MANIFEST_OK)
        assert i_straps < i_branch < i_wait < i_src < i_ok, (
            f"recovery sequence is out of order: {_STRAPS_LO_ECHO}@{i_straps} -> "
            f"{_RECOVERY_MARKER}@{i_branch} -> {_WAIT_SMC}@{i_wait} -> "
            f"{_SMC_MANIFEST_SRC}@{i_src} -> {_MANIFEST_OK}@{i_ok}. Console: {console}"
        )
        self.logger.info(
            "CHK-RECOVERY-ORDER: STRAPS_LO@%d -> BOOT_RECOVERY@%d -> "
            "WAIT_SMC_MANIFEST@%d -> SMC manifest@%d -> MANIFEST_OK@%d",
            i_straps,
            i_branch,
            i_wait,
            i_src,
            i_ok,
        )
