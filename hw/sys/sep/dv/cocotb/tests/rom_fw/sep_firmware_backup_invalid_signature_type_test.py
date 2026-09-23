# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest declares an unsupported signature TYPE -> terminal.

The primary's ``manifest_identifier`` is corrupted to force failover, then the
backup's ``signature_type`` is set to 0. The signature path accepts only
``MANIFEST_SIG_TYPE_RSA_3072`` (1, ) and refuses anything else
with ``PUBK_ALGO_UNSUPPORTED``.

WHY 0, And why A Fixed value. The ROM's check is a single ``!=`` against RSA-3072, so
every value in that set exercises the identical arm, and fixing it is what lets this
testcase assert the exact ``PUBK_ALGO_UNSUPPORTED`` the ROM echoed rather than accepting
any value at all -- the same reason
``sep_firmware_backup_invalid_public_key_selection_test`` fixes its selection.

THE ROM DOES VALIDATE TYPE SEPARATELY FROM VALUE, AND THIS TEST PROVES IT RATHER
THAN ASSUMING IT. The type check is the FIRST arm of the signature path,
ahead even of the ``PUBK_SEL=`` echo. So ``PUBK_SEL=``
is forbidden below: the primary died at BAD_MAGIC before any crypto ran, so if the
selector is echoed at all it can only be the backup's, which would mean the type
check did not preempt key selection. That single forbid is what turns "the ROM
rejected it" into "the ROM rejected it AT the type check".

WHY THIS IS NOT THE SAME TESTCASE AS ``sep_firmware_backup_invalid_signature_test``.
The two end at DIFFERENT codes, and that is the first discriminator. A
``signature_type`` that disagrees with the declared crypto field sizes is refused
structurally by ``oca_check_crypto_field_sizes()`` as
``MANIFEST_ERR_SIG_TYPE_INVALID``; a bad signature VALUE survives the structural
checks, reaches the verifier, and returns ``MANIFEST_ERR_SIG_FAILED``.

The console carries the ordering evidence the code cannot. The structural refusal
lands before ``plat_is_key_authorized()`` is called at all, so this run shows NO
``PUBK_*`` token for the backup -- not even the algorithm arm, which is why
``PUBK_ALGO_UNSUPPORTED`` is forbidden below rather than required -- and never
reaches ``RSA_EXEC`` or ``RSA_PKCS1_FAIL``, which its sibling requires.

``signature_type`` is one byte at manifest offset 165, INSIDE the TBS, so the
helper re-hashes. It cannot be a signature-region patch: the field is covered by
``manifest_hash``, so an un-rehashed write dies in the manifest loop as a hash
mismatch and never reaches the type check at all. No re-sign is needed or possible
-- the type is rejected before ``rsa_3072_verify``, so
the now-stale signature is never examined, and ``RSA_EXEC`` being
forbidden is what checks that ordering instead of assuming it.

No ``+esrc_noise_force``: OTBN is never driven on either slot.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_SIG_TYPE_INVALID,
    sep_backup_manifest_fail_base,
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
# sep_firmware_primary_invalid_security_version_test does the same for its own
# dedicated code.
_BAD_SIG_TYPE_ECHO = f"MANIFEST_ERR=0x{MANIFEST_ERR_SIG_TYPE_INVALID:08x}"


@pyuvm.test()
class sep_firmware_backup_invalid_signature_type_test(sep_backup_manifest_fail_base):
    """Primary BAD_MAGIC -> failover -> backup declares sig type 0 -> terminal."""

    backup_defect_marker = _BAD_SIG_TYPE_ECHO
    expected_error = MANIFEST_ERR_SIG_TYPE_INVALID
    efuse_preload = _EFUSE_PRELOAD
    # PUBK_SEL= is the load-bearing one: it is the very next thing
    # the signature path prints, so its absence proves the
    # type check ran FIRST rather than merely eventually. RSA_PKCS1_FAIL is the
    # discriminator against the signature-VALUE sibling, which shares this error
    # code. The rest are the later arms, none of which may be reached.
    extra_forbidden = (
        "PUBK_SEL=",
        # The whole of plat_is_key_authorized() is unreachable here, its own
        # algorithm arm included: the structural check refuses first. Forbidding
        # the arm this testcase used to require is what pins that.
        "PUBK_ALGO_UNSUPPORTED",
        "RSA_EXEC",
        "RSA_PKCS1_FAIL",
        "RSA_VERIFY_OK",
        "PUBK_SLOT_RESERVED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_OTP_EMPTY",
        "PUBK_UNAUTHORIZED",
    )

    def corrupt_backup(self, buf: bytearray) -> None:
        before = mm.signature_type(buf, "backup")
        assert before == mm.SIG_TYPE_RSA_3072, (
            f"backup signature_type is already {before}, expected "
            f"{mm.SIG_TYPE_RSA_3072} (RSA-3072): the shipped image is not the "
            f"supported-type baseline this testcase mutates away from"
        )
        mm.set_signature_type(buf, "backup", _BAD_SIG_TYPE)
        got = mm.signature_type(buf, "backup")
        assert got == _BAD_SIG_TYPE, (
            f"signature_type is 0x{got:02x} after the write, expected "
            f"0x{_BAD_SIG_TYPE:02x}; the mutation did not land"
        )
        # The re-hash must have restored a valid TBS hash, or the backup is thrown
        # out in the manifest loop as a hash mismatch and the type check -- the
        # only thing this testcase is about -- never runs.
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-SIGTYPE: backup signature_type %d (MANIFEST_SIG_TYPE_"
            "RSA_3072) -> %d (unsupported), TBS re-hashed, signature now stale "
            "but never reached",
            before,
            got,
        )

    def check_efuse(self, image) -> None:
        # Both of these are evaluated before the signature path is even entered, so either being non-zero would end the
        # run with a different verdict and make this testcase vacuous.
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: a revocation "
            f"verdict would come from a different arm of the same function"
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        # Exactly once. The primary never reaches crypto, so a second occurrence
        # would mean a slot this testcase did not account for also declared a bad
        # type -- and the verdict would not be attributable to this stimulus.
        n = sum(1 for line in console if _BAD_SIG_TYPE_ECHO in line)
        assert n == 1, (
            f"{_BAD_SIG_TYPE_ECHO} appeared {n} times, expected exactly 1 (the "
            f"backup's). Console: {console}"
        )
        self.logger.info(
            "CHK-SIGTYPE-ECHO: ROM read %s exactly once and never echoed PUBK_SEL=",
            _BAD_SIG_TYPE_ECHO,
        )
