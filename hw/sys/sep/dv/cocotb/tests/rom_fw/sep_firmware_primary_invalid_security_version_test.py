# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest is below the rollback floor; the backup boots.

The ``BL1_VERSION`` fuse sets a minimum security version of 1, the PRIMARY carries
0 and is refused as a rollback, and the BACKUP carries exactly 1 and boots.
The anti-rollback check is a single comparison, ``manifest_ver < fuse_ver``, reached from ``manifest validation:364``.

THE ORDERING IS ESTABLISHED, NOT ASSUMED, AND IT IS WHY THIS TESTCASE CAN NAME ITS
REASON. The anti-rollback check runs, BEFORE
the signature path -- so the rollback verdict preempts signature
type, key selection, revocation and RSA. That is what makes
``MANIFEST_ERR_VERSION_ROLLBACK`` -- ``OCA_FAIL_SECURITY_VERSION``, a DEDICATED code
rather than another user of the shared ``MANIFEST_ERR_SIG_FAILED``, and it is why
this testcase asserts the intended REASON instead of merely "it was rejected":
the run must show that code exactly once, on the primary, with the two
values the ROM actually compared, and must never reach ``PUBK_SEL=`` on the
primary.

The expected outcome is A Completed boot.

Platform adaptation -- The version scale. Its base config carries ``security_version:
5`` (``configs/default_test.yaml:55``); the config in THIS tree carries 0
(``bootrom/prod/configs/secure_boot_test.yaml:65,130``), so the primary cannot be
lowered below the shipped value and the asymmetry has to be built by raising the backup
instead.

Platform adaptation -- The backup is re-SIGNED. ``security_version`` is at offset 162,
inside the signed region, so raising it invalidates ``manifest_hash`` and the signature. The
backup has to BOOT, so a stale signature is not survivable the way it is for the
negative testcases: it is re-sealed with the dev0 key that ships in this tree
(``env/sep_payload_mutate.reseal``), whose modulus digest is the ROM's own key slot 0
(``digest_rom_key0`` in the generated ``bootrom/prod/<build dir>/key_digests.c``).
``verify_signing_key`` proves the local
signer reproduces the shipped signature byte for byte before any mutation, and the
shared base re-runs ``verify_sealed`` afterwards, so the re-seal is established rather
than asserted. The PRIMARY is deliberately NOT re-signed and NOT modified: its shipped
``security_version`` is already 0, so it stays fully sealed and the rollback is the only
thing wrong with it.

Needs ``+esrc_noise_force``: the backup is valid, so the full RSA-3072 modexp
runs on OTBN, which parks in UrndRefresh until EDN grants entropy. The RSA
assertions are untouched, so ``RSA_VERIFY_OK`` still means the signature verified.
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
    """Primary below the rollback floor -> rejected -> backup at the floor boots."""

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
        # The shipped primary already carries 0, which is below the floor this
        # preload sets. Assert that rather than write it: a write would be a no-op
        # wearing a mutation's name, and reading the real value is what proves the
        # rollback is the fuse's verdict on an untouched, still-sealed slot.
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
        # Untouched and therefore still completely sealed: the rollback is the
        # ONLY thing wrong with this slot.
        pm.verify_sealed(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-PRIMARY-VERSION: primary security_version=%d vs fuse "
            "floor %d (reject expected because %d < %d); slot untouched and still "
            "fully sealed",
            got,
            _FUSE_SECURITY_VERSION,
            got,
            _FUSE_SECURITY_VERSION,
        )

    def prepare_backup(self, buf: bytearray) -> None:
        # Anchor first: verify_sealed proves the offsets address the fields they
        # claim, and verify_signing_key proves the local signer reproduces the
        # packer's signature byte for byte. Without the second, a re-seal would be
        # an unverified claim whose failure mode -- the ROM refusing the backup as
        # SIG_FAILED -- looks like a plausible negative-test result.
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
            before,
            got,
            _FUSE_SECURITY_VERSION,
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
        # CHK-ROLLBACK-PREEMPTS-SIGNATURE: the ordering claim, asserted rather
        # than argued. Anti-rollback is checked after the root key is authorized
        # and BEFORE the signature, so the primary must never reach the verifier:
        # if the first RSA_EXEC in the run came before the backup read, a manifest
        # below the floor was handed to the verifier anyway.
        assert i_prsa > i_bsrc, (
            f"RSA_EXEC@{i_prsa} appeared before the backup read@{i_bsrc}: the "
            f"primary reached the verifier, so the rollback check did not preempt "
            f"the signature. Console: {console}"
        )
        # CHK-BACKUP-ACCEPTED-AT-FLOOR: the recovering slot's version was read and
        # accepted. Equality is the boundary the ROM must pass, so this is the
        # accept half of the same comparison.
        assert i_bsrc < i_bver, (
            f"{_BACKUP_VER_ECHO}@{i_bver} did not follow the backup read@{i_bsrc}"
        )
        # The fuse floor must have been read twice -- once per slot -- so the
        # accept and the reject came from the same floor.
        # Three, and the split is the point: the primary is rejected AT the first
        # version check so it reads the flags once and stops, while the backup
        # passes and is checked again after the signature
        # (OCA_RECHECK_SECURITY_VERSION). A count of two would mean either the
        # primary got past the comparison or the backup was never rechecked.
        n_fuse = sum(1 for line in console if _FUSE_VER_ECHO in line)
        assert n_fuse == 3, (
            f"{_FUSE_VER_ECHO} appeared {n_fuse} times, expected 3 (once for the "
            f"rejected primary, twice for the backup that also gets the "
            f"post-signature recheck). Both slots are measured against the same "
            f"floor. Console: {console}"
        )
        self.logger.info(
            "CHK-ROLLBACK-FAILOVER: %s + %s@%d -> rollback@%d -> backup@%d "
            "-> %s@%d accepted at the floor; RSA_EXEC first seen at %d, after the "
            "backup read",
            _FUSE_VER_ECHO,
            _PRIMARY_VER_ECHO,
            i_pver,
            i_roll,
            i_bsrc,
            _BACKUP_VER_ECHO,
            i_bver,
            i_prsa,
        )
