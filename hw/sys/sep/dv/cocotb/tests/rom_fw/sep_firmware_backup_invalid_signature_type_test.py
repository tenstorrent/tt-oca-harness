# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest declares an unsupported signature TYPE -> terminal.

The backup's ``signature_type`` is 0; 2 is avoided because it is the declared ECC P-256 type.
Forbidding ``PUBK_SEL=`` proves the type check refuses the slot before key selection.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_SIG_FAILED,
    sep_backup_manifest_fail_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_BAD_SIG_TYPE = 0
_BAD_SIG_TYPE_ECHO = f"BAD_SIG_TYPE=0x{_BAD_SIG_TYPE:08x}"


@pyuvm.test()
class sep_firmware_backup_invalid_signature_type_test(sep_backup_manifest_fail_base):
    """Primary BAD_MAGIC -> failover -> backup declares sig type 0 -> terminal."""

    backup_defect_marker = _BAD_SIG_TYPE_ECHO
    expected_error = MANIFEST_ERR_SIG_FAILED
    efuse_preload = _EFUSE_PRELOAD
    # PUBK_SEL= is printed right after the type check, so its absence proves that check ran first.
    extra_forbidden = ("PUBK_SEL=", "RSA_VERIFY_START", "RSA_VERIFY_FAIL",
                       "SIG_VALID", "CRYPTO_VALIDATE_OK", "BAD_KEY_IDX",
                       "BAD_KEY_SEL", "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY",
                       "PUBK_HASH_MISMATCH", "KEY_REVOKED", "VERSION_ROLLBACK")

    def corrupt_backup(self, buf: bytearray) -> None:
        before = mm.get_signature_type(buf, "backup")
        assert before == mm.SIG_TYPE_RSA_3072, (
            f"backup signature_type is already {before}, expected "
            f"{mm.SIG_TYPE_RSA_3072} (RSA-3072): the shipped image is not the "
            f"supported-type baseline this testcase mutates away from"
        )
        mm.set_signature_type(buf, "backup", _BAD_SIG_TYPE)
        got = mm.get_signature_type(buf, "backup")
        assert got == _BAD_SIG_TYPE, (
            f"signature_type is 0x{got:02x} after the write, expected "
            f"0x{_BAD_SIG_TYPE:02x}; the mutation did not land"
        )
        # A broken TBS hash would refuse the backup as a hash mismatch before the type check.
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-SIGTYPE: backup signature_type %d (MANIFEST_SIG_TYPE_"
            "RSA_3072) -> %d (unsupported), TBS re-hashed, signature now stale "
            "but never reached", before, got,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before validate_signature and would terminate the run first"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: a revocation "
            f"verdict would come from a different arm of the same function"
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        n = sum(1 for line in console if _BAD_SIG_TYPE_ECHO in line)
        assert n == 1, (
            f"{_BAD_SIG_TYPE_ECHO} appeared {n} times, expected exactly 1 (the "
            f"backup's). Console: {console}"
        )
        self.logger.info(
            "CHK-SIGTYPE-ECHO: ROM read %s exactly once and never echoed PUBK_SEL=",
            _BAD_SIG_TYPE_ECHO,
        )
