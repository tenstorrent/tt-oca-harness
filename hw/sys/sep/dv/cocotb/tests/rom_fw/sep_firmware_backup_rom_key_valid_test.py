# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest names a VALID ROM key index and boots -> success.

The positive member of the ROM-key family. The primary's ``manifest_identifier``
is corrupted to force failover, the backup's ``public_key_sel`` names ROM key slot
0 -- populated, unrevoked, and the slot the image is signed against -- and the ROM
must complete the boot from it.

A POSITIVE TEST THAT PASSES BECAUSE KEY SELECTION NEVER RAN WOULD PROVE NOTHING,
so "it booted" is not accepted as the result here. The run must show the ROM
reading the selector and the revocation bitmap and then verifying with them:

  * ``PUBK_SEL=0x00000000`` -- the selector the ROM read out of the backup
    manifest, so the boot is attributable to slot 0
    rather than to some other or absent selection;
  * ``PUBK_REVOKE=0x00000000`` -- the fuse word the revocation check read, proving the revocation check ran and
    PERMITTED this slot rather than being skipped. Note this marker alone does
    NOT prove the ROM-key arm was taken: the revocation check is called from
    the fuse-key arm too. What excludes that arm is
    the ``PUBK_SEL=0x00000000`` value above -- slot 0 is ROM classical key 0 --
    together with ``PUBK_SEL_AMBIGUOUS`` and ``PUBK_OTP_EMPTY`` being forbidden
    below;
  * ``RSA_EXEC`` then ``RSA_VERIFY_OK`` -- the modulus reached the verifier
    and the signature really verified, which only
    happens after the index bound, the revocation check and the digest bind have
    all passed;
  * and the shared base requires the failover ordering and the device-side read
    order, so the boot came from the backup ADDRESS and not from the primary.

Its ``BACKUP_ROM_KEY_VALID`` expectation ends in ``BACKUP_BL1_LOADED /
COPY_AND_EXEC_IMAGE / EXEC_IMAGE`` and -- unlike its own primary-side twin -- omits
``STATUS: USING_ROM_KEY``, so it never requires evidence that the ROM-key path was the
one taken. The markers above close that gap rather than reproduce it.

The matched pair is the strongest evidence here. This testcase and
``sep_firmware_backup_pubkey_rom_0_revoked_key_test`` build their flash image from the
same two calls -- ``mm.break_magic(primary)`` and ``select_backup_rom_slot(buf, 0)`` --
so the bytes are identical by construction. The ONLY difference between them is one bit
of ``CHIPLET_PUBK_REVOKE``. Fuse clear boots; bit 0 set is refused with the revocation
error code and never reaches ``RSA_EXEC``. Nothing else about revocation needs arguing.

Needs ``+esrc_noise_force``: the backup is valid, so the full RSA-3072 modexp
runs on OTBN, which parks in UrndRefresh until EDN grants entropy. The plusarg
injects raw noise at the decorrelator inputs; the ROM drives the real health
tests, CSRNG, EDN, and OTBN handshakes. The RSA assertions are untouched, so
``RSA_VERIFY_OK`` still means the signature really verified.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_fail_backup_boot_base import (
    MANIFEST_ERR_BAD_MAGIC,
    sep_primary_fail_backup_boot_base,
)
from rom_fw.sep_pubkey_rom_revoked_base import select_backup_rom_slot

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# The slot the shipped image is signed against (configs/oca_secure_boot_test.yaml),
# so the positive case needs no graft. All six slots carry a digest and their own
# key; slot 0 is simply the one the shipped bytes already bind to.
_VALID_SLOT = 0
_PUBK_SEL_ECHO = f"PUBK_SEL=0x{_VALID_SLOT:08x}"
_REVOKE_ECHO = "PUBK_REVOKE=0x00000000"


@pyuvm.test()
class sep_firmware_backup_rom_key_valid_test(sep_primary_fail_backup_boot_base):
    """Primary BAD_MAGIC -> failover -> backup names valid ROM slot 0 -> boots."""

    # The primary fails structurally, before any crypto runs, so it produces no
    # dedicated console token of its own -- only the BAD_MAGIC slot error.
    primary_defect_marker = ""
    primary_expected_error = MANIFEST_ERR_BAD_MAGIC
    efuse_preload = _EFUSE_PRELOAD
    extra_required = (_PUBK_SEL_ECHO, _REVOKE_ECHO)
    # Every rejecting arm of the signature path. This is a positive test, so none
    # of them may fire: seeing any one would mean the boot completed in spite of a
    # key-selection complaint, or from a slot this testcase did not select.
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
        # The same failover trigger the revoke family uses: the magic word, which
        # the manifest header check rejects before any hash or crypto work, so the trigger cannot interact with the key
        # selection under test.
        mm.break_magic(buf, "primary")

    def prepare_backup(self, buf: bytearray) -> None:
        got, tbs_changed = select_backup_rom_slot(buf, _VALID_SLOT)
        assert not tbs_changed, (
            f"writing ROM slot {_VALID_SLOT} into the backup selector changed the "
            f"TBS, so the shipped image did not already select it; the signature "
            f"is now stale and this positive test could not boot for the reason it "
            f"claims"
        )
        self.logger.info(
            "CHK-STIMULUS-VALID-SLOT: backup public_key_sel=0x%04x (ROM key slot "
            "%d, populated and unrevoked); TBS unchanged, so the backup keeps its "
            "original dev0 signature",
            got,
            _VALID_SLOT,
        )

    def check_efuse(self, image) -> None:
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: slot "
            f"{_VALID_SLOT} must not be revoked, or this positive case becomes its "
            f"own negative twin"
        )
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        i_bsrc = index_of(f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}")
        i_sel = index_of(_PUBK_SEL_ECHO)
        i_revoke = index_of(_REVOKE_ECHO)
        i_rsa = index_of("RSA_EXEC")

        # CHK-KEYSEL-RAN: key selection is the feature under test, so it must have
        # executed on the BACKUP and in the architected order -- selector read,
        # revocation bitmap consulted, and only then the verifier driven. Presence
        # alone would also be satisfied by a primary-side echo, which is why the
        # backup read bounds it from below.
        assert i_bsrc < i_sel < i_rsa, (
            f"key selection did not run on the backup before the signature step: "
            f"backup@{i_bsrc} -> {_PUBK_SEL_ECHO}@{i_sel} -> RSA_EXEC"
            f"@{i_rsa}. Console: {console}"
        )
        assert i_sel < i_revoke < i_rsa, (
            f"the revocation bitmap was not consulted between the selector and the "
            f"verifier: {_PUBK_SEL_ECHO}@{i_sel} -> {_REVOKE_ECHO}@{i_revoke} -> "
            f"RSA_EXEC@{i_rsa}. Console: {console}"
        )
        # Exactly once each: the primary died at BAD_MAGIC before any crypto, so a
        # second echo would mean a slot this testcase did not account for also
        # reached key selection.
        for marker in (_PUBK_SEL_ECHO, _REVOKE_ECHO):
            n = sum(1 for line in console if marker in line)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the backup's). "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-KEYSEL-RAN: backup@%d -> %s@%d -> %s@%d -> RSA_EXEC@%d; "
            "the ROM-key path executed and permitted slot %d",
            i_bsrc,
            _PUBK_SEL_ECHO,
            i_sel,
            _REVOKE_ECHO,
            i_revoke,
            i_rsa,
            _VALID_SLOT,
        )
