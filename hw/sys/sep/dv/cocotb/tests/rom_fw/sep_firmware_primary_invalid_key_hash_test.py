# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest fails the public-key hash bind; the backup boots.

One modulus bit is flipped and the TBS re-hashed, so ``check_pubkey_hash`` refuses
the slot before RSA verify. Needs ``+sep_crypto_edn_force`` for the backup's RSA.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

MANIFEST_ERR_KEY_HASH_MISMATCH = 0x0003_0016

_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_HASH_MISMATCH = "PUBK_HASH_MISMATCH"
_CRYPTO_FAIL = f"CRYPTO_FAIL=0x{MANIFEST_ERR_KEY_HASH_MISMATCH:08x}"
_SLOT_ERR = f"MANIFEST_ERR=0x{MANIFEST_ERR_KEY_HASH_MISMATCH:08x}"
_RSA_START = "RSA_VERIFY_START"
_SIG_VALID = "SIG_VALID"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"
_MANIFEST_OK = "MANIFEST_OK"
_LC_PROD = "LC=PROD"

_SBOOT_OFF = "SBOOT_OFF"
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_OTHER_KEY_VERDICTS = ("BAD_KEY_IDX", "BAD_KEY_SEL", "FUSE_KEY_EMPTY",
                       "ROM_KEY_EMPTY", "KEY_REVOKED", "VERSION_ROLLBACK")


@pyuvm.test()
class sep_firmware_primary_invalid_key_hash_test(sep_rom_ot_dma_boot_test):
    """Primary modulus does not match its digest -> backup retry -> boot."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD, _HASH_MISMATCH, _CRYPTO_FAIL, _SLOT_ERR, _BACKUP_SRC,
        _RSA_START, _SIG_VALID, _CRYPTO_OK,
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _SBOOT_OFF, _ALL_FAILED, "FUSE: SBOOT_DIS: 1",
    ) + _OTHER_KEY_VERDICTS

    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        bl1_ver = image.field_int("BL1_VERSION")
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced or the key-hash bind is never reached"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364)"
        )
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: revocation runs "
            f"before the hash bind (manifest_crypto.c:181), and the backup must "
            f"be able to use slot 0"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, "
            "BL1_VERSION=0x%x, PUBK_REVOKE=0x%x", lc, sboot_dis, bl1_ver, revoke,
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # corrupt_public_key() first checks that the shipped primary binds to slot 0.
        mm.corrupt_public_key(buf, "primary")
        mm.verify_public_key(buf, "backup")
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        self.logger.info("CHK-STIMULUS-BACKUP:  %s", mm.describe(buf, "backup"))
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
        i_hash = index_of(_HASH_MISMATCH)
        i_perr = index_of(_SLOT_ERR)
        i_bsrc = index_of(_BACKUP_SRC)
        i_rsa = index_of(_RSA_START)
        i_ok = index_of(_MANIFEST_OK)

        assert i_psrc < i_hash < i_perr < i_bsrc, (
            f"key-hash rejection is not attributable to the primary: "
            f"{_PRIMARY_SRC}@{i_psrc} -> {_HASH_MISMATCH}@{i_hash} -> "
            f"{_SLOT_ERR}@{i_perr} -> {_BACKUP_SRC}@{i_bsrc}. Console: {console}"
        )

        assert i_rsa > i_bsrc, (
            f"{_RSA_START} appeared at line {i_rsa}, before the backup slot was "
            f"read at line {i_bsrc}: the primary's unbound modulus reached the "
            f"RSA verifier. Console: {console}"
        )

        assert i_bsrc < i_ok, (
            f"{_MANIFEST_OK}@{i_ok} did not follow the backup read@{i_bsrc}"
        )
        self.logger.info(
            "CHK-KEYHASH-FAILOVER: primary@%d -> PUBK_HASH_MISMATCH@%d -> "
            "MANIFEST_ERR@%d -> backup@%d -> RSA_VERIFY_START@%d -> MANIFEST_OK@%d",
            i_psrc, i_hash, i_perr, i_bsrc, i_rsa, i_ok,
        )

        n_mismatch = sum(1 for line in console if _HASH_MISMATCH in line)
        assert n_mismatch == 1, (
            f"{_HASH_MISMATCH} appeared {n_mismatch} times, expected exactly 1 "
            f"(the primary's). Console: {console}"
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
        p_idx, p_txn = p_hit
        b_idx, _ = b_hit
        assert p_idx < b_idx, (
            f"device served the backup address (read[{b_idx}]) before the primary "
            f"(read[{p_idx}]): the transaction order is not a failover"
        )
        p_magic = ev.bytes_at(p_txn, mm.PRIMARY_MANIFEST_OFFSET, 4)
        assert p_magic == mm.MANIFEST_MAGIC, (
            f"device returned {p_magic!r} at 0x{mm.PRIMARY_MANIFEST_OFFSET:x}, "
            f"expected {mm.MANIFEST_MAGIC!r}: the primary was not a structurally "
            f"valid manifest, so its rejection is not attributable to the key hash"
        )
        self.logger.info(
            "CHK-KEYHASH-ADDR: read[%d] 0x%06x returned a valid %r header and was "
            "still rejected; read[%d] 0x%06x served the boot",
            p_idx, mm.PRIMARY_MANIFEST_OFFSET, p_magic,
            b_idx, mm.BACKUP_MANIFEST_OFFSET,
        )
