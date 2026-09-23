# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario: the primary slot is rejected and a valid backup completes the boot.

Subclasses plant the primary defect and declare its error code, its console token,
and whether the primary reaches RSA_VERIFY_START and SIG_VALID.
"""

from __future__ import annotations

import os
from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
MANIFEST_ERR_SIG_FAILED = 0x0003_000C
MANIFEST_ERR_VERSION_ROLLBACK = 0x0003_0014

# Identify slots by MANIFEST_SRC=: under rotate_update the label follows the retry counter.
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_RSA_START = "RSA_VERIFY_START"
_SIG_VALID = "SIG_VALID"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"
_MANIFEST_OK = "MANIFEST_OK"
_LC_PROD = "LC=PROD"

# Forbidden: secure boot skipped, or a terminal failure instead of recovery.
_SBOOT_OFF = "SBOOT_OFF"
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_SBOOT_DIS_FUSE = "FUSE: SBOOT_DIS: 1"


class sep_primary_fail_backup_boot_base(sep_rom_ot_dma_boot_test):

    flash_image = SECURE_FLASH_IMAGE

    # --- subclass contract -------------------------------------------------
    # The primary defect's console token, or "" when the defect prints none.
    primary_defect_marker: str = ""
    primary_expected_error: int = 0
    # Primary RSA_VERIFY_START count: 0 if refused before the verifier, 1 for a signature defect.
    primary_expected_rsa_starts: int = 0
    # Primary SIG_VALID count: 0 if refused at or before validate_signature, 1 if refused after it.
    primary_expected_sig_valids: int = 0
    efuse_preload: Path | None = None
    extra_forbidden: tuple[str, ...] = ()
    extra_required: tuple[str, ...] = ()
    # False for an encrypted backup: its TOC is ciphertext and cannot be parsed offline.
    backup_sealed_check_toc: bool = True

    def corrupt_primary(self, buf: bytearray) -> None:
        raise NotImplementedError

    def prepare_backup(self, buf: bytearray) -> None:
        ...

    def check_efuse(self, image) -> None:
        ...

    # --- wiring ------------------------------------------------------------
    @classmethod
    def _markers(cls) -> tuple[tuple[str, ...], tuple[str, ...]]:
        slot_err = f"MANIFEST_ERR=0x{cls.primary_expected_error:08x}"
        crypto_fail = f"CRYPTO_FAIL=0x{cls.primary_expected_error:08x}"
        required = (_LC_PROD, _PRIMARY_SRC, slot_err, _BACKUP_SRC,
                    _RSA_START, _SIG_VALID, _CRYPTO_OK, _MANIFEST_OK)
        if cls.primary_defect_marker:
            required += (cls.primary_defect_marker, crypto_fail)
        return required, (_SBOOT_OFF, _ALL_FAILED, _SBOOT_DIS_FUSE)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        req, forb = self._markers()
        # Per instance, so each subclass builds the lists from its own error code.
        self.required_markers = (sep_rom_ot_dma_boot_test.required_markers
                                 + req + tuple(self.extra_required))
        self.forbidden_markers = (sep_rom_ot_dma_boot_test.forbidden_markers
                                  + forb + tuple(self.extra_forbidden))

    def build_efuse_image(self):
        assert self.efuse_preload and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced or the verdict under test is never reached"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        self.check_efuse(image)
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, "
            "BL1_VERSION=0x%x, PUBK_REVOKE=0x%x", lc, sboot_dis,
            image.field_int("BL1_VERSION"), image.field_int("CHIPLET_PUBK_REVOKE"),
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        self.corrupt_primary(buf)
        self.prepare_backup(buf)
        pm.verify_sealed(buf, "backup", check_toc=self.backup_sealed_check_toc)
        mm.verify_public_key(buf, "backup")
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        self.logger.info("CHK-STIMULUS-BACKUP:  %s", mm.describe(buf, "backup"))
        self.logger.info(
            "CHK-STIMULUS-BACKUP-SEALED: backup passes payload_hash, %s "
            "manifest_hash over the TBS, and RSA verification of its shipped "
            "signature against the dev0 modulus; and the modulus it carries hashes "
            "to the ROM's compiled-in slot-0 digest -- it is a genuinely bootable "
            "slot",
            "every TOC image digest," if self.backup_sealed_check_toc
            else "(TOC arm skipped: the payload is ciphertext offline,)",
        )
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info("CHK-SPI-TXNS:\n%s",
                         ev.summarize(flash.get_transactions(), self._image_len))

    # --- checks ------------------------------------------------------------
    def check_transport(self, console: list[str], flash) -> None:
        def index_of(marker: str, after: int = -1) -> int:
            for i, line in enumerate(console):
                if i > after and marker in line:
                    return i
            return -1

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = index_of(_PRIMARY_SRC)
        i_perr = index_of(slot_err)
        i_bsrc = index_of(_BACKUP_SRC)
        i_rsa = index_of(_RSA_START)
        i_sig = index_of(_SIG_VALID)
        i_ok = index_of(_MANIFEST_OK)

        # The primary must be read and rejected before the backup is read.
        assert i_psrc >= 0 < i_perr, (
            f"primary read ({_PRIMARY_SRC}@{i_psrc}) or its rejection "
            f"({slot_err}@{i_perr}) is missing. Console: {console}"
        )
        assert i_psrc < i_perr < i_bsrc, (
            f"the primary rejection is not attributable to the primary slot: "
            f"{_PRIMARY_SRC}@{i_psrc} -> {slot_err}@{i_perr} -> "
            f"{_BACKUP_SRC}@{i_bsrc}. Console: {console}"
        )

        # The primary's defect token must sit inside the primary attempt, exactly once.
        if self.primary_defect_marker:
            i_defect = index_of(self.primary_defect_marker)
            assert i_psrc < i_defect < i_perr, (
                f"{self.primary_defect_marker}@{i_defect} does not sit between the "
                f"primary read@{i_psrc} and the primary error@{i_perr}: it is not "
                f"the primary's verdict. Console: {console}"
            )
            n = sum(1 for line in console
                    if self.primary_defect_marker in line)
            assert n == 1, (
                f"{self.primary_defect_marker} appeared {n} times, expected "
                f"exactly 1 (the primary's); the backup must not carry this "
                f"defect. Console: {console}"
            )

        # Pin both the count and the position of the primary's RSA_VERIFY_START.
        n_rsa = sum(1 for line in console if _RSA_START in line)
        expected_rsa = 1 + self.primary_expected_rsa_starts
        assert n_rsa == expected_rsa, (
            f"{_RSA_START} appeared {n_rsa} times, expected exactly {expected_rsa} "
            f"(the backup's, plus {self.primary_expected_rsa_starts} declared for "
            f"the primary). Console: {console}"
        )
        if self.primary_expected_rsa_starts == 0:
            # Refused before rsa_3072_verify, so the first RSA_VERIFY_START must be the backup's.
            assert i_rsa > i_bsrc, (
                f"{_RSA_START}@{i_rsa} appeared before the backup slot was read"
                f"@{i_bsrc}: the primary reached the RSA verifier, but this member "
                f"declares primary_expected_rsa_starts=0. Console: {console}"
            )
        else:
            # The defect is the signature value, so the primary must drive the verifier.
            assert i_psrc < i_rsa < i_perr, (
                f"{_RSA_START}@{i_rsa} does not sit between the primary read"
                f"@{i_psrc} and the primary error@{i_perr}: the primary did not "
                f"drive the verifier, so its rejection is not a signature verdict. "
                f"Console: {console}"
            )

        # SIG_VALID prints only after rsa_3072_verify passes; extra ones are the primary's.
        n_sig = sum(1 for line in console if _SIG_VALID in line)
        expected_sig = 1 + self.primary_expected_sig_valids
        assert n_sig == expected_sig, (
            f"{_SIG_VALID} appeared {n_sig} times, expected exactly {expected_sig} "
            f"(the backup's, plus {self.primary_expected_sig_valids} declared for "
            f"the primary). Console: {console}"
        )
        if self.primary_expected_sig_valids:
            assert i_psrc < i_sig < i_perr, (
                f"{_SIG_VALID}@{i_sig} does not sit between the primary read"
                f"@{i_psrc} and the primary error@{i_perr}: the primary's signature "
                f"was not verified, so its rejection is not downstream of "
                f"validate_signature as this member declares. Console: {console}"
            )

        # The accepted manifest must be the backup's: the first SIG_VALID after the backup read.
        i_sig_backup = index_of(_SIG_VALID, after=i_bsrc)
        assert i_bsrc < i_sig_backup < i_ok, (
            f"the accepted manifest is not the backup's: {_BACKUP_SRC}@{i_bsrc} -> "
            f"{_SIG_VALID}@{i_sig_backup} -> {_MANIFEST_OK}@{i_ok}. Console: {console}"
        )
        # Log the backup's RSA_VERIFY_START; the first is the primary's if it reaches the verifier.
        i_rsa_backup = index_of(_RSA_START, after=i_bsrc)
        self.logger.info(
            "CHK-PRIMARY-FAILOVER: primary@%d -> %s@%d -> backup@%d -> "
            "RSA_VERIFY_START@%d -> SIG_VALID@%d -> MANIFEST_OK@%d",
            i_psrc, slot_err, i_perr, i_bsrc, i_rsa_backup, i_sig_backup, i_ok,
        )

        # --- device evidence -------------------------------------------------
        # The console shows the address the ROM intended; the device record shows what was served.
        rds = ev.reads(flash.get_transactions())
        p_hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert p_hit is not None, (
            f"no SPI read covered 0x{mm.PRIMARY_MANIFEST_OFFSET:x}: the primary "
            f"was never fetched, so the run did not fail over FROM it"
        )
        assert b_hit is not None, (
            f"no SPI read covered 0x{mm.BACKUP_MANIFEST_OFFSET:x}: the boot did "
            f"not come from the backup address"
        )
        p_idx, _p_txn = p_hit
        b_idx, _b_txn = b_hit
        assert p_idx < b_idx, (
            f"device served the backup address (read[{b_idx}]) before the primary "
            f"(read[{p_idx}]): the transaction order is not a failover"
        )
        self.logger.info(
            "CHK-FAILOVER-ADDR: device served read[%d] 0x%06x first and read[%d] "
            "0x%06x second", p_idx, mm.PRIMARY_MANIFEST_OFFSET,
            b_idx, mm.BACKUP_MANIFEST_OFFSET,
        )
