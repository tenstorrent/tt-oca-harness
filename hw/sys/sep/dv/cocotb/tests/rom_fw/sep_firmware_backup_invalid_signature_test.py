# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest signature has one bit flipped; the ROM halts.

The backup is valid in every other field, so only RSA authentication can refuse it.
The signature lies outside the hashed signed region, so the flip needs no re-hash or re-sign.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_SIG_FAILED,
    sep_backup_manifest_fail_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)


@pyuvm.test()
class sep_firmware_backup_invalid_signature_test(sep_backup_manifest_fail_base):
    """Primary BAD_MAGIC -> failover -> backup signature fails RSA -> terminal."""

    # Only the verifier prints this, so an earlier failure cannot satisfy the test.
    backup_defect_marker = "RSA_PKCS1_FAIL"
    expected_error = MANIFEST_ERR_SIG_FAILED
    efuse_preload = _EFUSE_PRELOAD
    # The shared terminal code cannot show which signature arm refused each slot.
    extra_forbidden = ("RSA_VERIFY_OK", "MANIFEST_OK", "PUBK_ALGO_UNSUPPORTED")

    def corrupt_backup(self, buf: bytearray) -> None:
        before = bytes(buf[mm.BACKUP_MANIFEST_OFFSET + mm.OFF_SIGNATURE :][:8])
        mm.flip_signature_byte(buf, "backup", byte_index=0, xor_mask=0x01)
        after = bytes(buf[mm.BACKUP_MANIFEST_OFFSET + mm.OFF_SIGNATURE :][:8])
        assert before != after, "signature flip was a no-op"
        # A broken signed-region hash would refuse the backup before RSA runs.
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-SIG: backup signature[0:8] %s -> %s (1 bit), signed region hash intact",
            before.hex(),
            after.hex(),
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: a rollback rejection "
            f"precedes the signature check and would mask this defect"
        )
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: a revocation "
            f"rejection precedes the signature check"
        )
