# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest declares unsupported signature type 0; the ROM halts.

The primary fails on magic. ``oca_check_crypto_field_sizes()`` refuses the backup with
``MANIFEST_ERR_SIG_TYPE_INVALID`` before key selection, so no ``PUBK_*`` or RSA token appears.
``signature_type`` is in the signed region, so the helper re-hashes; the stale signature is unread.
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

# Type 0 declares no signature, so the field-size check refuses it before key
# selection.
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
    # PUBK_SEL= is the next thing the signature path prints, so its absence
    # proves the type check ran first.
    # RSA_PKCS1_FAIL is forbidden: only the signature-value sibling reaches the
    # verifier. The rest are later arms, none of which may be reached.
    extra_forbidden = (
        "PUBK_SEL=",
        # The structural check runs before plat_is_key_authorized(), including
        # its algorithm arm.
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
        # A stale signed-region hash would refuse the backup before the type check runs.
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-SIGTYPE: backup signature_type %d (MANIFEST_SIG_TYPE_"
            "RSA_3072) -> %d (unsupported), signed region re-hashed, signature now stale "
            "but never reached",
            before,
            got,
        )

    def check_efuse(self, image) -> None:
        # Both are evaluated before the signature path, so either one non-zero
        # would end the run with a different verdict and make this test vacuous.
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
