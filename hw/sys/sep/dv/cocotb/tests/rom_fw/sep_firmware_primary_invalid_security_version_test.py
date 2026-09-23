# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest is below the rollback floor; the backup boots.

The fuse floor is 1; the primary at 0 is a rollback, the re-signed backup at 1 boots.
Needs ``+sep_crypto_edn_force``: OTBN waits for EDN entropy in the backup's RSA-3072 verify.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw.sep_primary_fail_backup_boot_base import (
    MANIFEST_ERR_VERSION_ROLLBACK,
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod_secver1.toml"
)

# Must match the BL1_VERSION thermometer count in the preload; manifest < fuse is refused.
_FUSE_SECURITY_VERSION = 1
_PRIMARY_SECURITY_VERSION = 0
_BACKUP_SECURITY_VERSION = 1

_FUSE_VER_ECHO = f"FUSE_VER=0x{_FUSE_SECURITY_VERSION:08x}"
_PRIMARY_VER_ECHO = f"MFST_VER=0x{_PRIMARY_SECURITY_VERSION:08x}"
_BACKUP_VER_ECHO = f"MFST_VER=0x{_BACKUP_SECURITY_VERSION:08x}"


@pyuvm.test()
class sep_firmware_primary_invalid_security_version_test(
        sep_primary_fail_backup_boot_base):
    """Primary below the rollback floor -> rejected -> backup at the floor boots."""

    primary_defect_marker = "VERSION_ROLLBACK"
    primary_expected_error = MANIFEST_ERR_VERSION_ROLLBACK
    efuse_preload = _EFUSE_PRELOAD
    extra_required = (_FUSE_VER_ECHO, _PRIMARY_VER_ECHO, _BACKUP_VER_ECHO)
    extra_forbidden = ("BAD_SIG_TYPE=", "BAD_KEY_IDX", "BAD_KEY_SEL",
                       "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH",
                       "KEY_REVOKED", "RSA_VERIFY_FAIL")

    def corrupt_primary(self, buf: bytearray) -> None:
        # The shipped primary already carries 0, so it stays untouched and sealed.
        got = mm.security_version(buf, "primary")
        assert got == _PRIMARY_SECURITY_VERSION, (
            f"primary security_version is {got}, expected "
            f"{_PRIMARY_SECURITY_VERSION}: the shipped image is not the baseline "
            f"this testcase relies on, so the rollback would not be attributable"
        )
        assert got < _FUSE_SECURITY_VERSION, (
            f"primary security_version {got} is not below the fuse floor "
            f"{_FUSE_SECURITY_VERSION}, so no rollback would be detected"
        )
        pm.verify_sealed(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-PRIMARY-VERSION: primary security_version=%d vs fuse "
            "floor %d (reject expected because %d < %d); slot untouched and still "
            "fully sealed", got, _FUSE_SECURITY_VERSION, got,
            _FUSE_SECURITY_VERSION,
        )

    def prepare_backup(self, buf: bytearray) -> None:
        # A broken re-seal would look like a plausible SIG_FAILED, so prove the signer first.
        pm.verify_sealed(buf, "backup")
        pm.verify_signing_key(buf, "backup")
        before = mm.security_version(buf, "backup")
        mm.set_security_version(buf, "backup", _BACKUP_SECURITY_VERSION)
        pm.reseal(buf, "backup")
        got = mm.security_version(buf, "backup")
        assert got == _BACKUP_SECURITY_VERSION, (
            f"backup security_version is {got} after the write, expected "
            f"{_BACKUP_SECURITY_VERSION}; the mutation did not land"
        )
        assert got >= _FUSE_SECURITY_VERSION, (
            f"backup security_version {got} is below the fuse floor "
            f"{_FUSE_SECURITY_VERSION}: it would be rejected too and nothing "
            f"would boot"
        )
        self.logger.info(
            "CHK-STIMULUS-BACKUP-VERSION: backup security_version %d -> %d, "
            "exactly at the fuse floor %d (the `manifest_ver == fuse_ver` accept "
            "boundary); slot re-sealed and re-signed with dev0",
            before, got, _FUSE_SECURITY_VERSION,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        popcount = bin(bl1_ver).count("1")
        assert popcount == _FUSE_SECURITY_VERSION, (
            f"BL1_VERSION 0x{bl1_ver:x} has thermometer count {popcount}, expected "
            f"{_FUSE_SECURITY_VERSION}: the fuse minimum is what makes the "
            f"primary's version a rollback"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: a revocation "
            f"verdict comes from a different check and the backup must be able to "
            f"use ROM slot 0"
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        i_pver = index_of(_PRIMARY_VER_ECHO)
        i_roll = index_of("VERSION_ROLLBACK")
        i_bsrc = index_of(f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}")
        i_bver = index_of(_BACKUP_VER_ECHO)
        i_psel = index_of("PUBK_SEL=")

        assert 0 <= i_pver < i_roll < i_bsrc, (
            f"the rollback verdict is not attributable to the primary's version: "
            f"{_PRIMARY_VER_ECHO}@{i_pver} -> VERSION_ROLLBACK@{i_roll} -> "
            f"backup@{i_bsrc}. Console: {console}"
        )
        assert i_psel > i_bsrc, (
            f"PUBK_SEL=@{i_psel} appeared before the backup read@{i_bsrc}: the "
            f"primary reached key selection, so check_security_version did not "
            f"preempt validate_signature. Console: {console}"
        )
        assert i_bsrc < i_bver, (
            f"{_BACKUP_VER_ECHO}@{i_bver} did not follow the backup read@{i_bsrc}"
        )
        n_fuse = sum(1 for line in console if _FUSE_VER_ECHO in line)
        assert n_fuse == 2, (
            f"{_FUSE_VER_ECHO} appeared {n_fuse} times, expected 2 (one per slot): "
            f"the reject and the accept must be measured against the same floor. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-ROLLBACK-FAILOVER: %s + %s@%d -> VERSION_ROLLBACK@%d -> backup@%d "
            "-> %s@%d accepted at the floor; PUBK_SEL= first seen at %d, after the "
            "backup read", _FUSE_VER_ECHO, _PRIMARY_VER_ECHO, i_pver, i_roll,
            i_bsrc, _BACKUP_VER_ECHO, i_bver, i_psel,
        )
