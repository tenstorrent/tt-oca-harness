# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest fails the public-key hash bind; the backup boots.

One bit of the primary's RSA-3072 modulus is flipped and the signed region is re-hashed, so the
slot fails the SHA-256(modulus) comparison against the ROM's compiled-in digest for the selected
slot. The flipped modulus does not match its signature; the test proves that the bind fires
before the verifier.

Key authorization runs before ``rsa_3072_verify``, so the stale signature is never examined and
no ``RSA_EXEC`` may appear between the primary read and the backup read. The refusal returns to
the per-slot retry loop in ``rom_manifest_boot``, so the untouched backup boots; in
``sep_firmware_backup_invalid_key_hash_test`` both slots fail and the run is terminal.

Needs ``+esrc_noise_force``: the backup's RSA-3072 modexp stalls OTBN until EDN grants entropy.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev
from env.sep_efuse_image import SBOOT_DIS_MASK
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

# A key whose digest does not match its anchor is unauthorized, not revoked.
MANIFEST_ERR_KEY_HASH_MISMATCH = mm.boot_err("OCA_FAIL_ROOT_KEY_UNAUTHORIZED")

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_HASH_MISMATCH = "PUBK_UNAUTHORIZED"
_CRYPTO_FAIL = f"MANIFEST_ERR=0x{MANIFEST_ERR_KEY_HASH_MISMATCH:08x}"
_SLOT_ERR = f"MANIFEST_ERR=0x{MANIFEST_ERR_KEY_HASH_MISMATCH:08x}"
_RSA_START = "RSA_EXEC"
_RSA_VERIFY_OK = "RSA_VERIFY_OK"
_MANIFEST_OK = "MANIFEST_OK"
_LC_PROD = "LC=PROD"

# Must not appear: secure boot skipped (the bind would never have run), the run
# ending terminal instead of recovering, or the primary being rejected for a
# reason other than the planted one.
_SBOOT_OFF = "SBOOT_OFF"
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_OTHER_KEY_VERDICTS = (
    "PUBK_SLOT_RESERVED",
    "PUBK_SEL_AMBIGUOUS",
    "PUBK_OTP_EMPTY",
    "PUBK_SLOT_UNPROVISIONED",
)


@pyuvm.test()
class sep_firmware_primary_invalid_key_hash_test(sep_rom_ot_dma_boot_test):
    """Primary modulus does not match its digest -> backup retry -> boot."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD,
        _HASH_MISMATCH,
        _CRYPTO_FAIL,
        _SLOT_ERR,
        _BACKUP_SRC,
        _RSA_START,
        _RSA_VERIFY_OK,
        _MANIFEST_OK,
    )
    forbidden_markers = (
        sep_rom_ot_dma_boot_test.forbidden_markers
        + (
            _SBOOT_OFF,
            _ALL_FAILED,
            "FUSE: SBOOT_DIS: 1",
        )
        + _OTHER_KEY_VERDICTS
    )

    def build_efuse_image(self):
        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & SBOOT_DIS_MASK
        bl1_ver = image.field_int("BL1_VERSION")
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced or the key-hash bind is never reached"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        # Both of these are evaluated before the key bind and would end the run
        # first, making the verdict unattributable.
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
        )
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: revocation runs "
            f"before the hash bind, and the backup must "
            f"be able to use slot 0"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, "
            "BL1_VERSION=0x%x, PUBK_REVOKE=0x%x",
            lc,
            sboot_dis,
            bl1_ver,
            revoke,
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # verify_public_key() inside corrupt_public_key() proves the untouched
        # image really did bind to ROM slot 0, so the mismatch below is caused by
        # this mutation and not by an image that never matched.
        mm.corrupt_public_key(buf, "primary")
        # The backup must still bind, or "it recovered" would be untestable.
        mm.verify_public_key(buf, "backup")
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        self.logger.info("CHK-STIMULUS-BACKUP:  %s", mm.describe(buf, "backup"))
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

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

        # CHK-KEYHASH-ON-PRIMARY: the mismatch was the PRIMARY's verdict and the
        # trigger for the retry. Presence alone would also hold if the backup had
        # produced it, which would be the opposite scenario.
        assert i_psrc < i_hash < i_perr < i_bsrc, (
            f"key-hash rejection is not attributable to the primary: "
            f"{_PRIMARY_SRC}@{i_psrc} -> {_HASH_MISMATCH}@{i_hash} -> "
            f"{_SLOT_ERR}@{i_perr} -> {_BACKUP_SRC}@{i_bsrc}. Console: {console}"
        )

        # CHK-KEYHASH-BEFORE-RSA: no signature verification was attempted on the
        # primary. The bind exists to stop an unbound modulus from reaching the
        # verifier, so "rejected eventually" is not the same result.
        assert i_rsa > i_bsrc, (
            f"{_RSA_START} appeared at line {i_rsa}, before the backup slot was "
            f"read at line {i_bsrc}: the primary's unbound modulus reached the "
            f"RSA verifier. Console: {console}"
        )

        # CHK-KEYHASH-RECOVERED: the boot came from the backup, after the primary
        # was rejected.
        assert i_bsrc < i_ok, f"{_MANIFEST_OK}@{i_ok} did not follow the backup read@{i_bsrc}"
        self.logger.info(
            "CHK-KEYHASH-FAILOVER: primary@%d -> PUBK_UNAUTHORIZED@%d -> "
            "MANIFEST_ERR@%d -> backup@%d -> RSA_EXEC@%d -> MANIFEST_OK@%d",
            i_psrc,
            i_hash,
            i_perr,
            i_bsrc,
            i_rsa,
            i_ok,
        )

        # CHK-KEYHASH-ONE-MISMATCH: the backup did not also mismatch. A second
        # occurrence would mean the run recovered from something else.
        n_mismatch = sum(1 for line in console if _HASH_MISMATCH in line)
        assert n_mismatch == 1, (
            f"{_HASH_MISMATCH} appeared {n_mismatch} times, expected exactly 1 "
            f"(the primary's). Console: {console}"
        )

        # --- device evidence -------------------------------------------------
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
        # The device really did serve a well-formed manifest at the primary
        # address: the rejection was the key bind, not a blank or garbled slot.
        p_magic = ev.bytes_at(p_txn, mm.PRIMARY_MANIFEST_OFFSET, 4)
        assert p_magic == mm.MANIFEST_MAGIC, (
            f"device returned {p_magic!r} at 0x{mm.PRIMARY_MANIFEST_OFFSET:x}, "
            f"expected {mm.MANIFEST_MAGIC!r}: the primary was not a structurally "
            f"valid manifest, so its rejection is not attributable to the key hash"
        )
        self.logger.info(
            "CHK-KEYHASH-ADDR: read[%d] 0x%06x returned a valid %r header and was "
            "still rejected; read[%d] 0x%06x served the boot",
            p_idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            p_magic,
            b_idx,
            mm.BACKUP_MANIFEST_OFFSET,
        )
