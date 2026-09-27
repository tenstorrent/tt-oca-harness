# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's decrypted payload is not a TOC; the backup boots.

THE SLOT BUNDLE IS THE UNIT OF VERIFICATION. A manifest and its payload are
confirmed together -- header, signature, decryption and plaintext validation --
and until one bundle is fully confirmed and the device begins locking for ROM
exit, switching to the other slot is legitimate. ``oca_boot.c``'s retry loop is
written that way and says so: each slot's verdict is reported as a WARN while
retries remain, and only slot exhaustion is re-reported as an ERROR alongside
``MANIFEST_ALL_FAILED``. There is no per-error retry class, so a payload defect
is no less recoverable than a bad magic word.

This testcase is that requirement stated positively: a defect found AFTER
decryption, deep in the bundle, must still fail over rather than end the boot.

WHY IT IS A SEPARATE TESTCASE. ``sep_decryption_failure_terminal_test`` covers
the terminal shape, which under bundle-level failover needs the defect in BOTH
slots. An earlier version of it corrupted only the primary and required the
backup never to be read -- the reading that procedure step 5's "no backup address
read" invites. That reading was resolved against the ROM on 2026-09-14: the
behaviour is correct and it is the expectation that was wrong. The one-slot shape
was then left uncovered, which is what this testcase restores.

THE DEFECT. ``corrupt_ciphertext`` flips a byte of CBC block 0 of the primary's
encrypted payload and re-seals the manifest over the new ciphertext. Block 0 is
chosen because ``P0 = D(C0) XOR IV``, so altering ``C0`` randomises the whole of
plaintext block 0 -- the bytes carrying the ``PTOC`` identifier. The pad lives in
the LAST block and is untouched, so decryption itself succeeds and the rejection
lands where it is aimed: ``OCA_FAIL_PAYLOAD_TOC``.

WHAT MAKES THE VERDICT ATTRIBUTABLE. ``DECRYPT_OK`` must appear, and the primary
must both drive the RSA verifier and have its signature verify --
``primary_expected_rsa_starts = 1`` and ``primary_expected_rsa_oks = 1`` -- because
this defect is refused DOWNSTREAM of the verifier rather than upstream of it.
Together they place the refusal after the signature check and after the AES engine
drained, which is the only window ``OCA_FAIL_PAYLOAD_TOC`` can come from. An
``AES_PAD_BAD`` here would mean the class key is wrong rather than the plaintext --
see the note in ``sep_efuse_lc_prod_class_key.toml``.

This is the first member of the family whose primary verifies successfully, so it
is the shape the base's docstring reserved ``primary_expected_rsa_oks`` for: with
it undeclared the base requires ``RSA_VERIFY_OK`` exactly once, and this run
prints it twice. Declaring it is what keeps "two slots verified because the defect
is downstream" distinguishable from "two slots were accepted in one run", which
would be a ROM defect rather than this stimulus.

THE BACKUP IS UNTOUCHED and is proved bootable before the run, with ``check_toc``
cleared: its TOC is ciphertext until the ROM decrypts it, so the manifest-side
checks are what apply here. The base's own backup verification cannot be used
unmodified for an encrypted image for exactly that reason.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

_SEP_ROOT = Path(__file__).resolve().parents[4]
_ENCRYPTED_IMAGE = str(_SEP_ROOT / "bootrom" / "prod" / "build" / "oca_encrypted_boot.bin")
_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod_class_key.toml"
)

_DECRYPT_OK = "DECRYPT_OK"

# Every way the run could stop before the plaintext is produced. Any of these
# means the testcase observed something other than the post-decrypt refusal it
# exists to check -- most usefully AES_PAD_BAD, which indicates a wrong class key
# rather than a wrong plaintext.
_PREMATURE = (
    "AES_PAD_BAD",
    "AES_DEC_FAIL",
    "AES_INIT_FAIL",
    "KDF_FAIL",
    "DECRYPT_NO_SECRET",
    "DECRYPT_CLASS_KEY_EMPTY",
    "PLD_HASH_TIMEOUT",
)


@pyuvm.test()
class sep_decryption_failure_failover_test(sep_primary_fail_backup_boot_base):
    """Primary decrypts to a non-TOC -> refused -> backup boots."""

    flash_image = _ENCRYPTED_IMAGE
    efuse_preload = _EFUSE_PRELOAD
    # The primary prints no token of its own for this defect; the refusal is the
    # MANIFEST_ERR code, which the base already requires.
    primary_defect_marker = ""
    primary_expected_error = pm.MANIFEST_ERR_BAD_TOC_ID
    # Refused downstream of the verifier: the primary's own RSA_EXEC must sit
    # between the primary read and the primary error, and the total must be 2.
    primary_expected_rsa_starts = 1
    # And its signature VERIFIES before it is refused, so RSA_VERIFY_OK appears
    # twice -- once per slot. This is the shape the base's docstring reserved this
    # parameter for; declaring it keeps "two slots verified because the defect is
    # downstream" distinguishable from "two slots were accepted", which would be a
    # ROM defect rather than this stimulus.
    primary_expected_rsa_oks = 1
    # Decryption must have RUN and completed, or the refusal is not the one aimed at.
    extra_required = (_DECRYPT_OK,)
    extra_forbidden = _PREMATURE

    # --- stimulus ------------------------------------------------------------
    def corrupt_primary(self, buf: bytearray) -> None:
        base = pm.payload_base(buf, "primary")
        before = bytes(buf[base : base + 16])
        at = pm.corrupt_ciphertext(buf, "primary")
        after = bytes(buf[base : base + 16])
        assert before != after, "the ciphertext flip did not change the image"
        self.logger.info(
            "CHK-STIMULUS-CIPHERTEXT: primary payload flash byte 0x%x -> 0x%02x; "
            "CBC block 0 %s -> %s (block 0 decrypts to the bytes carrying the TOC "
            "identifier); manifest re-hashed and re-signed",
            at,
            buf[at],
            before.hex(),
            after.hex(),
        )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        """As the base's, but with ``check_toc`` cleared over the backup.

        The base proves the backup is genuinely bootable before the run, which is
        the whole claim of a failover scenario. It does that with
        ``verify_sealed(buf, "backup")``, and the default ``check_toc=True``
        cannot hold for an encrypted image -- the payload begins with ciphertext,
        not ``PTOC``. The manifest-side checks still apply and still run.
        """
        self.corrupt_primary(buf)
        self.prepare_backup(buf)
        pm.verify_sealed(buf, "backup", check_toc=False)
        mm.verify_public_key(buf, "backup")
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        self.logger.info("CHK-STIMULUS-BACKUP:  %s", mm.describe(buf, "backup"))
        self.logger.info(
            "CHK-STIMULUS-BACKUP-SEALED PASS: backup passes payload_hash over its "
            "CIPHERTEXT, manifest_hash over the signed region and RSA verification of its "
            "shipped signature; its modulus hashes to the ROM's compiled-in slot-0 "
            "digest. TOC entry digests are not checked here -- they are ciphertext "
            "until the ROM decrypts them"
        )
        return buf

    def check_efuse(self, image) -> None:
        # A zero CLASS_KEY would refuse with DECRYPT_CLASS_KEY_EMPTY before any
        # plaintext existed, and a WRONG one decrypts to garbage and dies at
        # AES_PAD_BAD -- both forbidden above, but the precondition is cheaper to
        # assert here than to diagnose from a four-hour run.
        key = image.field_int("CLASS_KEY")
        want = int.from_bytes(bytes(range(32)), "little")
        assert key == want, (
            f"CLASS_KEY is 0x{key:064x}, expected 0x{want:064x} -- the 32 bytes "
            f"00 01 .. 1f that configs/oca_encrypted_boot_test.yaml encrypts with. "
            f"A different value derives a different AES key and the payload "
            f"decrypts to garbage, which surfaces as AES_PAD_BAD rather than as "
            f"anything mentioning keys"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: both slots select "
            f"ROM key slot 0 and must be able to use it, or the backup could not boot"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE PASS: CLASS_KEY is the packer's secret and "
            "CHIPLET_PUBK_REVOKE=0, so decryption and key authorization can only "
            "succeed or fail on the stimulus"
        )
