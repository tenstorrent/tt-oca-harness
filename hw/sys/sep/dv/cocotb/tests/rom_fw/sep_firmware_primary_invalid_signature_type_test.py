# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest declares an unsupported signature TYPE; the backup boots.

The PRIMARY's ``signature_type`` is set to 0. Only
``MANIFEST_SIG_TYPE_RSA_3072`` (1) agrees with the declared crypto field sizes, so
``oca_check_crypto_field_sizes()`` refuses the slot structurally -- before
``plat_is_key_authorized()`` runs -- returning ``MANIFEST_ERR_SIG_TYPE_INVALID``
with no ``PUBK_*`` token printed for the primary at all.

THE PRIMARY MUST NOT BE BROKEN ANY OTHER WAY. So there is no BAD_MAGIC failover trigger
here.

``generate_verified_signature`` then returns an EMPTY bytearray, and
``min_signature_size`` stayed 0 so the size check accepts it. Note also that 0 is
literally ``ManifestSignatureType.NO_SIGNATURE``. THIS port keeps the shipped,
syntactically complete, merely stale dev0 signature, which is the harder case: the ROM
must refuse on the declared TYPE alone with a plausible signature sitting right there.
Both are refused before the signature is read at all, so the outcome is the same and the
stimulus here is strictly less forgiving.

The expected outcome is A Completed boot.

WHY 0, And why A Fixed value. The ROM's check is a single ``!=`` against RSA-3072, so
every value in that set exercises the identical arm, and fixing it is what lets this
testcase assert the exact ``PUBK_ALGO_UNSUPPORTED`` the ROM echoed rather than accepting
any value at all.

**HOW THIS IS TOLD APART FROM ``sep_firmware_primary_invalid_signature_test``.**
The error code now does most of the work: this member ends at
``MANIFEST_ERR_SIG_TYPE_INVALID`` from the structural check, its sibling at
``MANIFEST_ERR_SIG_FAILED`` from the verifier. The console separates them in BOTH
directions on top of that, and both halves are asserted here:

  * the type check is the FIRST arm of the signature path, ahead even of the ``PUBK_SEL=`` echo at
. So this run must show the primary's selector NEVER echoed: with the
    backup booting from ROM slot 0, ``PUBK_SEL=0x00000000`` is pinned to exactly
    **one** occurrence, the backup's. Its sibling pins the same token to **two**,
    because there both manifests reach key selection. That single count makes the
    two mutually exclusive on one log;
  * ``RSA_PKCS1_FAIL`` is forbidden here and required there, and
    ``PUBK_ALGO_UNSUPPORTED0x00000000`` is required here and forbidden there.

Platform adaptation -- MARKER. This ROM *defines* that code
(``bootrom/prod/include/status_values.h:11``) but never EMITS it: there is no
``report_status`` call for it anywhere under ``bootrom/prod/src``, so the architected
status ring carries only the generic terminal code and the debug console token is the
only per-reason evidence available.

``signature_type`` is one byte at manifest offset 165, INSIDE the hashed signed region
(field order; ``sep_manifest_mutate.OFF_SIGNATURE_TYPE``), so the
helper re-hashes. It cannot be a signature-region patch: the field is covered by
``manifest_hash``, so an un-rehashed write dies in the manifest loop as a hash
mismatch and never reaches the type check. No re-sign is needed or possible -- the
type is rejected before ``rsa_3072_verify``, so the
now-stale signature is never examined, and the base's ``primary_expected_rsa_starts
= 0`` is what checks that ordering instead of assuming it.

Needs ``+esrc_noise_force``: the backup is valid, so the full RSA-3072 modexp
runs on OTBN, which parks in UrndRefresh until EDN grants entropy. The RSA
assertions are untouched, so ``RSA_VERIFY_OK`` still means the signature verified.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_fail_backup_boot_base import (
    MANIFEST_ERR_SIG_TYPE_INVALID,
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# Fixed rather than drawn at random, so the refusal is attributable to this
# stimulus. See the docstring for why not 2.
_BAD_SIG_TYPE = 0
# The refusal is structural -- oca_check_crypto_field_sizes() rejects a type that
# disagrees with the field sizes before plat_is_key_authorized() is called -- so
# there is no PUBK_* token to key on and the error code IS the defect marker.
_BAD_SIG_TYPE_ECHO = f"MANIFEST_ERR=0x{MANIFEST_ERR_SIG_TYPE_INVALID:08x}"
# The backup keeps the shipped selector: ROM key slot 0
# (configs/secure_boot_test.yaml:112-114).
_BACKUP_SEL_ECHO = "PUBK_SEL=0x00000000"


@pyuvm.test()
class sep_firmware_primary_invalid_signature_type_test(sep_primary_fail_backup_boot_base):
    """Primary declares sig type 0 -> rejected at the first arm -> backup boots."""

    primary_defect_marker = _BAD_SIG_TYPE_ECHO
    primary_expected_error = MANIFEST_ERR_SIG_TYPE_INVALID
    # The type check precedes rsa_3072_verify, so the primary never drives it.
    primary_expected_rsa_starts = 0
    efuse_preload = _EFUSE_PRELOAD
    # The backup's selector, so "the backup booted" is tied to slot 0 rather than
    # to an unread selection.
    extra_required = (_BACKUP_SEL_ECHO,)
    # RSA_PKCS1_FAIL is the discriminator against the signature-VALUE sibling,
    # which shares this error code. The rest are the later arms of
    # the signature path: the primary dies at the first arm and the backup is
    # valid, so none of them may fire on either slot.
    extra_forbidden = (
        # plat_is_key_authorized() is unreachable on the primary, its algorithm arm
        # included: the structural check refuses before the callback runs. The
        # primary's PUBK_SEL= would say otherwise, but the backup legitimately
        # prints one, so PUBK_SEL= cannot be forbidden outright here -- the
        # primary's absence is pinned by _BACKUP_SEL_ECHO being the only one.
        "PUBK_ALGO_UNSUPPORTED",
        "RSA_PKCS1_FAIL",
        "PUBK_SLOT_RESERVED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_OTP_EMPTY",
        "PUBK_UNAUTHORIZED",
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        # No manifest_identifier corruption: the primary must reach
        # the signature path.
        before = mm.signature_type(buf, "primary")
        assert before == mm.SIG_TYPE_RSA_3072, (
            f"primary signature_type is already {before}, expected "
            f"{mm.SIG_TYPE_RSA_3072} (RSA-3072): the shipped image is not the "
            f"supported-type baseline this testcase mutates away from"
        )
        mm.set_signature_type(buf, "primary", _BAD_SIG_TYPE)
        got = mm.signature_type(buf, "primary")
        assert got == _BAD_SIG_TYPE, (
            f"signature_type is 0x{got:02x} after the write, expected "
            f"0x{_BAD_SIG_TYPE:02x}; the mutation did not land"
        )
        # The re-hash must have restored a valid signed region hash, or the primary is thrown
        # out in the manifest loop as a hash mismatch and the type check -- the only
        # thing this testcase is about -- never runs.
        mm.verify_layout(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-SIGTYPE: primary signature_type %d (MANIFEST_SIG_TYPE_"
            "RSA_3072) -> %d (unsupported), signed region re-hashed, signature now stale but "
            "never reached",
            before,
            got,
        )

    def check_efuse(self, image) -> None:
        # Both are evaluated before the signature path is entered, so either being non-zero would end the
        # run with a different verdict and make this testcase vacuous.
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
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

        # CHK-SIGTYPE-PREEMPTS-KEYSEL: this is the discriminating check of the
        # testcase. PUBK_SEL= is printed, one statement
        # after the type check, so the primary must NOT have echoed a
        # selector at all -- the only occurrence in the run belongs to the booting
        # backup, and it must follow the backup read. A count of 2 would mean the
        # type check did not preempt key selection, which is precisely what
        # separates this testcase from its signature-VALUE sibling.
        n_sel = sum(1 for line in console if "PUBK_SEL=" in line)
        assert n_sel == 1, (
            f"PUBK_SEL= appeared {n_sel} times, expected exactly 1 (the backup's). "
            f"More than one means the primary reached the selector echo at "
            f", so the signature-type check at :162-165 did "
            f"not preempt key selection. Console: {console}"
        )
        assert 0 <= i_bsrc < i_bsel, (
            f"{_BACKUP_SEL_ECHO}@{i_bsel} did not follow the backup read@{i_bsrc}: "
            f"the single selector echo is not the booting slot's. Console: {console}"
        )
        # And the type verdict is the PRIMARY's: it precedes the backup read, and
        # occurs exactly once.
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
            _BAD_SIG_TYPE_ECHO,
            i_type,
            i_bsrc,
            _BACKUP_SEL_ECHO,
            i_bsel,
        )
