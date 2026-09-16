# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest is below the rollback floor; the backup boots.

The ``BL1_VERSION`` fuse sets a minimum security version of 1, the PRIMARY carries
0 and is refused as a rollback, and the BACKUP carries exactly 1 and boots.
``check_security_version`` is a single comparison, ``manifest_ver < fuse_ver``
(``manifest_crypto.c``), reached from ``manifest_crypto_validate:364``.

THE ORDERING IS ESTABLISHED, NOT ASSUMED, AND IT IS WHY THIS TESTCASE CAN NAME ITS
REASON. ``check_security_version`` runs at ``manifest_crypto.c``, BEFORE
``validate_signature`` -- so the rollback verdict preempts signature
type, key selection, revocation and RSA. That is what makes
``MANIFEST_ERR_VERSION_ROLLBACK`` (0x00030014, ``manifest.h``) a DEDICATED code
rather than another user of the shared ``MANIFEST_ERR_SIG_FAILED``, and it is why
this testcase asserts the intended REASON instead of merely "it was rejected":
the run must show ``VERSION_ROLLBACK`` exactly once, on the primary, with the two
values the ROM actually compared, and must never reach ``PUBK_SEL=`` on the
primary.

THE EXPECTED OUTCOME IS A COMPLETED BOOT. The reference
grades the primary's rejection ``WARNING:`` and expects ``COPY_AND_EXEC_IMAGE`` /
``EXEC_IMAGE``, so a terminal port would test a different requirement. This port
additionally requires the backup ADDRESS to be the one that served the boot,
which the reference's own pattern list for this scenario omits.

PLATFORM ADAPTATION -- THE VERSION SCALE. The reference burns a fuse whose
popcount is 91
and draws the primary from 0..10 and the backup from 91..100
(``sep_firmware_secure_boot_test.py``). Its base config carries
``security_version: 5`` (``configs/default_test.yaml:55``); the config in THIS tree
carries 0 (``bootrom/prod/configs/secure_boot_test.yaml:65,130``), so the primary
cannot be lowered below the shipped value and the asymmetry has to be built by
raising the backup instead. The comparison is a single ``<`` and is identical at
any scale, so a floor of 1 with 0 below it and 1 at it is the same test at the
smallest scale -- and putting the backup exactly AT the floor also covers the
``manifest_ver == fuse_ver`` accept boundary, which the reference's random 91..100
hits one run in ten.

PLATFORM ADAPTATION -- THE BACKUP IS RE-SIGNED. ``security_version`` is at offset
162, inside the TBS, so raising it invalidates ``manifest_hash`` and the signature.
The backup has to BOOT, so a stale signature is not survivable the way it is for
the negative testcases: it is re-sealed with the dev0 key that ships in this tree
(``env/sep_payload_mutate.reseal``), whose modulus digest is the ROM's own key slot
0 (``bootrom/prod/src/key_digests.c:18-21``). That keeps the ROM's signature check
ENABLED and passing on a legitimately signed image, which is what the reference's
packer does for the same scenario -- it is not a bypass. ``verify_signing_key``
proves the local signer reproduces the shipped signature byte for byte before any
mutation, and the shared base re-runs ``verify_sealed`` afterwards, so the re-seal
is established rather than asserted. The PRIMARY is NOT re-signed and
NOT modified: its shipped ``security_version`` is already 0, so it stays fully
sealed and the rollback is the only thing wrong with it.

Needs ``+sep_crypto_edn_force``: the backup is valid, so the full RSA-3072 modexp
runs on OTBN, which parks in UrndRefresh until EDN grants entropy. The RSA
assertions are untouched, so ``SIG_VALID`` still means the signature verified.
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

# Thermometer count of BL1_VERSION in the preload above, and the versions the two
# slots carry. The ROM rejects when manifest < fuse, so 0 is refused and 1 -- the
# equality boundary -- must be accepted.
_FUSE_SECURITY_VERSION = 1
_PRIMARY_SECURITY_VERSION = 0
_BACKUP_SECURITY_VERSION = 1

# manifest_crypto.c -- the two values the ROM echoes before comparing them.
_FUSE_VER_ECHO = f"FUSE_VER=0x{_FUSE_SECURITY_VERSION:08x}"
_PRIMARY_VER_ECHO = f"MFST_VER=0x{_PRIMARY_SECURITY_VERSION:08x}"
_BACKUP_VER_ECHO = f"MFST_VER=0x{_BACKUP_SECURITY_VERSION:08x}"


@pyuvm.test()
class sep_firmware_primary_invalid_security_version_test(sep_primary_fail_backup_boot_base):
    """Primary below the rollback floor -> rejected -> backup at the floor boots."""

    primary_defect_marker = "VERSION_ROLLBACK"
    primary_expected_error = MANIFEST_ERR_VERSION_ROLLBACK
    efuse_preload = _EFUSE_PRELOAD
    # Both slots' comparisons must be visible. Without the pair, VERSION_ROLLBACK
    # could have been produced by any version pair, including one this stimulus
    # did not create.
    extra_required = (_FUSE_VER_ECHO, _PRIMARY_VER_ECHO, _BACKUP_VER_ECHO)
    # None of these may fire. The primary is rejected upstream of key selection,
    # so every one of them appearing on the primary would mean the rollback check
    # did not preempt it; and the backup is valid, so none may fire there either.
    extra_forbidden = (
        "BAD_SIG_TYPE=",
        "BAD_KEY_IDX",
        "BAD_KEY_SEL",
        "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY",
        "PUBK_HASH_MISMATCH",
        "KEY_REVOKED",
        "RSA_VERIFY_FAIL",
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

        i_pver = index_of(_PRIMARY_VER_ECHO)
        i_roll = index_of("VERSION_ROLLBACK")
        i_bsrc = index_of(f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}")
        i_bver = index_of(_BACKUP_VER_ECHO)
        i_psel = index_of("PUBK_SEL=")

        # CHK-ROLLBACK-PAIR: the ROM read the primary's version and refused it, in
        # that order. The echo is what ties the verdict to this stimulus's version
        # pair rather than to any pair that would also roll back.
        assert 0 <= i_pver < i_roll < i_bsrc, (
            f"the rollback verdict is not attributable to the primary's version: "
            f"{_PRIMARY_VER_ECHO}@{i_pver} -> VERSION_ROLLBACK@{i_roll} -> "
            f"backup@{i_bsrc}. Console: {console}"
        )
        # CHK-ROLLBACK-PREEMPTS-KEYSEL: this is the ordering claim, and it is
        # asserted rather than argued. validate_signature echoes PUBK_SEL= as its
        # second act (manifest_crypto.c); if the FIRST such echo in the whole
        # run came before the backup read, the primary reached key selection and
        # the rollback check did not preempt it.
        assert i_psel > i_bsrc, (
            f"PUBK_SEL=@{i_psel} appeared before the backup read@{i_bsrc}: the "
            f"primary reached key selection, so check_security_version did not "
            f"preempt validate_signature. Console: {console}"
        )
        # CHK-BACKUP-ACCEPTED-AT-FLOOR: the recovering slot's version was read and
        # accepted. Equality is the boundary the ROM must pass, so this is the
        # accept half of the same comparison.
        assert i_bsrc < i_bver, (
            f"{_BACKUP_VER_ECHO}@{i_bver} did not follow the backup read@{i_bsrc}"
        )
        # The fuse floor must have been read twice -- once per slot -- so the
        # accept and the reject came from the same floor.
        n_fuse = sum(1 for line in console if _FUSE_VER_ECHO in line)
        assert n_fuse == 2, (
            f"{_FUSE_VER_ECHO} appeared {n_fuse} times, expected 2 (one per slot): "
            f"the reject and the accept must be measured against the same floor. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-ROLLBACK-FAILOVER: %s + %s@%d -> VERSION_ROLLBACK@%d -> backup@%d "
            "-> %s@%d accepted at the floor; PUBK_SEL= first seen at %d, after the "
            "backup read",
            _FUSE_VER_ECHO,
            _PRIMARY_VER_ECHO,
            i_pver,
            i_roll,
            i_bsrc,
            _BACKUP_VER_ECHO,
            i_bver,
            i_psel,
        )
