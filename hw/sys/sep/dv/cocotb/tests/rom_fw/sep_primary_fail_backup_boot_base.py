# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario: the PRIMARY slot is rejected and the BACKUP boots.

Every error ``try_manifest_slot()`` returns fails over to the next slot, so each
member expects a completed boot; each ``MANIFEST_SRC=`` attempt is checked alone.
"""

from __future__ import annotations

import os
from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

MANIFEST_ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")
MANIFEST_ERR_SIG_FAILED = mm.boot_err("OCA_FAIL_SIGNATURE")
MANIFEST_ERR_VERSION_ROLLBACK = mm.boot_err("OCA_FAIL_SECURITY_VERSION")
# Every plat_is_key_authorized() refusal uses this code; only the marker names the arm.
MANIFEST_ERR_KEY_UNAUTHORIZED = mm.boot_err("OCA_FAIL_ROOT_KEY_UNAUTHORIZED")
# Refused before key selection runs, so this arm prints no PUBK_* marker.
MANIFEST_ERR_SIG_TYPE_INVALID = mm.boot_err("OCA_FAIL_CRYPTO_FIELD_SIZE")

_KEY_OK = "PUBK_AUTHORIZED"
_RSA_EXEC = "RSA_EXEC"
_RSA_OK = "RSA_VERIFY_OK"
_MANIFEST_OK = "MANIFEST_OK"
_DECRYPT_OK = "DECRYPT_OK"
_PAYLOAD_OK = "PAYLOAD_OK"
_LC_PROD = "LC=PROD"

_SBOOT_OFF = "SBOOT_OFF"
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_SBOOT_DIS_FUSE = "FUSE: SBOOT_DIS: 1"

_PRIMARY_STAGES = ("manifest", "payload", "placement")


class sep_primary_fail_backup_boot_base(sep_rom_ot_dma_boot_test):
    flash_image = SECURE_FLASH_IMAGE

    # Printed exactly once, as the primary's error line or the line just before it.
    primary_defect_marker: str = ""
    primary_expected_error: int = 0
    # 0: the primary is refused before RSA_EXEC. 1: the primary drives the verifier.
    primary_expected_rsa_starts: int = 0
    # 1: the primary's signature verifies and the refusal is downstream of it.
    primary_expected_rsa_oks: int = 0
    primary_expected_stage: str = "manifest"
    # Markers the primary prints after its RSA/MANIFEST_OK prefix, in ROM order.
    primary_ordered: tuple[str, ...] = ()
    primary_absent: tuple[str, ...] = ()
    efuse_preload: Path | None = None
    extra_forbidden: tuple[str, ...] = ()
    extra_required: tuple[str, ...] = ()

    def corrupt_primary(self, buf: bytearray) -> None:
        raise NotImplementedError

    def prepare_backup(self, buf: bytearray) -> None:
        pass

    def check_efuse(self, image) -> None:
        pass

    @staticmethod
    def _check_contract(obj) -> None:
        # obj is the class at import time and the instance at run time.
        concrete = not isinstance(obj, type)
        name = type(obj).__name__ if concrete else obj.__name__
        oc.assert_known(
            tuple(obj.extra_required)
            + tuple(obj.extra_forbidden)
            + tuple(obj.primary_ordered)
            + tuple(obj.primary_absent)
            + ((obj.primary_defect_marker,) if obj.primary_defect_marker else ()),
            name,
        )
        assert not hasattr(obj, "primary_expected_sig_valids"), (
            f"{name}: primary_expected_sig_valids is not read; declare "
            f"primary_expected_rsa_starts / primary_expected_rsa_oks instead"
        )
        starts, oks, stage = (
            obj.primary_expected_rsa_starts,
            obj.primary_expected_rsa_oks,
            obj.primary_expected_stage,
        )
        assert starts in (0, 1) and oks in (0, 1) and oks <= starts, (
            f"{name}: primary_expected_rsa_starts={starts}, primary_expected_rsa_oks={oks}; "
            f"each slot drives the verifier at most once and can only verify if it ran"
        )
        assert stage in _PRIMARY_STAGES, (
            f"{name}: primary_expected_stage={stage!r} is not one of {_PRIMARY_STAGES}"
        )
        assert oks or stage == "manifest", (
            f"{name}: primary_expected_stage={stage!r} with primary_expected_rsa_oks=0; "
            f"MANIFEST_OK follows RSA_VERIFY_OK, so an unverified primary stops at the "
            f"manifest stage"
        )
        if concrete:
            assert obj.primary_expected_error, (
                f"{name}: set primary_expected_error to the code the primary is refused with"
            )
            assert obj.primary_defect_marker, (
                f"{name}: set primary_defect_marker to the arm's own marker, or to "
                f'f"MANIFEST_ERR=0x{{code:08x}}" when the arm prints none'
            )

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        cls._check_contract(cls)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._check_contract(self)
        self.required_markers = (
            sep_rom_ot_dma_boot_test.required_markers + (_LC_PROD,) + tuple(self.extra_required)
        )
        self.forbidden_markers = (
            sep_rom_ot_dma_boot_test.forbidden_markers
            + (_SBOOT_OFF, _ALL_FAILED, _SBOOT_DIS_FUSE)
            + tuple(self.extra_forbidden)
        )

    def primary_attempt_ordered(self) -> tuple[str, ...]:
        seq: tuple[str, ...] = ()
        if self.primary_expected_rsa_starts:
            seq += (_KEY_OK, _RSA_EXEC)
        if self.primary_expected_rsa_oks:
            seq += (_RSA_OK,)
        if self.primary_expected_stage != "manifest":
            seq += (_MANIFEST_OK,)
        seq += tuple(self.primary_ordered)
        if self.primary_defect_marker:
            seq += (self.primary_defect_marker,)
        return seq

    def primary_attempt_absent(self) -> tuple[str, ...]:
        absent = tuple(self.primary_absent)
        if not self.primary_expected_rsa_starts:
            absent += (_RSA_EXEC,)
        if not self.primary_expected_rsa_oks:
            absent += (_RSA_OK,)
        return absent

    def backup_attempt_ordered(self) -> tuple[str, ...]:
        seq = (_KEY_OK, _RSA_EXEC, _RSA_OK, _MANIFEST_OK)
        if self._backup_encrypted:
            seq += (_DECRYPT_OK,)
        return seq + (_PAYLOAD_OK,)

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
            "BL1_VERSION=0x%x, PUBK_REVOKE=0x%x",
            lc,
            sboot_dis,
            image.field_int("BL1_VERSION"),
            image.field_int("CHIPLET_PUBK_REVOKE"),
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        self.corrupt_primary(buf)
        self.prepare_backup(buf)
        pm.verify_sealed(buf, "backup")
        mm.verify_public_key(buf, "backup")
        self._backup_encrypted = pm.is_encrypted(buf, "backup")
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        self.logger.info("CHK-STIMULUS-BACKUP:  %s", mm.describe(buf, "backup"))
        self.logger.info(
            "CHK-STIMULUS-BACKUP-SEALED PASS: backup passes payload_hash, %severy TOC "
            "image digest and the hash chain, manifest_hash and RSA verification of its "
            "signature; the modulus it carries hashes to the ROM's slot digest",
            "decryption under the golden CLASS_KEY, " if self._backup_encrypted else "",
        )
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

    def check_transport(self, console: list[str], flash) -> None:
        attempts = oc.split_attempts(console)
        srcs = [f"0x{a.src:08x}" for a in attempts]
        want = [f"0x{mm.PRIMARY_MANIFEST_OFFSET:08x}", f"0x{mm.BACKUP_MANIFEST_OFFSET:08x}"]
        assert srcs == want, (
            f"slot attempts read {srcs}, expected {want}: a failover is the primary "
            f"then the backup, once each. Console: {console}"
        )
        primary, backup = attempts

        # The slot headers precede MANIFEST_SRC=, so they sit outside both attempts.
        def header_at(token: str) -> list[int]:
            return [i for i, line in enumerate(console) if line.strip() == token]

        i_ph, i_bh = header_at("MANIFEST_PRIMARY"), header_at("MANIFEST_BACKUP")
        assert len(i_ph) == 1 and i_ph[0] < primary.first, (
            f"MANIFEST_PRIMARY@{i_ph} is not once before the primary attempt@{primary.first}"
        )
        assert len(i_bh) == 1 and primary.last < i_bh[0] < backup.first, (
            f"MANIFEST_BACKUP@{i_bh} is not once between the primary error@{primary.last} "
            f"and the backup attempt@{backup.first}"
        )

        p_ordered = self.primary_attempt_ordered()
        oc.assert_attempt(
            primary,
            error=self.primary_expected_error,
            stage=self.primary_expected_stage,
            ordered=p_ordered,
            absent=self.primary_attempt_absent(),
        )
        if self.primary_defect_marker:
            tail = [line for _, line in primary.markers][-2:]
            assert oc.count(tail, self.primary_defect_marker) == 1, (
                f"{self.primary_defect_marker} is not the primary's error line or the "
                f"line just before it (attempt ends {tail}): a later check also refused "
                f"the slot, so the verdict is not the planted defect's"
            )
        b_ordered = self.backup_attempt_ordered()
        oc.assert_attempt(
            backup,
            error=None,
            stage="accepted",
            ordered=b_ordered,
            absent=(self.primary_defect_marker,) if self.primary_defect_marker else (),
        )

        for marker, want_n in (
            (_RSA_EXEC, 1 + self.primary_expected_rsa_starts),
            (_RSA_OK, 1 + self.primary_expected_rsa_oks),
        ) + (((self.primary_defect_marker, 1),) if self.primary_defect_marker else ()):
            n = oc.count(console, marker)
            assert n == want_n, (
                f"{marker} appeared {n} times, expected exactly {want_n} (declared "
                f"rsa_starts={self.primary_expected_rsa_starts}, "
                f"rsa_oks={self.primary_expected_rsa_oks}). Console: {console}"
            )
        self.logger.info(
            "CHK-PRIMARY-FAILOVER PASS: primary@%d-%d 0x%08x at %s after %s; "
            "backup@%d-%d accepted after %s",
            primary.first,
            primary.last,
            self.primary_expected_error,
            self.primary_expected_stage,
            " -> ".join(p_ordered) or "no marker",
            backup.first,
            backup.last,
            " -> ".join(b_ordered),
        )

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
            "CHK-FAILOVER-ADDR: device served read[%d] 0x%06x first and read[%d] 0x%06x second",
            p_idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            b_idx,
            mm.BACKUP_MANIFEST_OFFSET,
        )
