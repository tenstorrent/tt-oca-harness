# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest names two ROM key slots at once; the ROM halts.

The primary's magic is broken to force failover. The backup's ``public_key_select``
bitmap names slots 0 and 1, both provisioned, so the refusal can only be the
ambiguity: the platform prints ``PUBK_SEL_AMBIGUOUS`` and returns
``MANIFEST_ERR_KEY_UNAUTHORIZED``. A bad ROM key index is a different arm
(``PUBK_SLOT_RESERVED``) and is forbidden.

The selector is inside the signed region, so the helper re-hashes. No re-sign: the
selection is refused before the signature check, and ``RSA_EXEC`` is forbidden so
that ordering is checked.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_KEY_UNAUTHORIZED,
    sep_backup_manifest_fail_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# Two provisioned ROM key slots named at once. Both are individually valid, so
# the refusal can only be the ambiguity itself -- naming one valid and one
# invalid slot would leave the verdict attributable to either.
_AMBIGUOUS_SLOTS = (0, 1)


@pyuvm.test()
class sep_firmware_backup_invalid_public_key_selection_test(sep_backup_manifest_fail_base):
    """Primary BAD_MAGIC -> failover -> backup names two key slots -> terminal."""

    backup_defect_marker = "PUBK_SEL_AMBIGUOUS"
    expected_error = MANIFEST_ERR_KEY_UNAUTHORIZED
    efuse_preload = _EFUSE_PRELOAD
    # The selection must be rejected before any key is loaded or verified.
    extra_forbidden = (
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "PUBK_SLOT_RESERVED",
        "PUBK_OTP_EMPTY",
    )

    def corrupt_backup(self, buf: bytearray) -> None:
        mm.set_public_key_slots(buf, "backup", _AMBIGUOUS_SLOTS)
        # get_public_key_sel refuses to resolve a bitmap naming more than one
        # slot, which is the property this stimulus is planting.
        try:
            got = mm.get_public_key_sel(buf, "backup")
        except AssertionError:
            pass
        else:
            raise AssertionError(
                f"backup public_key_sel resolved to a single slot {got}; the "
                f"bitmap should name {_AMBIGUOUS_SLOTS}"
            )
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-PUBKSEL: backup public_key_sel names slots %s, both "
            "individually valid, re-hashed",
            _AMBIGUOUS_SLOTS,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
        )
        assert image.field_int("CHIPLET_PUBK_REVOKE") == 0, (
            "CHIPLET_PUBK_REVOKE must be 0; revocation is keyed off the selected "
            "slot and would produce a different verdict"
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        # PUBK_SEL= is refused BEFORE it can be echoed: the ambiguity is detected
        # inside the resolution loop, so no slot number is printed. The primary
        # fails on its magic and never reaches selection, so no PUBK_SEL= line may
        # appear in the run.
        sels = [line for line in console if "PUBK_SEL=" in line]
        assert not sels, (
            f"ROM echoed a resolved slot {sels}: an ambiguous bitmap must be "
            f"refused before resolution completes. Console: {console}"
        )
        self.logger.info(
            "CHK-PUBKSEL-UNRESOLVED: no PUBK_SEL= echo, so neither of %s was picked",
            _AMBIGUOUS_SLOTS,
        )
