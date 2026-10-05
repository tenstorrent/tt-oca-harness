# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest lacks a required security flag; the backup boots.

The ``BL1_VERSION`` fuse sets one security flag. The primary's shipped ``security_version`` is 0
and lacks that flag, so it is refused with ``OCA_FAIL_SECURITY_VERSION``; the backup carries
exactly that flag and boots. Anti-rollback runs after key authorization and before the
signature, so the run must show that code once, on the primary, with both compared values, and
the primary must never reach ``RSA_EXEC``.

The shipped images carry ``security_version`` 0, so the asymmetry is built by raising the
backup. The field is inside the signed region, so the backup is re-sealed with the dev0 key
(``env/sep_payload_mutate.reseal``), whose modulus digest is ROM key slot 0;
``verify_signing_key`` first proves the local signer reproduces the shipped signature. The
primary is not modified and stays fully sealed.

Needs ``+esrc_noise_force``: the backup's RSA-3072 modexp stalls OTBN until EDN grants entropy.
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
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod_secver1.toml"
)

# BL1_VERSION in the preload above, and the flag words the two slots carry.
# security_version is a 128-flag bitmap: the manifest must carry every flag the
# device has, so a rejection is (device & ~manifest) != 0. Slot 0 omits the
# device's only flag and is refused; slot 1 carries exactly it, the boundary that
# must be accepted.
_FUSE_SECURITY_VERSION = 1
_PRIMARY_SECURITY_VERSION = 0
_BACKUP_SECURITY_VERSION = 1

# The low 32 flags of each side, echoed by plat_get_security_version before the
# comparison. That width is what the fuse bank backs.
_FUSE_VER_ECHO = f"FUSE_VER=0x{_FUSE_SECURITY_VERSION:08x}"
_PRIMARY_VER_ECHO = f"MFST_VER=0x{_PRIMARY_SECURITY_VERSION:08x}"
_BACKUP_VER_ECHO = f"MFST_VER=0x{_BACKUP_SECURITY_VERSION:08x}"


@pyuvm.test()
class sep_firmware_primary_invalid_security_version_test(sep_primary_fail_backup_boot_base):
    """Primary misses a device flag -> rejected -> matching backup boots."""

    primary_defect_marker = f"MANIFEST_ERR=0x{MANIFEST_ERR_VERSION_ROLLBACK:08x}"
    primary_expected_error = MANIFEST_ERR_VERSION_ROLLBACK
    efuse_preload = _EFUSE_PRELOAD
    # Both slots' comparisons must be visible. Without the pair the rejection code
    # could have been produced by any flag pair, including one this stimulus did
    # not create.
    extra_required = (_FUSE_VER_ECHO, _PRIMARY_VER_ECHO, _BACKUP_VER_ECHO)
    # None of these may fire. Anti-rollback runs after key authorization and
    # before the signature, so a key refusal here would mean the primary died
    # ahead of the comparison this test is about, and RSA_PKCS1_FAIL would mean it
    # got past one. The backup is valid, so none may fire there either.
    extra_forbidden = (
        "PUBK_ALGO_UNSUPPORTED",
        "PUBK_SLOT_RESERVED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_OTP_EMPTY",
        "PUBK_UNAUTHORIZED",
        "RSA_PKCS1_FAIL",
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        # The shipped primary carries 0, which omits the flag this preload sets.
        # The slot is read and asserted without modification, so the rollback is
        # the fuse's verdict on an untouched, sealed slot.
        got = mm.security_version(buf, "primary")
        assert got == _PRIMARY_SECURITY_VERSION, (
            f"primary security_version is {got}, expected "
            f"{_PRIMARY_SECURITY_VERSION}: the shipped image is not the baseline "
            f"this testcase relies on, so the rollback would not be attributable"
        )
        assert (got & _FUSE_SECURITY_VERSION) != _FUSE_SECURITY_VERSION, (
            f"primary security_version 0x{got:x} contains every device flag "
            f"0x{_FUSE_SECURITY_VERSION:x}, so no rollback would be detected"
        )
        # Untouched and therefore still completely sealed: the rollback is the
        # ONLY thing wrong with this slot.
        pm.verify_sealed(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-PRIMARY-VERSION: primary security_version=0x%x vs "
            "device flags 0x%x (reject expected because required flags are "
            "missing); slot untouched and still fully sealed",
            got,
            _FUSE_SECURITY_VERSION,
        )

    def prepare_backup(self, buf: bytearray) -> None:
        # verify_sealed checks that the offsets address the fields they claim, and
        # verify_signing_key checks that the local signer reproduces the packer's
        # signature byte for byte. A bad re-seal makes the ROM refuse the backup as
        # SIG_FAILED, which looks like a negative-test result.
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
        assert (got & _FUSE_SECURITY_VERSION) == _FUSE_SECURITY_VERSION, (
            f"backup security_version 0x{got:x} does not contain every device "
            f"flag 0x{_FUSE_SECURITY_VERSION:x}: it would be rejected too and "
            f"nothing would boot"
        )
        self.logger.info(
            "CHK-STIMULUS-BACKUP-VERSION: backup security_version 0x%x -> 0x%x, "
            "exactly matching the device flags 0x%x; slot re-sealed and re-signed "
            "with dev0",
            before,
            got,
            _FUSE_SECURITY_VERSION,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == _FUSE_SECURITY_VERSION, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected flag bitmap "
            f"0x{_FUSE_SECURITY_VERSION:x}: the missing device flag is what "
            f"makes the primary's version a rollback"
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

        _ROLLBACK_ERR = f"MANIFEST_ERR=0x{MANIFEST_ERR_VERSION_ROLLBACK:08x}"
        i_pver = index_of(_PRIMARY_VER_ECHO)
        i_roll = index_of(_ROLLBACK_ERR)
        i_bsrc = index_of(f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}")
        i_bver = index_of(_BACKUP_VER_ECHO)
        i_prsa = index_of("RSA_EXEC")

        # CHK-ROLLBACK-PAIR: the ROM read the primary's version and refused it, in
        # that order. The echo is what ties the verdict to this stimulus's version
        # pair rather than to any pair that would also roll back.
        assert 0 <= i_pver < i_roll < i_bsrc, (
            f"the rollback verdict is not attributable to the primary's version: "
            f"{_PRIMARY_VER_ECHO}@{i_pver} -> {_ROLLBACK_ERR}@{i_roll} -> "
            f"backup@{i_bsrc}. Console: {console}"
        )
        # CHK-ROLLBACK-PREEMPTS-SIGNATURE: anti-rollback runs after root-key
        # authorization and before signature verification. The primary must not
        # reach RSA_EXEC before the backup read.
        assert i_prsa > i_bsrc, (
            f"RSA_EXEC@{i_prsa} appeared before the backup read@{i_bsrc}: the "
            f"primary reached the verifier, so the rollback check did not preempt "
            f"the signature. Console: {console}"
        )
        # CHK-BACKUP-ACCEPTED: the recovering slot carries every device flag and
        # was accepted. Exact equality exercises the simplest accepted superset.
        assert i_bsrc < i_bver, (
            f"{_BACKUP_VER_ECHO}@{i_bver} did not follow the backup read@{i_bsrc}"
        )
        # Three reads, and the split is the point: the primary is rejected at the
        # first version check so it reads the device flags once and stops, while
        # the backup passes and reads the same flags again after the signature
        # (OCA_RECHECK_SECURITY_VERSION). A count of two would mean either the
        # primary got past the comparison or the backup was never rechecked.
        n_fuse = sum(1 for line in console if _FUSE_VER_ECHO in line)
        assert n_fuse == 3, (
            f"{_FUSE_VER_ECHO} appeared {n_fuse} times, expected 3 (once for the "
            f"rejected primary, twice for the backup that also gets the "
            f"post-signature recheck). Both slots are checked against the same "
            f"device flags. Console: {console}"
        )
        self.logger.info(
            "CHK-ROLLBACK-FAILOVER: %s + %s@%d -> rollback@%d -> backup@%d "
            "-> %s@%d accepted with all device flags; RSA_EXEC first seen at %d, "
            "after the backup read",
            _FUSE_VER_ECHO,
            _PRIMARY_VER_ECHO,
            i_pver,
            i_roll,
            i_bsrc,
            _BACKUP_VER_ECHO,
            i_bver,
            i_prsa,
        )
