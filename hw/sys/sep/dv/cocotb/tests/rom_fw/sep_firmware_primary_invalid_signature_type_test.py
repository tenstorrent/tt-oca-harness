# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest declares an unsupported signature type; the backup boots.

The primary's ``signature_type`` is 0, so the ROM refuses it with ``BAD_SIG_TYPE=``.
Needs ``+sep_crypto_edn_force``: OTBN waits for EDN entropy in the backup's RSA-3072 verify.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_fail_backup_boot_base import (
    MANIFEST_ERR_SIG_FAILED,
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

# Not 2: that is MANIFEST_SIG_TYPE_ECC_P_256, a declared type the packer treats specially.
_BAD_SIG_TYPE = 0
_BAD_SIG_TYPE_ECHO = f"BAD_SIG_TYPE=0x{_BAD_SIG_TYPE:08x}"
# The backup keeps the shipped selector: ROM key slot 0.
_BACKUP_SEL_ECHO = "PUBK_SEL=0x00000000"


@pyuvm.test()
class sep_firmware_primary_invalid_signature_type_test(
        sep_primary_fail_backup_boot_base):
    """Primary declares sig type 0 -> rejected at the first arm -> backup boots."""

    primary_defect_marker = _BAD_SIG_TYPE_ECHO
    primary_expected_error = MANIFEST_ERR_SIG_FAILED
    # The type check precedes rsa_3072_verify, so the primary never drives it.
    primary_expected_rsa_starts = 0
    efuse_preload = _EFUSE_PRELOAD
    extra_required = (_BACKUP_SEL_ECHO,)
    # RSA_VERIFY_FAIL shares this error code, so forbid it to separate the two arms.
    extra_forbidden = ("RSA_VERIFY_FAIL", "BAD_KEY_IDX", "BAD_KEY_SEL",
                       "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH",
                       "KEY_REVOKED", "VERSION_ROLLBACK")

    def corrupt_primary(self, buf: bytearray) -> None:
        # No manifest_identifier corruption: the primary must reach validate_signature.
        before = mm.get_signature_type(buf, "primary")
        assert before == mm.SIG_TYPE_RSA_3072, (
            f"primary signature_type is already {before}, expected "
            f"{mm.SIG_TYPE_RSA_3072} (RSA-3072): the shipped image is not the "
            f"supported-type baseline this testcase mutates away from"
        )
        mm.set_signature_type(buf, "primary", _BAD_SIG_TYPE)
        got = mm.get_signature_type(buf, "primary")
        assert got == _BAD_SIG_TYPE, (
            f"signature_type is 0x{got:02x} after the write, expected "
            f"0x{_BAD_SIG_TYPE:02x}; the mutation did not land"
        )
        # A stale TBS hash would reject the primary before the type check.
        mm.verify_layout(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-SIGTYPE: primary signature_type %d (MANIFEST_SIG_TYPE_"
            "RSA_3072) -> %d (unsupported), TBS re-hashed, signature now stale but "
            "never reached", before, got,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before validate_signature and would reject the primary first"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: a revocation verdict "
            f"would come from a different arm of the same function, and the backup "
            f"selects ROM slot 0 and must be able to use it or nothing would boot"
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        i_type = index_of(_BAD_SIG_TYPE_ECHO)
        i_bsrc = index_of(f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}")
        i_bsel = index_of(_BACKUP_SEL_ECHO)

        n_sel = sum(1 for line in console if "PUBK_SEL=" in line)
        assert n_sel == 1, (
            f"PUBK_SEL= appeared {n_sel} times, expected exactly 1 (the backup's). "
            f"More than one means the primary reached the selector echo at "
            f"manifest_crypto.c:167, so the signature-type check at :162-165 did "
            f"not preempt key selection. Console: {console}"
        )
        assert 0 <= i_bsrc < i_bsel, (
            f"{_BACKUP_SEL_ECHO}@{i_bsel} did not follow the backup read@{i_bsrc}: "
            f"the single selector echo is not the booting slot's. Console: {console}"
        )
        assert 0 <= i_type < i_bsrc, (
            f"{_BAD_SIG_TYPE_ECHO}@{i_type} does not precede the backup read"
            f"@{i_bsrc}: the verdict is not attributable to the primary. "
            f"Console: {console}"
        )
        n_type = sum(1 for line in console if _BAD_SIG_TYPE_ECHO in line)
        assert n_type == 1, (
            f"{_BAD_SIG_TYPE_ECHO} appeared {n_type} times, expected exactly 1 (the "
            f"primary's); the backup must not declare a bad type. Console: {console}"
        )
        self.logger.info(
            "CHK-SIGTYPE-PREEMPTS-KEYSEL: %s@%d before the backup read@%d, and "
            "PUBK_SEL= appears exactly once (%s@%d, the backup's) -- the type check "
            "ran ahead of the selector echo",
            _BAD_SIG_TYPE_ECHO, i_type, i_bsrc, _BACKUP_SEL_ECHO, i_bsel,
        )
