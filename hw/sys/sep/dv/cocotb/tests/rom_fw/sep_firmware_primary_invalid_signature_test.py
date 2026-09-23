# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest with a corrupted RSA signature; the backup boots.

One bit of the primary signature is flipped, so the primary reaches RSA and fails there.
Needs ``+sep_crypto_edn_force``: OTBN waits for EDN entropy in both RSA-3072 verifies.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_fail_backup_boot_base import (
    MANIFEST_ERR_SIG_FAILED,
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

# Both slots ship with ROM key slot 0, so they echo the same selector.
_SEL_ECHO = "PUBK_SEL=0x00000000"


@pyuvm.test()
class sep_firmware_primary_invalid_signature_test(sep_primary_fail_backup_boot_base):
    """Primary signature fails RSA -> failover -> backup verifies and boots."""

    primary_defect_marker = "RSA_VERIFY_FAIL"
    primary_expected_error = MANIFEST_ERR_SIG_FAILED
    # The defect is the signature value, so the primary must drive the verifier.
    primary_expected_rsa_starts = 1
    efuse_preload = _EFUSE_PRELOAD
    extra_required = (_SEL_ECHO,)
    # BAD_SIG_TYPE= shares this error code, so forbid it to separate the two arms.
    extra_forbidden = ("BAD_SIG_TYPE=", "BAD_KEY_IDX", "BAD_KEY_SEL",
                       "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH",
                       "KEY_REVOKED", "VERSION_ROLLBACK")

    def corrupt_primary(self, buf: bytearray) -> None:
        # No manifest_identifier corruption: the primary must reach rsa_3072_verify.
        base = mm.slot_base("primary") + mm.OFF_SIGNATURE
        before = bytes(buf[base:base + 8])
        mm.flip_signature_byte(buf, "primary", byte_index=0, xor_mask=0x01)
        after = bytes(buf[base:base + 8])
        assert before != after, "signature flip was a no-op"
        # A stale TBS hash would reject the primary before RSA runs.
        mm.verify_layout(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-SIG: primary signature[0:8] %s -> %s (1 bit), TBS hash "
            "intact and modulus still binds the ROM slot-0 digest",
            before.hex(), after.hex(),
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
            f"rejection precedes the signature check on both slots"
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        def indices_of(marker: str) -> list[int]:
            return [i for i, line in enumerate(console) if marker in line]

        i_bsrc = next(iter(indices_of(
            f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}")), -1)
        sels = indices_of(_SEL_ECHO)

        assert len(sels) == 2, (
            f"{_SEL_ECHO} appeared {len(sels)} times at {sels}, expected exactly 2 "
            f"(one per manifest slot). One occurrence would mean a slot was refused "
            f"before the selector echo, i.e. not by its signature value. "
            f"Console: {console}"
        )
        assert 0 <= i_bsrc and sels[0] < i_bsrc < sels[1], (
            f"{_SEL_ECHO} occurrences {sels} do not straddle the backup read"
            f"@{i_bsrc}: the two echoes are not one per slot. Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-REACHED-KEYSEL: %s at lines %s, one before and one after the "
            "backup read@%d -- both manifests passed the signature-type arm and "
            "reached key selection", _SEL_ECHO, sels, i_bsrc,
        )
