# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secondary manifest at a valid but 4-modulo-8 SMC-SRAM address is refused."""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from ocah_axi_vip import RESP_SLVERR
from rom_fw.sep_secondary_chiplet_base import (
    ALL_FAILED,
    ERR_BAD_MAGIC,
    MANIFEST_OK,
    SMC_SRAM_BASE,
    sep_secondary_chiplet_base,
)

_MISALIGNED_OFFSET = 0x1004
_ERR_MANIFEST_ALIGNMENT = mm.rom_boot_err("OCA_BOOT_ERR_MANIFEST_ALIGNMENT")

_SLOT_ERR = f"MANIFEST_ERR=0x{_ERR_MANIFEST_ALIGNMENT:08x}"
_BOOT_FAIL = f"MANIFEST_BOOT_FAIL=0x{_ERR_MANIFEST_ALIGNMENT:08x}"
_ALIGN_FAIL = "MANIFEST_ALIGN_FAIL"
_BAD_MAGIC_ERR = f"MANIFEST_ERR=0x{ERR_BAD_MAGIC:08x}"
_DOWNSTREAM_TOKENS = (
    "OCA_BODY=",
    "MFST_VER=",
    "PUBK_SEL=",
    "PUBK_AUTHORIZED",
    "RSA_EXEC",
    "SBOOT_OFF",
    "PAYLOAD_LOC_FAIL",
    "PAYLOAD_OK",
    MANIFEST_OK,
)
_BOOT_PROGRESS = ("PRE_JUMP", "BL1_COPIED", "BL1_JUMP=", "FUSE_SECRETS_LOCKED")


@pyuvm.test()
class sep_firmware_secondary_manifest_offset_misaligned_test(sep_secondary_chiplet_base):
    """A complete valid SMC image shifted by four bytes is rejected at its source."""

    manifest_offset = _MISALIGNED_OFFSET
    image_manifest_offset = _MISALIGNED_OFFSET
    expect_boot = False
    expected_error = _ERR_MANIFEST_ALIGNMENT
    extra_required = (_ALIGN_FAIL, _SLOT_ERR, ALL_FAILED, _BOOT_FAIL)
    extra_forbidden = (_BAD_MAGIC_ERR,) + _DOWNSTREAM_TOKENS + _BOOT_PROGRESS

    def prepare_smc_mem(self) -> None:
        smc_mem = self.cfg.smc_mem
        assert smc_mem is not None, "the rom_boot target did not bind its SMC responder"
        src = SMC_SRAM_BASE + self.manifest_offset
        beat = src & ~0x7
        smc_mem.inject_error(beat, RESP_SLVERR, read=True, write=False)
        self.logger.info(
            "CHK-STIMULUS-MANIFEST-READ-FAULT: armed a one-shot SLVERR on containing AXI beat "
            "0x%08x for source 0x%08x; an attempted manifest read would return "
            "OCA_BOOT_ERR_DMA instead of the expected alignment error",
            beat,
            src,
        )

    def check_outcome(self, console, status_seq, fw_done, fw_pass) -> None:
        status_hex = [hex(v) for v in status_seq]
        src = self.src_echo
        i_src = self._index_of(console, src)
        i_align = self._index_of(console, _ALIGN_FAIL)
        i_err = self._index_of(console, _SLOT_ERR)
        i_all = self._index_of(console, ALL_FAILED)
        i_fail = self._index_of(console, _BOOT_FAIL)

        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [SMC_SRAM_BASE + self.manifest_offset], (
            f"slot attempts read {[hex(a.src) for a in attempts]}, expected one at "
            f"the published misaligned address. Console: {console}"
        )
        oc.assert_attempt(
            attempts[0],
            error=self.expected_error,
            stage="manifest",
            ordered=(_ALIGN_FAIL, _SLOT_ERR),
            absent=_DOWNSTREAM_TOKENS,
        )
        assert self._count(console, "MANIFEST_ERR=") == 1, (
            f"expected one alignment rejection for the SMC path's only slot. Console: {console}"
        )
        assert i_src < i_align < i_err < i_all < i_fail, (
            f"rejection sequence is out of order: {src}@{i_src} -> "
            f"{_ALIGN_FAIL}@{i_align} -> {_SLOT_ERR}@{i_err} -> "
            f"{ALL_FAILED}@{i_all} -> {_BOOT_FAIL}@{i_fail}. "
            f"Console: {console}"
        )

        status_msg = mm.rom_status_for_result(self.expected_error)
        expected_status = 0x0F01_0000 | status_msg
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x}; observed {status_hex}"
        )
        assert fw_done, (
            f"ROM never signalled completion after rejecting the misaligned source. "
            f"cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, "ROM signalled PASS from a manifest source that is not 8-byte aligned"
        self.logger.info(
            "CHK-MANIFEST-NO-READ PASS: the armed SLVERR did not replace the "
            "alignment verdict with OCA_BOOT_ERR_DMA"
        )
        self.logger.info(
            "CHK-MANIFEST-SOURCE-ALIGN PASS: valid manifest at %s rejected with "
            "%s, one slot attempted, verdict FAIL",
            src,
            _SLOT_ERR,
        )
