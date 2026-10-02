# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secondary chiplet, valid published manifest: the SMC-SRAM boot completes.

With ``STRAPS_LO[25]`` clear the ROM must take the secondary boot arm, load the
manifest the SMC publishes at 0x1000 in one attempt, and hand off to BL1.
"""

from __future__ import annotations

import pyuvm
from env import sep_oca_console as oc
from rom_fw.sep_secondary_chiplet_base import (
    ALL_FAILED,
    DEFAULT_MANIFEST_OFFSET,
    MANIFEST_OK,
    SMC_SRAM_BASE,
    sep_secondary_chiplet_base,
)

# The SMC image is unsigned and the part is TEST_DEV, so secure boot is off.
_ACCEPT_MARKERS = ("OCA_BODY=", "MFST_VER=", MANIFEST_OK, "PAYLOAD_OK", "SBOOT_OFF")
_SECURE_ONLY = ("PUBK_SEL=", "PUBK_AUTHORIZED", "PUBK_REVOKE=", "RSA_EXEC")
_HANDOFF_MARKERS = ("BL1_COPIED", "BL1_JUMP=")
# Printed by BL1 after the handoff and by nothing in the ROM.
_BL1_MARKER = "FUSE_CHK"
_MANIFEST_ERR = "MANIFEST_ERR="


@pyuvm.test()
class sep_firmware_secondary_chiplet_bootcode_test(sep_secondary_chiplet_base):
    """Secondary arm + a valid SMC manifest at 0x1000 -> MANIFEST_OK -> BL1."""

    manifest_offset = DEFAULT_MANIFEST_OFFSET
    expect_boot = True
    extra_required = _ACCEPT_MARKERS + _HANDOFF_MARKERS + (_BL1_MARKER,)
    extra_forbidden = (_MANIFEST_ERR, ALL_FAILED) + _SECURE_ONLY

    def check_outcome(self, console, status_seq, fw_done, fw_pass) -> None:
        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [SMC_SRAM_BASE + self.manifest_offset], (
            f"slot attempts read {[hex(a.src) for a in attempts]}, expected one at the "
            f"published address. Console: {console}"
        )
        oc.assert_attempt(
            attempts[0],
            error=None,
            stage="accepted",
            ordered=_ACCEPT_MARKERS + _HANDOFF_MARKERS + (_BL1_MARKER,),
            absent=_SECURE_ONLY,
        )
        i_src = self._index_of(console, self.src_echo)
        i_ok = self._index_of(console, MANIFEST_OK)
        i_copy = self._index_of(console, "BL1_COPIED")
        i_jump = self._index_of(console, "BL1_JUMP=")
        i_bl1 = self._index_of(console, _BL1_MARKER)

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
            "CHK-SECONDARY-BOOT PASS: %s@%d, handoff at BL1_JUMP=@%d, BL1 spoke at "
            "%s@%d, cold_scratch[0] verdict PASS",
            MANIFEST_OK,
            i_ok,
            i_jump,
            _BL1_MARKER,
            i_bl1,
        )
