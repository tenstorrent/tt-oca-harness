# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CHIPLET fused-key family: the manifest selects CHIPLET_PUBK_HASH0 or HASH1.

Each member sets ``_CHIPLET_KEY`` and picks the valid base (the primary boots) or the
revoked base (that key's revocation bit refuses both slots).
"""

from __future__ import annotations

from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_KEY_REVOKED,
    sep_backup_manifest_fail_base,
)
from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)

_EFUSE_DIR = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"
)

_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# CHIPLET_PUBK_REVOKE bit for each CHIPLET_PUBK_HASH fuse, from the eFuse register map.
PUBK_REVOKE_BIT_CHIPLET_HASH = (16, 17)

# Printed only by a ROM that wrongly takes the ROM-key arm with index 0.
ROM_ARM_KEY_REVOKED = "KEY_REVOKED idx=0x00000000"


def select_chiplet_fuse_key(buf: bytearray, key_index: int) -> tuple[int, int]:
    selection = (mm.PUBK_SEL_FUSE_KEY_0, mm.PUBK_SEL_FUSE_KEY_1)[key_index]
    got: list[int] = []
    for slot in ("primary", "backup"):
        # The shipped slot must be sealed and carry the dev0 modulus the chiplet fuse hashes.
        pm.verify_sealed(buf, slot)
        mm.verify_public_key(buf, slot)
        pm.verify_signing_key(buf, slot)

        mm.set_public_key_sel(buf, slot, selection=selection, index=0)
        expected = (selection & 0x7) << 4
        sel = mm.get_public_key_sel(buf, slot)
        assert sel == expected, (
            f"{slot} public_key_sel encoded as 0x{sel:04x}, expected 0x{expected:04x} "
            f"(selection=PUBK_SEL_FUSE_KEY_{key_index}, index=0)"
        )
        pm.reseal(buf, slot)
        # A stale hash or signature would refuse the slot for a reason unrelated to the key.
        pm.verify_sealed(buf, slot)
        got.append(sel)
    return got[0], got[1]


class _chiplet_key_mixin:

    # Set by every member; -1 fails an unset member instead of silently testing key 0.
    _CHIPLET_KEY: int = -1
    # Set by the concrete base, not by the member.
    _REVOKED: bool = False

    _PUBK_SEL_VALUE: int = 0
    _PUBK_SEL_ECHO: str = ""
    _REVOKE_BITMAP: int = 0
    _REVOKE_ECHO: str = ""
    _REVOKE_BIT: int = 0
    _KEY_REVOKED_ECHO: str = ""

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        key = cls._CHIPLET_KEY
        if key < 0:
            # Intermediate bases have no key; _plant_fused_selector() fails if one runs.
            return
        assert key in (0, 1), (
            f"{cls.__name__}: _CHIPLET_KEY {key} is not a CHIPLET fused key. Only "
            f"PUBK_SEL_FUSE_KEY_0 and _1 are covered here; PUBK_SEL_FUSE_SOP_KEY (4) "
            f"and PUBK_SEL_FUSE_SYS_KEY (5) are two more arms of the same switch "
            f"(manifest_crypto.c:214-221) with revoke bits 20 and 22, and have no "
            f"testcase yet"
        )
        selection = (mm.PUBK_SEL_FUSE_KEY_0, mm.PUBK_SEL_FUSE_KEY_1)[key]
        cls._PUBK_SEL_VALUE = (selection & 0x7) << 4
        cls._PUBK_SEL_ECHO = f"PUBK_SEL=0x{cls._PUBK_SEL_VALUE:08x}"
        cls._REVOKE_BIT = PUBK_REVOKE_BIT_CHIPLET_HASH[key]
        # Revoke ROM dev key 0 so a ROM that wrongly takes the ROM-key arm is refused.
        cls._REVOKE_BITMAP = 1 << 0
        if cls._REVOKED:
            cls._REVOKE_BITMAP |= 1 << cls._REVOKE_BIT
        # The ROM echoes the whole fuse word, so both slot attempts print the same value.
        cls._REVOKE_ECHO = f"PUBK_REVOKE=0x{cls._REVOKE_BITMAP:08x}"
        cls._KEY_REVOKED_ECHO = f"KEY_REVOKED idx=0x{cls._REVOKE_BIT:08x}"
        suffix = "_revoke" if cls._REVOKED else ""
        cls.efuse_preload = _EFUSE_DIR / f"sep_efuse_lc_prod_chiplet_key{key}{suffix}.toml"

    def _plant_fused_selector(self, buf: bytearray) -> None:
        p_sel, b_sel = select_chiplet_fuse_key(buf, self._CHIPLET_KEY)
        assert p_sel == b_sel == self._PUBK_SEL_VALUE, (
            f"selectors are primary=0x{p_sel:04x} backup=0x{b_sel:04x}, expected both "
            f"0x{self._PUBK_SEL_VALUE:04x}: this family's outcome shape depends on BOTH "
            f"slots selecting the same fused key, exactly as the reference does"
        )
        self.logger.info(
            "CHK-STIMULUS-FUSED-KEY: both slots public_key_sel=0x%04x "
            "(PUBK_SEL_FUSE_KEY_%d, index 0), re-signed with dev0 and re-verified "
            "sealed; the digest the ROM will compare against is CHIPLET_PUBK_HASH%d",
            p_sel, self._CHIPLET_KEY, self._CHIPLET_KEY,
        )
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        self.logger.info("CHK-STIMULUS-BACKUP: %s", mm.describe(buf, "backup"))

    def _assert_chiplet_efuse(self, image) -> None:
        key = self._CHIPLET_KEY
        other = 1 - key
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == self._REVOKE_BITMAP, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:08x}, expected "
            f"0x{self._REVOKE_BITMAP:08x}: exactly bit 0 (ROM dev key 0, the "
            f"ROM-key-arm counterfactual)"
            + (f" and bit {self._REVOKE_BIT} (CHIPLET_PUBK_HASH{key})"
               if self._REVOKED else "")
            + ". A wider bitmap could refuse a key this testcase did not select"
        )
        mine = image.field_int(f"CHIPLET_PUBK_HASH{key}")
        theirs = image.field_int(f"CHIPLET_PUBK_HASH{other}")
        # The ROM reads the digest as eight 32-bit words, byte 0 first: little-endian.
        want = int.from_bytes(mm.ROM_KEY0_DIGEST, "little")
        assert mine == want, (
            f"CHIPLET_PUBK_HASH{key} is 0x{mine:064x}, expected 0x{want:064x} -- the "
            f"little-endian SHA-256 of the dev0 modulus (key_digests.c:18-21). The "
            f"manifest is signed with dev0 and carries its modulus, so any other "
            f"value makes this a PUBK_HASH_MISMATCH testcase instead"
        )
        assert theirs != 0 and theirs != want, (
            f"CHIPLET_PUBK_HASH{other} is 0x{theirs:064x}; it must be a NON-ZERO "
            f"digest that is not the dev0 one. Zero would make a wrong-fuse read "
            f"fail as FUSE_KEY_EMPTY instead of PUBK_HASH_MISMATCH, and the dev0 "
            f"value would let a ROM reading the wrong chiplet fuse boot anyway"
        )
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364 then :369) and would end "
            f"the run before the fused-key path is reached"
        )
        self.logger.info(
            "CHK-STIMULUS-CHIPLET-EFUSE: CHIPLET_PUBK_REVOKE=0x%08x (bit 0 ROM dev "
            "key 0%s), CHIPLET_PUBK_HASH%d=dev0 digest, CHIPLET_PUBK_HASH%d=decoy "
            "(non-zero, != dev0), BL1_VERSION=0",
            revoke, f" + bit {self._REVOKE_BIT}" if self._REVOKED else "",
            key, other,
        )


class sep_chiplet_pubkey_valid_base(_chiplet_key_mixin, sep_rom_ot_dma_boot_test):

    flash_image = SECURE_FLASH_IMAGE
    _REVOKED = False

    efuse_preload: Path | None = None

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls._CHIPLET_KEY < 0:
            return
        cls.required_markers = sep_rom_ot_dma_boot_test.required_markers + (
            "LC=PROD", _PRIMARY_SRC, cls._PUBK_SEL_ECHO, cls._REVOKE_ECHO,
            "RSA_VERIFY_START", "SIG_VALID", "CRYPTO_VALIDATE_OK",
            "BL1_COPIED", "BL1_JUMP=",
        )
        cls.forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
            "SBOOT_OFF", "FUSE: SBOOT_DIS: 1", _BACKUP_SRC, "MANIFEST_ERR=",
            "MANIFEST_ALL_FAILED", "BAD_SIG_TYPE=", "BAD_KEY_IDX", "BAD_KEY_SEL",
            "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH",
            "PUBK_HASH_TIMEOUT", "KEY_REVOKED", "VERSION_ROLLBACK",
            "RSA_VERIFY_FAIL", "CRYPTO_FAIL=", "LC_USAGE_CONSTRAINT_FAIL",
        )

    def build_efuse_image(self):
        assert self.efuse_preload and self.efuse_preload.is_file(), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced by the lifecycle, or the key selection under test is never "
            f"reached on the production path"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        self._assert_chiplet_efuse(image)
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        self._plant_fused_selector(buf)
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
        i_sel = index_of(self._PUBK_SEL_ECHO)
        i_revoke = index_of(self._REVOKE_ECHO)
        i_rsa = index_of("RSA_VERIFY_START")
        i_sig = index_of("SIG_VALID")
        i_ok = index_of("CRYPTO_VALIDATE_OK")

        # CHK-FUSEKEY-RAN: presence alone does not show the fused-key path ran in order.
        assert 0 <= i_psrc < i_sel < i_revoke < i_rsa < i_sig < i_ok, (
            f"the fused-key path did not run on the primary in the architected "
            f"order: primary@{i_psrc} -> {self._PUBK_SEL_ECHO}@{i_sel} -> "
            f"{self._REVOKE_ECHO}@{i_revoke} -> RSA_VERIFY_START@{i_rsa} -> "
            f"SIG_VALID@{i_sig} -> CRYPTO_VALIDATE_OK@{i_ok}. Console: {console}"
        )
        # A second occurrence means the backup slot also reached key selection.
        for marker in (self._PUBK_SEL_ECHO, self._REVOKE_ECHO, "RSA_VERIFY_START",
                       "SIG_VALID"):
            n = sum(1 for line in console if marker in line)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the primary's). "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-FUSEKEY-RAN: primary@%d -> %s@%d -> %s@%d -> RSA_VERIFY_START@%d -> "
            "SIG_VALID@%d -> CRYPTO_VALIDATE_OK@%d, each exactly once; the ROM read "
            "CHIPLET fused key %d, found it unrevoked, and the manifest modulus bound "
            "to that fuse's digest",
            i_psrc, self._PUBK_SEL_ECHO, i_sel, self._REVOKE_ECHO, i_revoke,
            i_rsa, i_sig, i_ok, self._CHIPLET_KEY,
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
        # CHK-NO-FAILOVER: a refused primary with a booted backup passes every console check.
        backup_hits = ev.slot_read_indices(rds, "backup", self._image_len)
        assert not backup_hits, (
            f"device served {len(backup_hits)} read(s) inside the backup slot span "
            f"(read indices {backup_hits}): the primary alone did not serve this "
            f"boot, so this is a failover result and not a fused-key result"
        )
        self.logger.info(
            "CHK-NO-FAILOVER: read[%d] at 0x%06x returned magic %r, and no read "
            "touched the backup span across %d reads -- the PRIMARY served this boot",
            idx, mm.PRIMARY_MANIFEST_OFFSET, magic, len(rds),
        )


class sep_chiplet_pubkey_revoked_base(_chiplet_key_mixin, sep_backup_manifest_fail_base):

    _REVOKED = True

    expected_error = MANIFEST_ERR_KEY_REVOKED
    primary_expected_error = MANIFEST_ERR_KEY_REVOKED
    # Both manifests are otherwise valid, so neither may reach the RSA verifier.
    extra_forbidden = ("ROM_KEY_EMPTY", "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH",
                       "PUBK_HASH_TIMEOUT", "RSA_VERIFY_START", "RSA_VERIFY_FAIL",
                       "SIG_VALID", "CRYPTO_VALIDATE_OK", "BAD_KEY_IDX",
                       "BAD_KEY_SEL", "BAD_SIG_TYPE=", "VERSION_ROLLBACK",
                       "LC_USAGE_CONSTRAINT_FAIL", ROM_ARM_KEY_REVOKED)

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls._CHIPLET_KEY >= 0:
            cls.backup_defect_marker = cls._KEY_REVOKED_ECHO

    def corrupt_primary(self, buf: bytearray) -> None:
        # Both slots must reach validate_signature, so select the key instead of breaking one.
        self._plant_fused_selector(buf)

    def corrupt_backup(self, buf: bytearray) -> None:
        # corrupt_primary() already selected the key here; prove the backup is intact.
        got = mm.get_public_key_sel(buf, "backup")
        assert got == self._PUBK_SEL_VALUE, (
            f"backup public_key_sel is 0x{got:04x}, expected "
            f"0x{self._PUBK_SEL_VALUE:04x}: this member's claim is that ONE fuse bit "
            f"refuses BOTH manifests, which requires the backup to select the revoked "
            f"key too"
        )
        pm.verify_sealed(buf, "backup")
        mm.verify_public_key(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-BOTH-SEALED: backup public_key_sel=0x%04x, and the backup "
            "passes payload_hash, every TOC image digest, manifest_hash over the TBS "
            "and RSA verification of its RE-SIGNED signature against the dev0 "
            "modulus, whose SHA-256 is the CHIPLET_PUBK_HASH%d fuse value. Both "
            "manifests are genuinely bootable and one fuse bit refuses both",
            got, self._CHIPLET_KEY,
        )

    def check_efuse(self, image) -> None:
        self._assert_chiplet_efuse(image)

    def check_defect_attribution(self, console, i_backup: int) -> None:
        # Both slots print the marker, so require one occurrence on each side of the backup read.
        hits = [i for i, line in enumerate(console)
                if self.backup_defect_marker in line]
        assert len(hits) == 2, (
            f"{self.backup_defect_marker} appeared {len(hits)} times at {hits}, "
            f"expected exactly 2 -- one per manifest slot. One occurrence would mean "
            f"only one slot reached key selection. Console: {console}"
        )
        assert hits[0] < i_backup < hits[1], (
            f"{self.backup_defect_marker} occurrences {hits} do not straddle the "
            f"backup read@{i_backup}: the two rejections are not one per slot. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-REVOKED: %s at lines %s, one before and one after the backup "
            "read@%d -- both manifests were refused by CHIPLET_PUBK_REVOKE bit %d",
            self.backup_defect_marker, hits, i_backup, self._REVOKE_BIT,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        # Once per slot, so each KEY_REVOKED is tied to this key and this bitmap.
        for marker in (self._PUBK_SEL_ECHO, self._REVOKE_ECHO):
            n = sum(1 for line in console if marker in line)
            assert n == 2, (
                f"{marker} appeared {n} times, expected exactly 2 (one per manifest "
                f"slot): the revocation verdicts cannot be attributed to CHIPLET "
                f"fused key {self._CHIPLET_KEY} under a 0x{self._REVOKE_BITMAP:08x} "
                f"bitmap. Console: {console}"
            )

        # The base checks only the primary's CRYPTO_FAIL=; require the backup's too.
        crypto_fail = f"CRYPTO_FAIL=0x{self.expected_error:08x}"
        i_backup = next((i for i, line in enumerate(console) if _BACKUP_SRC in line), -1)
        hits = [i for i, line in enumerate(console) if crypto_fail in line]
        assert len(hits) == 2, (
            f"{crypto_fail} appeared {len(hits)} times at {hits}, expected exactly 2 "
            f"-- one per manifest slot, because both are refused by the same fuse "
            f"bit. Console: {console}"
        )
        assert 0 <= i_backup and hits[0] < i_backup < hits[1], (
            f"{crypto_fail} occurrences {hits} do not straddle the backup read"
            f"@{i_backup}: the terminal error is not attributable to both slots. "
            f"Console: {console}"
        )

        # CHK-ALL-SLOTS-EXHAUSTED: separates 'both refused' from 'stopped after the first'.
        assert any("MANIFEST_ALL_FAILED" in line for line in console), (
            f"ROM never printed MANIFEST_ALL_FAILED (manifest_load.c:808): the retry "
            f"loop did not exhaust, so the run is not the both-slots-refused outcome "
            f"this member claims. Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-SLOTS-REFUSED: %s and %s each twice, %s at lines %s straddling "
            "the backup read@%d, then MANIFEST_ALL_FAILED",
            self._PUBK_SEL_ECHO, self._REVOKE_ECHO, crypto_fail, hits, i_backup,
        )

        # The BFM record shows which addresses the device served, and in what order.
        rds = ev.reads(self._flash.get_transactions())
        p_hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert p_hit is not None and b_hit is not None, (
            f"device did not serve both manifest addresses: primary "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:x} hit={p_hit is not None}, backup "
            f"0x{mm.BACKUP_MANIFEST_OFFSET:x} hit={b_hit is not None}. Both slots "
            f"must be fetched for 'both were refused' to mean anything"
        )
        p_idx, _p = p_hit
        b_idx, _b = b_hit
        assert p_idx < b_idx, (
            f"device served the backup address (read[{b_idx}]) before the primary "
            f"(read[{p_idx}]): the transaction order is not a failover"
        )
        self.logger.info(
            "CHK-BOTH-FETCHED: device served read[%d] 0x%06x then read[%d] 0x%06x; "
            "both slots were really fetched and both were refused",
            p_idx, mm.PRIMARY_MANIFEST_OFFSET, b_idx, mm.BACKUP_MANIFEST_OFFSET,
        )
