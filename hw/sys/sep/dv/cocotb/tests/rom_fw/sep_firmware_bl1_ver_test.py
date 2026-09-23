# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""BL1 security version EQUALS the BL1_VERSION fuse floor -> accepted, boots.

Fuse word i holds i+1 bits (floor 36), so a misread word changes the exact ``FUSE_VER=`` echo.
Both slots are re-signed with dev0; needs ``+sep_crypto_edn_force`` for the RSA-3072 modexp.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod_bl1ver36_spread.toml"
)

# Equal to the fuse floor: that equality is the accept boundary under test.
_SECURITY_VERSION = 36
_FUSE_VER_ECHO = f"FUSE_VER=0x{_SECURITY_VERSION:08x}"
_MFST_VER_ECHO = f"MFST_VER=0x{_SECURITY_VERSION:08x}"

_LC_PROD = "LC=PROD"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_PUBK_SEL = "PUBK_SEL="
_RSA_START = "RSA_VERIFY_START"
_SIG_VALID = "SIG_VALID"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"


@pyuvm.test()
class sep_firmware_bl1_ver_test(sep_rom_ot_dma_boot_test):
    """manifest security_version == BL1_VERSION popcount -> accepted, primary boots."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD, _PRIMARY_SRC, _FUSE_VER_ECHO, _MFST_VER_ECHO,
        _RSA_START, _SIG_VALID, _CRYPTO_OK, "BL1_COPIED", "BL1_JUMP=",
    )
    # VERSION_ROLLBACK is the arm this boundary must not take; the rest exclude other boot paths.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        "VERSION_ROLLBACK", "SBOOT_OFF", "FUSE: SBOOT_DIS: 1", _BACKUP_SRC,
        "MANIFEST_ERR=", "MANIFEST_ALL_FAILED", "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
        "BAD_SIG_TYPE=", "BAD_KEY_IDX", "BAD_KEY_SEL", "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH", "PUBK_HASH_TIMEOUT", "KEY_REVOKED",
        "LC_USAGE_CONSTRAINT_FAIL",
    )

    def build_efuse_image(self):
        assert _EFUSE_PRELOAD.is_file(), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): the rollback check is "
            f"reached through manifest_crypto_validate, which only runs when secure "
            f"boot is enabled (manifest_load.c:668-669)"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the whole crypto chain, including the "
            f"rollback check under test, would be skipped"
        )
        bl1_ver = image.field_int("BL1_VERSION")
        popcount = bin(bl1_ver).count("1")
        words = [(bl1_ver >> (32 * i)) & 0xFFFF_FFFF for i in range(8)]
        nonzero_words = sum(1 for w in words if w)
        assert popcount == _SECURITY_VERSION, (
            f"BL1_VERSION popcount is {popcount}, expected {_SECURITY_VERSION}: the "
            f"fuse floor must EQUAL the manifest security_version this testcase "
            f"writes, or the run is no longer the accept boundary"
        )
        assert nonzero_words == 8, (
            f"BL1_VERSION has bits in only {nonzero_words} of its 8 words "
            f"({[hex(w) for w in words]}): this testcase's whole thermometer claim "
            f"is that all eight mmio_read32() calls of "
            f"get_security_version_from_fuse (manifest_crypto.c:73-84) contribute, "
            f"and a floor concentrated in one word cannot show that"
        )
        per_word = [bin(w).count("1") for w in words]
        assert sorted(per_word) == list(range(1, 9)), (
            f"BL1_VERSION per-word popcounts are {per_word}, expected a permutation "
            f"of 1..8. Equal or duplicated per-word contributions would let a "
            f"mis-indexed decode reach the same total, and this testcase's "
            f"thermometer claim rests on that not being possible"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: a revoked key would "
            f"reject the manifest after the version check passed, and this positive "
            f"testcase would fail for a reason that has nothing to do with rollback"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, PUBK_REVOKE=0x%x, "
            "BL1_VERSION popcount=%d spread over %d/8 words %s with per-word "
            "popcounts %s (a permutation of 1..8, so no mis-indexed decode reaches "
            "the same total)",
            lc, sboot_dis, revoke, popcount, nonzero_words, [hex(w) for w in words],
            per_word,
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            # A re-seal is sound only if the local signer reproduces the shipped signature.
            pm.verify_sealed(buf, slot)
            mm.verify_public_key(buf, slot)
            pm.verify_signing_key(buf, slot)

            before = mm.security_version(buf, slot)
            assert before < _SECURITY_VERSION, (
                f"shipped {slot} security_version is already {before}, which is not "
                f"below the {_SECURITY_VERSION} this testcase writes; the mutation "
                f"would be a no-op or a downgrade and the boundary would not be set "
                f"by this testcase (configs/secure_boot_test.yaml:65 and :130 ship 0)"
            )
            mm.set_security_version(buf, slot, _SECURITY_VERSION)
            got = mm.security_version(buf, slot)
            assert got == _SECURITY_VERSION, (
                f"{slot} security_version reads back {got} after the write, expected "
                f"{_SECURITY_VERSION}"
            )
            pm.reseal(buf, slot)
            pm.verify_sealed(buf, slot)
            self.logger.info("CHK-STIMULUS-%s: %s", slot.upper(), mm.describe(buf, slot))
        self.logger.info(
            "CHK-STIMULUS-BOUNDARY: both slots security_version %d -> %d, re-signed "
            "with dev0 and re-verified sealed; the fuse floor is also %d, so the "
            "manifest sits EXACTLY on the accept boundary of manifest_crypto.c:94",
            0, _SECURITY_VERSION, _SECURITY_VERSION,
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
        i_fuse = index_of(_FUSE_VER_ECHO)
        i_mfst = index_of(_MFST_VER_ECHO)
        i_sel = index_of(_PUBK_SEL)
        i_rsa = index_of(_RSA_START)
        i_sig = index_of(_SIG_VALID)
        i_ok = index_of(_CRYPTO_OK)

        assert 0 <= i_psrc < i_fuse < i_mfst < i_rsa < i_sig < i_ok, (
            f"the rollback check did not run on the primary in the architected "
            f"order: primary@{i_psrc} -> {_FUSE_VER_ECHO}@{i_fuse} -> "
            f"{_MFST_VER_ECHO}@{i_mfst} -> {_RSA_START}@{i_rsa} -> "
            f"{_SIG_VALID}@{i_sig} -> {_CRYPTO_OK}@{i_ok}. Console: {console}"
        )
        # check_security_version must precede validate_signature; key-selection tests rely on it.
        assert 0 <= i_fuse < i_sel, (
            f"{_FUSE_VER_ECHO}@{i_fuse} did not precede {_PUBK_SEL}@{i_sel}: the "
            f"rollback check no longer runs before key selection, which invalidates "
            f"the attribution of every key-selection testcase in this testlist. "
            f"Console: {console}"
        )
        for marker in (_FUSE_VER_ECHO, _MFST_VER_ECHO, _RSA_START, _SIG_VALID):
            n = sum(1 for line in console if marker in line)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the primary's). "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-ROLLBACK-BOUNDARY: primary@%d -> %s@%d -> %s@%d (equal, so accepted) "
            "-> %s@%d -> %s@%d -> %s@%d, each exactly once; and the version check "
            "preceded %s@%d",
            i_psrc, _FUSE_VER_ECHO, i_fuse, _MFST_VER_ECHO, i_mfst,
            _RSA_START, i_rsa, _SIG_VALID, i_sig, _CRYPTO_OK, i_ok, _PUBK_SEL, i_sel,
        )

        txns = flash.get_transactions()
        rds = ev.reads(txns)
        assert rds, (
            f"flash BFM served no read transactions, so nothing was fetched over SPI "
            f"and the boot did not come from this device. All {len(txns)} "
            f"transactions: {[hex(t['opcode']) for t in txns]}"
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
            f"device returned {magic!r} at 0x{mm.PRIMARY_MANIFEST_OFFSET:x}, expected "
            f"{mm.MANIFEST_MAGIC!r}"
        )
        # Both slots carry the same version, so only the device record rules out a failover.
        backup_hits = ev.slot_read_indices(rds, "backup", self._image_len)
        assert not backup_hits, (
            f"device served {len(backup_hits)} read(s) inside the backup slot span "
            f"(read indices {backup_hits}): the primary alone did not serve this "
            f"boot, so the accepted version cannot be attributed to the primary"
        )
        self.logger.info(
            "CHK-NO-FAILOVER: read[%d] at 0x%06x returned magic %r, and no read "
            "touched the backup span across %d reads -- the PRIMARY served this boot",
            idx, mm.PRIMARY_MANIFEST_OFFSET, magic, len(rds),
        )
