# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lifecycle outranks a manifest asking for non-secure boot: the part refuses (PyUVM).

FEATURE UNDER TEST. Secure boot is decided by a precedence, not by the manifest
alone (``secure_boot_decide``, ``validators/oca/lib/secure_boot.c``). Three inputs
are consulted in order, and the first to settle the question wins: the manifest's
``secure_boot_control`` enforced bit, then a device asserting ``SBOOT_DIS``, then
the device's own ``is_secure_boot_active()`` -- the lifecycle. The stimulus is
lifecycle PROD, ``SBOOT_DIS = 0``, and a manifest whose ``secure_boot`` is
CLEARED, so input (1) declines to enforce and input (3) enforces anyway. The run
establishes that the lifecycle wins.

THE OUTCOME IS A REFUSAL, AND THAT IS THE POINT. Clearing the enforced bit
obliges the whole crypto set to be zero: with secure boot off the parser requires
the slot to carry no signature, public key, key-select or type/encoding bytes,
and returns ``OCA_FAIL_SECURE_BOOT_INVARIANT`` otherwise
(``parser.c:180-208``). So ``mm.clear_secure_boot`` necessarily produces a
legally UNSIGNED manifest -- which is what a manifest requesting non-secure boot
IS in this format.

Both class bits live in the same byte as the enforced bit: the shipped slots
carry ``secure_boot_control = 0x03`` (enforced + ``secure_boot_classic``) and the
mutation leaves ``0x00``. The lifecycle then puts secure boot in force with
nothing naming a signature family to verify with, and ``secure_boot.c:226``
refuses on exactly that -- ``MANIFEST_ERR=0x00030024``
(``OCA_FAIL_SIGNATURE_CLASS_CONTROL``) on both slots, then
``MANIFEST_ALL_FAILED``. Read plainly: this part requires secure boot, this image
is unsigned, so it does not boot.

WHY NOT A VERIFIED BOOT. A manifest that disclaims secure boot while carrying a
verifiable signature is not expressible. The enforced bit sits INSIDE the TBS (at
offset 182, against a signed region ending at 3172), and the invariant above
forbids the signing fields whenever it is clear -- including when a class bit is
still set, because the invariant keys on the enforced bit alone. The format
closed that hole structurally rather than leaving the ROM to catch it at runtime,
so requiring ``RSA_VERIFY_OK`` here would be requiring a state the format
prevents.

The refusal still proves the precedence, because it is lifecycle-dependent: the
same image boots non-secure in TEST_DEV, where input (1) is honoured. It is
refused here. ``SBOOT_OFF`` is the sharpest forbid and the base already applies
it -- a PROD part must never announce secure boot off, whatever the manifest
asked for.

Distinction from ``sep_firmware_device_cntl_non_secure_boot_flow_test``: there the
DEVICE asks for non-secure boot (``SBOOT_DIS``) and the manifest asks to be
verified, so input (1) wins and the boot is verified. Here the two swap sides.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_SIG_CLASS_CONTROL,
    sep_backup_manifest_fail_base,
)
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE

_LC_PROD = "LC=PROD"
_ALL_FAILED = "MANIFEST_ALL_FAILED"
# Would mean secure boot was off for a different reason than the manifest flag.
_SBOOT_DIS_SET = "FUSE: SBOOT_DIS: 1"

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)


@pyuvm.test()
class sep_firmware_cntl_secure_boot_flow_test(sep_backup_manifest_fail_base):
    """PROD + manifest secure_boot=0 -> a legally unsigned manifest -> both slots refused."""

    flash_image = SECURE_FLASH_IMAGE
    efuse_preload = _EFUSE_PRELOAD
    # A class-control refusal prints no token of its own -- it lands before key
    # selection -- so the error code IS the defect marker, the same way
    # sep_firmware_primary_invalid_security_version_test uses its dedicated code.
    backup_defect_marker = f"MANIFEST_ERR=0x{MANIFEST_ERR_SIG_CLASS_CONTROL:08x}"
    expected_error = MANIFEST_ERR_SIG_CLASS_CONTROL
    # NOT the base's BAD_MAGIC default: the primary carries the same cleared flag
    # and is refused for the same reason, rather than being a failover trigger.
    primary_expected_error = MANIFEST_ERR_SIG_CLASS_CONTROL
    # PUBK_SEL= is the load-bearing one. The refusal is inside
    # oca_validate_manifest() ahead of key authorization, so neither slot may echo
    # a selector -- its absence is what places the rejection before key selection
    # rather than merely somewhere in the crypto chain. MANIFEST_OK would mean a
    # slot was accepted; the RSA pair would mean the verifier ran on an image that
    # carries no signature at all.
    extra_forbidden = (
        "PUBK_SEL=",
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "MANIFEST_OK",
        _SBOOT_DIS_SET,
    )

    # --- stimulus ------------------------------------------------------------
    def _clear_one(self, buf: bytearray, slot: str) -> None:
        before = mm.secure_boot_control(buf, slot)
        assert before & mm.SECURE_BOOT_ENFORCED_BIT, (
            f"{slot} manifest already has secure_boot=0 (secure_boot_control="
            f"0x{before:02x}); clearing it would be a no-op and the override would "
            f"be untested"
        )
        mm.clear_secure_boot(buf, slot)
        after = mm.secure_boot_control(buf, slot)
        # Zero, not merely bit 0 cleared: the class bits share this byte, and it is
        # their absence under a lifecycle that enforces that produces the verdict.
        assert after == 0, (
            f"{slot} secure_boot_control is 0x{after:02x} after clear_secure_boot, "
            f"expected 0x00. A surviving class bit would name a signature family, "
            f"and the slot would be refused somewhere other than the class check"
        )
        # Proves the mutation left the signed region consistent: verify_layout
        # recomputes sha256(TBS) and compares it to the stored manifest_hash.
        mm.verify_layout(buf, slot)
        self.logger.info(
            "CHK-MUTATION: %s secure_boot_control 0x%02x -> 0x%02x, %s",
            slot,
            before,
            after,
            mm.describe(buf, slot),
        )

    def corrupt_primary(self, buf: bytearray) -> None:
        # Both slots: the ROM may serve this boot from either, and leaving the
        # backup's flag set would let a failover quietly satisfy the test for the
        # wrong reason.
        self._clear_one(buf, "primary")

    def corrupt_backup(self, buf: bytearray) -> None:
        self._clear_one(buf, "backup")

    # --- checks --------------------------------------------------------------
    def check_defect_attribution(self, console, i_backup: int) -> None:
        """Both slots carry the same defect, so the marker must appear exactly twice.

        The base default requires the FIRST occurrence to follow the backup read,
        which holds only when the primary failed for some other reason. Here the
        primary's own verdict is legitimately the first occurrence, so the pair has
        to straddle the backup read instead -- otherwise a run that refused the
        primary twice and never read the backup would look identical.
        """
        hits = [i for i, line in enumerate(console) if self.backup_defect_marker in line]
        assert len(hits) == 2, (
            f"{self.backup_defect_marker} appeared {len(hits)} time(s) at {hits}, "
            f"expected exactly 2 -- one per slot. Console: {console}"
        )
        before = [i for i in hits if i < i_backup]
        after = [i for i in hits if i > i_backup]
        assert len(before) == 1 and len(after) == 1, (
            f"{self.backup_defect_marker} occurrences {hits} do not straddle the "
            f"backup read at line {i_backup}: one must be the primary's verdict and "
            f"one the backup's. Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-SLOTS-REFUSED: %s at lines %s, straddling the backup read at %d",
            self.backup_defect_marker,
            hits,
            i_backup,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        # The lifecycle the override depends on, as the ROM itself read it. The OTP
        # assertion in check_efuse covers the image; this covers what the ROM made
        # of it.
        assert any(_LC_PROD in line for line in console), (
            f"ROM never printed {_LC_PROD}: the lifecycle that forces secure boot "
            f"here is not the one the ROM resolved. Console: {console}"
        )
        # Both slots gone, so the retry loop exhausted rather than the run ending
        # on one slot's verdict.
        assert any(_ALL_FAILED in line for line in console), (
            f"ROM never printed {_ALL_FAILED}: the retry loop did not exhaust both "
            f"slots. Console: {console}"
        )
        self.logger.info(
            "CHK-LIFECYCLE-WINS: %s, both slots refused with %s, %s -- the cleared "
            "manifest flag did not disable secure boot",
            _LC_PROD,
            self.backup_defect_marker,
            _ALL_FAILED,
        )

    def check_efuse(self, image) -> None:
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        bl1_ver = image.field_int("BL1_VERSION")
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD). In TEST_DEV a cleared "
            f"manifest flag legitimately disables secure boot, so the override "
            f"under test only exists in PROD/PROD_END"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the chicken bit outranks the lifecycle, so "
            f"secure boot would be off for a different reason than the manifest flag"
        )
        assert bl1_ver == 0, f"BL1_VERSION is 0x{bl1_ver:x}, expected 0 (rollback would mask this)"
        assert revoke == 0, f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0"
        self.logger.info(
            "CHK-SBOOT-STIMULUS: OTP LC raw=0x%x (PROD), SBOOT_DIS=%d, "
            "BL1_VERSION=0x%x, PUBK_REVOKE=0x%x",
            lc,
            sboot_dis,
            bl1_ver,
            revoke,
        )
