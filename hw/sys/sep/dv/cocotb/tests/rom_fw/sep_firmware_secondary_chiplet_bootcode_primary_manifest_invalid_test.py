# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secondary chiplet, published manifest invalid: one attempt, then terminal.

The SMC publishes offset 0x5000, which holds zero bytes, so the ROM returns ``BAD_MAGIC``.
The SMC path has one manifest slot and no retry, so this rejection ends the boot.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_secondary_chiplet_base import (
    ALL_FAILED,
    ERR_BAD_MAGIC,
    MANIFEST_OK,
    sep_secondary_chiplet_base,
)

_INVALID_OFFSET = 0x5000

_SLOT_ERR = f"MANIFEST_ERR=0x{ERR_BAD_MAGIC:08x}"
_BOOT_FAIL = f"MANIFEST_BOOT_FAIL=0x{ERR_BAD_MAGIC:08x}"

# BAD_VERSION and BAD_LENGTH, the other codes validate_manifest_header returns.
_OTHER_HEADER_ERRORS = (0x0003_0003, 0x0003_0004)
_DOWNSTREAM_TOKENS = (
    "MANIFEST_HASH_OK", "MANIFEST_HASH_MISMATCH", "LC_USAGE_CONSTRAINT_FAIL",
    "CHIPLET_ID_MISMATCH", "PACKAGE_ID_MISMATCH", "RSA_VERIFY_START",
    "SIG_VALID", "CRYPTO_VALIDATE_OK", "CRYPTO_FAIL=", "SBOOT_OFF",
    "PLD_HASH_OK", "DECRYPT_START", MANIFEST_OK,
)
_BOOT_PROGRESS = ("PRE_JUMP", "BL1_COPIED", "BL1_JUMP=", "FUSE_SECRETS_LOCKED")


@pyuvm.test()
class sep_firmware_secondary_chiplet_bootcode_primary_manifest_invalid_test(
        sep_secondary_chiplet_base):
    """Secondary arm + published offset 0x5000 -> BAD_MAGIC, one attempt, halt."""

    manifest_offset = _INVALID_OFFSET
    expect_boot = False
    expected_error = ERR_BAD_MAGIC
    extra_required = (_SLOT_ERR, ALL_FAILED, _BOOT_FAIL)
    extra_forbidden = (
        tuple(f"MANIFEST_ERR=0x{c:08x}" for c in _OTHER_HEADER_ERRORS)
        + _DOWNSTREAM_TOKENS + _BOOT_PROGRESS
    )

    def check_outcome(self, console, status_seq, fw_done, fw_pass) -> None:
        status_hex = [hex(v) for v in status_seq]
        src = self.src_echo
        i_src = self._index_of(console, src)
        i_err = self._index_of(console, _SLOT_ERR)
        i_all = self._index_of(console, ALL_FAILED)
        i_fail = self._index_of(console, _BOOT_FAIL)

        n_err = self._count(console, "MANIFEST_ERR=")
        assert n_err == 1, (
            f"MANIFEST_ERR= appeared {n_err} times, expected exactly 1: the SMC "
            f"path has one slot, so one rejection ends the run. Console: {console}"
        )

        assert i_src < i_err < i_all < i_fail, (
            f"rejection sequence is out of order: {src}@{i_src} -> "
            f"{_SLOT_ERR}@{i_err} -> {ALL_FAILED}@{i_all} -> {_BOOT_FAIL}@{i_fail}. "
            f"Console: {console}"
        )

        assert _SLOT_ERR == f"MANIFEST_ERR=0x{self.expected_error:08x}", (
            f"the required slot-error marker {_SLOT_ERR} and the declared "
            f"expected_error 0x{self.expected_error:08x} disagree"
        )
        expected_status = 0x0F01_0000 | (self.expected_error & 0xFFFF)
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x} "
            f"(STATUS_ENCODE(ERROR, 0x{self.expected_error & 0xFFFF:04x})); observed "
            f"{status_hex}"
        )
        assert fw_done, (
            f"ROM never signalled completion; a published offset holding no "
            f"manifest must converge on a FAIL verdict. cold_scratch[1]: "
            f"{status_hex}"
        )
        assert not fw_pass, (
            "ROM signalled PASS: it booted from an offset that holds no manifest"
        )
        self.logger.info(
            "CHK-INVALID-PUBLISHED-MANIFEST: one attempt at %s, refused "
            "%s@%d, %s@%d, %s@%d, cold_scratch[1]=0x%08x, verdict FAIL",
            src, _SLOT_ERR, i_err, ALL_FAILED, i_all, _BOOT_FAIL, i_fail,
            expected_status,
        )
