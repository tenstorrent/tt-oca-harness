# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Both manifests fail the public-key hash bind: terminal, no boot.

The terminal partner of ``sep_firmware_primary_invalid_key_hash_test``: the same
defect is in both slots, so the ROM stops with ``MANIFEST_ERR_KEY_HASH_MISMATCH``.
The primary carries the same defect as the backup, not BAD_MAGIC, so
``corrupt_primary`` and ``primary_expected_error`` are overridden.

Both slots print ``PUBK_UNAUTHORIZED``, so :meth:`check_defect_attribution`
requires exactly two, one on each side of the backup read.

The hash bind precedes RSA, so ``RSA_EXEC`` is forbidden and no
``+esrc_noise_force`` is needed.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_KEY_HASH_MISMATCH,
    MANIFEST_ERR_KEY_REVOKED,
    sep_backup_manifest_fail_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

_HASH_MISMATCH = "PUBK_UNAUTHORIZED"


@pyuvm.test()
class sep_firmware_backup_invalid_key_hash_test(sep_backup_manifest_fail_base):
    """Primary and backup moduli both fail their digest bind -> terminal."""

    backup_defect_marker = _HASH_MISMATCH
    expected_error = MANIFEST_ERR_KEY_HASH_MISMATCH
    primary_expected_error = MANIFEST_ERR_KEY_HASH_MISMATCH
    efuse_preload = _EFUSE_PRELOAD
    # Every verdict that would mean the rejection was something other than the
    # digest bind, plus proof neither unbound modulus reached the verifier.
    extra_forbidden = (
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "PUBK_SLOT_RESERVED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_OTP_EMPTY",
        "PUBK_SLOT_UNPROVISIONED",
        f"MANIFEST_ERR=0x{MANIFEST_ERR_KEY_REVOKED:08x}",
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        # Different byte from the backup's, so the two mutations cannot be one
        # write landing twice, and each slot's digest is independently wrong.
        mm.corrupt_public_key(buf, "primary", offset=0)

    def corrupt_backup(self, buf: bytearray) -> None:
        mm.corrupt_public_key(buf, "backup", offset=383)

    def check_efuse(self, image) -> None:
        # Revocation and anti-rollback run after the key bind. With both fuses
        # clear, a slot that passes the bind by mistake goes on to RSA_EXEC, which
        # extra_forbidden catches.
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: revocation runs "
            f"after the hash bind, so a set bit would refuse a slot that wrongly "
            f"passed the bind with KEY_REVOKED instead of letting it reach RSA_EXEC"
        )

    def check_defect_attribution(self, console, i_backup: int) -> None:
        hits = [i for i, line in enumerate(console) if _HASH_MISMATCH in line]
        assert len(hits) == 2, (
            f"{_HASH_MISMATCH} appeared {len(hits)} time(s) at {hits}, expected "
            f"exactly 2 -- one per slot. Console: {console}"
        )
        before = [i for i in hits if i < i_backup]
        after = [i for i in hits if i > i_backup]
        assert len(before) == 1 and len(after) == 1, (
            f"{_HASH_MISMATCH} occurrences {hits} do not straddle the backup read "
            f"at line {i_backup}: one must be the primary's verdict and one the "
            f"backup's. Console: {console}"
        )
        self.logger.info(
            "CHK-BACKUP-DEFECT: %s at line %d (primary) and line %d (backup, "
            "after the backup read at %d)",
            _HASH_MISMATCH,
            before[0],
            after[0],
            i_backup,
        )
