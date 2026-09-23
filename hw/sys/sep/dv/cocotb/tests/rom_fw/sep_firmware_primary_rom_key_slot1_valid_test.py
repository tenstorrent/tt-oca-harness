# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary names ROM key slot 1 and boots -> proves a non-zero slot can verify.

The manifest carries slot 1's modulus and is re-signed with slot 1's test key. That key
exists only under ``TEST_BUILD``; a release ROM refuses slot 1 with ``ROM_KEY_EMPTY``.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_rom_key_slots as ks
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)

_DV_ROOT = Path(__file__).resolve().parents[3]

_EFUSE_PRELOAD = (
    _DV_ROOT / "tb" / "efuse_preloads" / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

_VALID_SLOT = 1
_PUBK_SEL_ECHO = f"PUBK_SEL=0x{_VALID_SLOT:08x}"
_REVOKE_ECHO = "PUBK_REVOKE=0x00000000"

_LC_PROD = "LC=PROD"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_RSA_START = "RSA_VERIFY_START"
_SIG_VALID = "SIG_VALID"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"
_BL1_COPIED = "BL1_COPIED"
_BL1_JUMP = "BL1_JUMP="

_SBOOT_OFF = "SBOOT_OFF"
_ANY_MANIFEST_ERR = "MANIFEST_ERR="
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_SBOOT_DIS_FUSE = "FUSE: SBOOT_DIS: 1"


@pyuvm.test()
class sep_firmware_primary_rom_key_slot1_valid_test(sep_rom_ot_dma_boot_test):
    """Primary names ROM slot 1, carries its key, and boots without failover."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD, _PRIMARY_SRC, _PUBK_SEL_ECHO, _REVOKE_ECHO, _RSA_START,
        _SIG_VALID, _CRYPTO_OK, _BL1_COPIED, _BL1_JUMP,
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _SBOOT_OFF, _SBOOT_DIS_FUSE, _BACKUP_SRC, _ANY_MANIFEST_ERR, _ALL_FAILED,
        "BAD_SIG_TYPE=", "BAD_KEY_IDX", "BAD_KEY_SEL", "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH", "KEY_REVOKED", "VERSION_ROLLBACK",
        "RSA_VERIFY_FAIL", "CRYPTO_FAIL=",
    )

    def build_efuse_image(self):
        assert _EFUSE_PRELOAD.is_file(), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced by the lifecycle, or the key selection under test is not "
            f"reached on the production path"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: slot {_VALID_SLOT} "
            f"must not be revoked, or this positive case becomes its own negative "
            f"twin"
        )
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection and would reject the primary first"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, BL1_VERSION=0x%x, "
            "PUBK_REVOKE=0x%x", lc, sboot_dis, bl1_ver, revoke,
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        info = ks.bind_manifest_to_rom_slot(buf, "primary", _VALID_SLOT)
        assert info["tbs_changed"], (
            f"selecting slot {_VALID_SLOT} left the TBS unchanged; the shipped "
            f"primary already selects it (configs/secure_boot_test.yaml)"
        )
        self.logger.info(
            "CHK-STIMULUS-SLOT1: public_key_sel=0x%04x, modulus digest=%s, "
            "re-signed with %s", info["selector"], info["digest"].hex()[:16],
            Path(info["key_path"]).name,
        )
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info("CHK-SPI-TXNS:\n%s",
                         ev.summarize(flash.get_transactions(), self._image_len))

    def check_transport(self, console: list[str], flash) -> None:
        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        i_psrc = index_of(_PRIMARY_SRC)
        i_sel = index_of(_PUBK_SEL_ECHO)
        i_revoke = index_of(_REVOKE_ECHO)
        i_rsa = index_of(_RSA_START)
        i_sig = index_of(_SIG_VALID)
        i_ok = index_of(_CRYPTO_OK)

        assert 0 <= i_psrc < i_sel < i_revoke < i_rsa < i_sig < i_ok, (
            f"key selection did not run on the primary in the architected order: "
            f"primary@{i_psrc} -> {_PUBK_SEL_ECHO}@{i_sel} -> {_REVOKE_ECHO}"
            f"@{i_revoke} -> {_RSA_START}@{i_rsa} -> {_SIG_VALID}@{i_sig} -> "
            f"{_CRYPTO_OK}@{i_ok}. Console: {console}"
        )
        for marker in (_PUBK_SEL_ECHO, _REVOKE_ECHO, _RSA_START, _SIG_VALID):
            n = sum(1 for line in console if marker in line)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the primary's). "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-KEYSEL-RAN: primary@%d -> %s@%d -> %s@%d -> %s@%d -> %s@%d -> "
            "%s@%d, each exactly once; the ROM-key path permitted slot %d",
            i_psrc, _PUBK_SEL_ECHO, i_sel, _REVOKE_ECHO, i_revoke, _RSA_START,
            i_rsa, _SIG_VALID, i_sig, _CRYPTO_OK, i_ok, _VALID_SLOT,
        )

        txns = flash.get_transactions()
        rds = ev.reads(txns)
        assert rds, (
            f"flash BFM served no read transactions, so the boot did not come from "
            f"this device. All {len(txns)} transactions: "
            f"{[hex(t['opcode']) for t in txns]}"
        )
        hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        assert hit is not None, (
            f"no SPI read covered the primary manifest address "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:x}: the boot did not come from the "
            f"primary address"
        )
        idx, txn = hit
        magic = ev.bytes_at(txn, mm.PRIMARY_MANIFEST_OFFSET, 4)
        assert magic == mm.MANIFEST_MAGIC, (
            f"device returned {magic!r} at 0x{mm.PRIMARY_MANIFEST_OFFSET:x}, "
            f"expected {mm.MANIFEST_MAGIC!r}"
        )
        # Console markers alone cannot tell a primary boot from a failover.
        backup_hits = ev.slot_read_indices(rds, "backup", self._image_len)
        assert not backup_hits, (
            f"device served {len(backup_hits)} read(s) inside the backup slot span "
            f"(read indices {backup_hits}): this is a failover result, not a "
            f"primary slot-{_VALID_SLOT} key-selection result"
        )
        self.logger.info(
            "CHK-NO-FAILOVER: read[%d] at 0x%06x returned magic %r, and no read "
            "touched the backup span across %d reads -- the PRIMARY served this "
            "boot", idx, mm.PRIMARY_MANIFEST_OFFSET, magic, len(rds),
        )
