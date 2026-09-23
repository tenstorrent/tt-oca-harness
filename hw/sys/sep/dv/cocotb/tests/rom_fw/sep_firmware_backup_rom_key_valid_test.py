# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest names a VALID ROM key index and boots -> success.

The ``PUBK_SEL=`` and ``PUBK_REVOKE=`` echoes must precede ``RSA_VERIFY_START`` on the backup.
Needs ``+sep_crypto_edn_force``: OTBN waits for EDN entropy during the RSA-3072 modexp.
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
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

# The shipped image is signed for this slot, so the backup needs no re-signing.
_VALID_SLOT = 0
_PUBK_SEL_ECHO = f"PUBK_SEL=0x{_VALID_SLOT:08x}"
_REVOKE_ECHO = "PUBK_REVOKE=0x00000000"


@pyuvm.test()
class sep_firmware_backup_rom_key_valid_test(sep_primary_fail_backup_boot_base):
    """Primary BAD_MAGIC -> failover -> backup names valid ROM slot 0 -> boots."""

    # BAD_MAGIC fails before any crypto, so the primary prints no defect token of its own.
    primary_defect_marker = ""
    primary_expected_error = MANIFEST_ERR_BAD_MAGIC
    efuse_preload = _EFUSE_PRELOAD
    extra_required = (_PUBK_SEL_ECHO, _REVOKE_ECHO)
    extra_forbidden = ("BAD_SIG_TYPE=", "BAD_KEY_IDX", "BAD_KEY_SEL",
                       "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH",
                       "KEY_REVOKED", "VERSION_ROLLBACK", "RSA_VERIFY_FAIL")

    def corrupt_primary(self, buf: bytearray) -> None:
        # validate_manifest_header rejects the magic before hashing, so key selection is untouched.
        mm.set_identifier(buf, "primary")

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
            "original dev0 signature", got, _VALID_SLOT,
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
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364 then :369) and would "
            f"reject the backup before the key path is reached"
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
        i_rsa = index_of("RSA_VERIFY_START")

        # Bound from below by the backup read, so a primary-side echo cannot satisfy the order.
        assert i_bsrc < i_sel < i_rsa, (
            f"key selection did not run on the backup before the signature step: "
            f"backup@{i_bsrc} -> {_PUBK_SEL_ECHO}@{i_sel} -> RSA_VERIFY_START"
            f"@{i_rsa}. Console: {console}"
        )
        assert i_sel < i_revoke < i_rsa, (
            f"the revocation bitmap was not consulted between the selector and the "
            f"verifier: {_PUBK_SEL_ECHO}@{i_sel} -> {_REVOKE_ECHO}@{i_revoke} -> "
            f"RSA_VERIFY_START@{i_rsa}. Console: {console}"
        )
        for marker in (_PUBK_SEL_ECHO, _REVOKE_ECHO):
            n = sum(1 for line in console if marker in line)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the backup's). "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-KEYSEL-RAN: backup@%d -> %s@%d -> %s@%d -> RSA_VERIFY_START@%d; "
            "the ROM-key path executed and permitted slot %d",
            i_bsrc, _PUBK_SEL_ECHO, i_sel, _REVOKE_ECHO, i_revoke, i_rsa,
            _VALID_SLOT,
        )
