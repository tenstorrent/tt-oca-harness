# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest selects a revoked ROM key slot; each member sets ``_REVOKED_SLOT``.

Slot 0 is terminal because both manifests select ROM key 0; slots 1-5 fail over and boot.
Slots 1-5 need ``+sep_crypto_edn_force`` for the backup's RSA modexp; slot 0 must run without it.
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
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

_EFUSE_DIR = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"
)

# public_key_sel packs selection[6:4] and index[3:0]; ROM-key selection is 0.
PUBK_SEL_ROM_KEY = 0

_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"


def select_primary_rom_slot(buf: bytearray, slot_index: int) -> tuple[int, bool]:
    base = mm.slot_base("primary")
    tbs_before = bytes(buf[base:base + mm.TBS_LEN])
    mm.set_public_key_sel(buf, "primary", selection=PUBK_SEL_ROM_KEY, index=slot_index)
    tbs_after = bytes(buf[base:base + mm.TBS_LEN])
    tbs_changed = tbs_before != tbs_after

    got = mm.get_public_key_sel(buf, "primary")
    expected = slot_index & 0xF
    assert got == expected, (
        f"primary public_key_sel encoded as 0x{got:04x}, expected 0x{expected:04x} "
        f"(selection=PUBK_SEL_ROM_KEY, index={slot_index})"
    )
    # The primary must still carry the dev0 modulus at OFF_PUBLIC_KEY, or the test proves nothing.
    mm.verify_public_key(buf, "primary")
    if not tbs_changed:
        pm.verify_sealed(buf, "primary")
    else:
        n, e_pub, _d = pm.load_rsa_private_key()
        sig = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES])
        assert not pm.verify_pkcs1v15_sha256(tbs_after, sig, n, e_pub), (
            "primary signature still verifies after the selector was changed; the "
            "write did not land inside the TBS, so the ROM would read the original "
            f"selector and this testcase would prove nothing about slot {slot_index}"
        )
        mm.verify_layout(buf, "primary")
    return got, tbs_changed


class _primary_revoked_slot_mixin:

    # -1 marks an unset member so it cannot silently test slot 0.
    _REVOKED_SLOT: int = -1

    _REVOKE_BITMAP: int = 0
    _PUBK_SEL_VALUE: int = 0
    _PUBK_SEL_ECHO: str = ""
    _REVOKE_ECHO: str = ""
    _KEY_REVOKED_ECHO: str = ""

    _BACKUP_ALSO_REVOKED: bool = False

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        slot = cls._REVOKED_SLOT
        if slot < 0:
            return
        assert 0 <= slot < mm.PUBK_SEL_NUM_ROM_KEYS, (
            f"{cls.__name__}: _REVOKED_SLOT {slot} is outside the ROM key table "
            f"[0, {mm.PUBK_SEL_NUM_ROM_KEYS}); an out-of-range index is the "
            f"separate BAD_KEY_IDX arm (manifest_crypto.c:174-177), not a "
            f"revocation testcase"
        )
        cls._REVOKE_BITMAP = 1 << slot
        cls._PUBK_SEL_VALUE = slot & 0xF
        cls._KEY_REVOKED_ECHO = f"KEY_REVOKED idx=0x{slot:08x}"
        cls._REVOKE_ECHO = f"PUBK_REVOKE=0x{cls._REVOKE_BITMAP:08x}"
        cls._PUBK_SEL_ECHO = f"PUBK_SEL=0x{cls._PUBK_SEL_VALUE:08x}"
        cls.efuse_preload = _EFUSE_DIR / f"sep_efuse_lc_prod_pubk_revoke{slot}.toml"

    # --- stimulus ----------------------------------------------------------
    def _plant_revoked_selector(self, buf: bytearray) -> None:
        got, tbs_changed = select_primary_rom_slot(buf, self._REVOKED_SLOT)
        expect_changed = self._REVOKED_SLOT != 0
        assert tbs_changed == expect_changed, (
            f"slot {self._REVOKED_SLOT}: primary TBS changed={tbs_changed}, "
            f"expected {expect_changed}. The shipped primary manifest no longer "
            f"selects ROM slot 0 (configs/secure_boot_test.yaml:43-45), so this "
            f"member is no longer testing what its docstring claims"
        )
        self._assert_outcome_shape(buf)
        self.logger.info(
            "CHK-STIMULUS-REVOKED-SLOT: primary public_key_sel=0x%04x (ROM key slot "
            "%d, revoked by CHIPLET_PUBK_REVOKE bit %d); TBS changed=%s, primary "
            "manifest %s",
            got, self._REVOKED_SLOT, self._REVOKED_SLOT, tbs_changed,
            "re-hashed, signature now stale" if tbs_changed
            else "untouched and still fully sealed with a valid dev0 signature",
        )

    def _assert_outcome_shape(self, buf: bytearray) -> None:
        backup_sel = mm.get_public_key_sel(buf, "backup")
        backup_revoked = bool(self._REVOKE_BITMAP & (1 << (backup_sel & 0xF))) and \
            ((backup_sel >> 4) & 0x7) == PUBK_SEL_ROM_KEY
        assert backup_revoked == self._BACKUP_ALSO_REVOKED, (
            f"slot {self._REVOKED_SLOT}: the backup selector is 0x{backup_sel:04x}, "
            f"so 'the backup is refused by the same fuse bit' is {backup_revoked}, "
            f"but this member is built on the "
            f"{'TERMINAL' if self._BACKUP_ALSO_REVOKED else 'FAILOVER'} base which "
            f"requires {self._BACKUP_ALSO_REVOKED}. The outcome shape of this family "
            f"depends on both slots naming ROM key 0 "
            f"(configs/secure_boot_test.yaml:43-45 and :112-114); that is no longer "
            f"true, so the member's expected outcome is wrong"
        )
        self.logger.info(
            "CHK-STIMULUS-OUTCOME-SHAPE: backup selector 0x%04x, refused by bitmap "
            "0x%x = %s -> %s expected", backup_sel, self._REVOKE_BITMAP,
            backup_revoked, "TERMINAL" if backup_revoked else "FAILOVER",
        )

    def check_efuse(self, image) -> None:
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == self._REVOKE_BITMAP, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected "
            f"0x{self._REVOKE_BITMAP:x}: exactly bit {self._REVOKED_SLOT} must be "
            f"blown -- a wider bitmap could reject a manifest through a slot this "
            f"testcase did not select"
        )
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364 then :369) and would "
            f"terminate the run before revocation is reached"
        )


class sep_primary_pubkey_rom_revoked_failover_base(
        _primary_revoked_slot_mixin, sep_primary_fail_backup_boot_base):

    _BACKUP_ALSO_REVOKED = False

    primary_expected_error = MANIFEST_ERR_KEY_REVOKED
    # Revocation precedes rsa_3072_verify, so the primary never starts the verifier.
    primary_expected_rsa_starts = 0
    # Other validate_signature rejections; PUBK_HASH_MISMATCH means the digest check ran first.
    extra_forbidden = ("ROM_KEY_EMPTY", "PUBK_HASH_MISMATCH", "BAD_KEY_IDX",
                       "BAD_KEY_SEL", "FUSE_KEY_EMPTY", "VERSION_ROLLBACK",
                       "BAD_SIG_TYPE=", "RSA_VERIFY_FAIL")
    # Every slot echoes the same PUBK_REVOKE= word, so the backup needs only its selector echo.
    _BACKUP_SEL_ECHO = "PUBK_SEL=0x00000000"

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls._REVOKED_SLOT < 0:
            return
        # Class attributes: the base reads primary_defect_marker through a classmethod.
        cls.primary_defect_marker = cls._KEY_REVOKED_ECHO
        cls.extra_required = (cls._PUBK_SEL_ECHO, cls._REVOKE_ECHO,
                              cls._BACKUP_SEL_ECHO)

    def corrupt_primary(self, buf: bytearray) -> None:
        self._plant_revoked_selector(buf)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        def indices_of(marker: str) -> list[int]:
            return [i for i, line in enumerate(console) if marker in line]

        i_psrc = index_of(_PRIMARY_SRC)
        i_sel = index_of(self._PUBK_SEL_ECHO)
        i_revoked = index_of(self._KEY_REVOKED_ECHO)
        i_bsrc = index_of(_BACKUP_SRC)
        revokes = indices_of(self._REVOKE_ECHO)

        # Count first, so an empty list fails as an assertion and not an IndexError.
        assert len(revokes) == 2, (
            f"{self._REVOKE_ECHO} appeared {len(revokes)} times at {revokes}, "
            f"expected exactly 2 -- check_pubkey_revoked echoes the whole fuse word "
            f"once per slot attempt (manifest_crypto.c:108-109). Console: {console}"
        )

        # Primary selector, fuse check and refusal must all precede the backup read.
        assert 0 <= i_psrc < i_sel < revokes[0] < i_revoked < i_bsrc, (
            f"the revocation verdict is not attributable to the primary's slot "
            f"{self._REVOKED_SLOT}: primary@{i_psrc} -> {self._PUBK_SEL_ECHO}"
            f"@{i_sel} -> {self._REVOKE_ECHO}@{revokes} -> "
            f"{self._KEY_REVOKED_ECHO}@{i_revoked} -> backup@{i_bsrc}. "
            f"Console: {console}"
        )
        for marker in (self._PUBK_SEL_ECHO, self._KEY_REVOKED_ECHO):
            n = sum(1 for line in console if marker in line)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the primary's). "
                f"Console: {console}"
            )
        assert revokes[0] < i_bsrc < revokes[1], (
            f"{self._REVOKE_ECHO} occurrences {revokes} do not straddle the backup "
            f"read@{i_bsrc}: the booting slot did not consult the revocation bitmap. "
            f"Console: {console}"
        )
        i_bsel = index_of(self._BACKUP_SEL_ECHO)
        assert i_bsrc < i_bsel < revokes[1], (
            f"the booting slot's key selection is unattributed: backup@{i_bsrc} -> "
            f"{self._BACKUP_SEL_ECHO}@{i_bsel} -> {self._REVOKE_ECHO}@{revokes[1]}. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-REVOKE-FAILOVER: primary %s -> %s -> %s (slot %d refused once) -> "
            "backup %s -> %s again at line %d, permitted -> boot",
            self._PUBK_SEL_ECHO, self._REVOKE_ECHO, self._KEY_REVOKED_ECHO,
            self._REVOKED_SLOT, self._BACKUP_SEL_ECHO, self._REVOKE_ECHO,
            revokes[1],
        )


class sep_primary_pubkey_rom_revoked_terminal_base(
        _primary_revoked_slot_mixin, sep_backup_manifest_fail_base):

    _BACKUP_ALSO_REVOKED = True

    expected_error = MANIFEST_ERR_KEY_REVOKED
    primary_expected_error = MANIFEST_ERR_KEY_REVOKED
    # Both manifests are otherwise valid, so any verifier marker means revocation did not act.
    extra_forbidden = ("ROM_KEY_EMPTY", "PUBK_HASH_MISMATCH", "RSA_VERIFY_START",
                       "RSA_VERIFY_FAIL", "SIG_VALID", "CRYPTO_VALIDATE_OK",
                       "BAD_KEY_IDX", "BAD_KEY_SEL", "FUSE_KEY_EMPTY",
                       "VERSION_ROLLBACK", "BAD_SIG_TYPE=")

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls._REVOKED_SLOT >= 0:
            cls.backup_defect_marker = cls._KEY_REVOKED_ECHO

    # --- stimulus ----------------------------------------------------------
    def corrupt_primary(self, buf: bytearray) -> None:
        # Not the base's BAD_MAGIC defect: the primary must reach validate_signature.
        self._plant_revoked_selector(buf)

    def corrupt_backup(self, buf: bytearray) -> None:
        # No planted defect: the shipped backup already selects the revoked slot.
        got = mm.get_public_key_sel(buf, "backup")
        assert got == self._PUBK_SEL_VALUE, (
            f"backup public_key_sel is 0x{got:04x}, expected "
            f"0x{self._PUBK_SEL_VALUE:04x}: this member's whole claim is that ONE "
            f"fuse bit refuses BOTH manifests, which requires the backup to select "
            f"the revoked slot too"
        )
        pm.verify_sealed(buf, "backup")
        mm.verify_public_key(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-BOTH-SEALED: backup public_key_sel=0x%04x, and the backup "
            "passes payload_hash, every TOC image digest, manifest_hash over the "
            "TBS and RSA verification of its shipped signature against the dev0 "
            "modulus, whose SHA-256 is the ROM's compiled-in slot-0 digest. Both "
            "manifests are genuinely bootable and one fuse bit refuses both", got,
        )

    # --- checks ------------------------------------------------------------
    def check_defect_attribution(self, console, i_backup: int) -> None:
        # Both slots print the marker, so require one occurrence on each side of the backup read.
        hits = [i for i, line in enumerate(console)
                if self.backup_defect_marker in line]
        assert len(hits) == 2, (
            f"{self.backup_defect_marker} appeared {len(hits)} times at {hits}, "
            f"expected exactly 2 -- one per manifest slot. One occurrence would "
            f"mean only one slot reached key selection. Console: {console}"
        )
        assert hits[0] < i_backup < hits[1], (
            f"{self.backup_defect_marker} occurrences {hits} do not straddle the "
            f"backup read@{i_backup}: the two rejections are not one per slot. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-REVOKED: %s at lines %s, one before and one after the backup "
            "read@%d -- both manifests were refused by bit %d",
            self.backup_defect_marker, hits, i_backup, self._REVOKED_SLOT,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        for marker in (self._PUBK_SEL_ECHO, self._REVOKE_ECHO):
            n = sum(1 for line in console if marker in line)
            assert n == 2, (
                f"{marker} appeared {n} times, expected exactly 2 (one per manifest "
                f"slot): the revocation verdicts cannot be attributed to ROM slot "
                f"{self._REVOKED_SLOT} under a 0x{self._REVOKE_BITMAP:x} bitmap. "
                f"Console: {console}"
            )
        # The base checks only the first CRYPTO_FAIL=, which is the primary's; require one per slot.
        crypto_fail = f"CRYPTO_FAIL=0x{self.expected_error:08x}"
        i_backup = next((i for i, line in enumerate(console)
                         if f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}" in line),
                        -1)
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

        assert any("MANIFEST_ALL_FAILED" in line for line in console), (
            f"ROM never printed MANIFEST_ALL_FAILED (manifest_load.c:808): the "
            f"retry loop did not exhaust, so the run is not the both-slots-refused "
            f"outcome this member claims. Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-SLOTS-REFUSED: %s and %s each twice, %s at lines %s straddling "
            "the backup read@%d, then MANIFEST_ALL_FAILED",
            self._PUBK_SEL_ECHO, self._REVOKE_ECHO, crypto_fail, hits, i_backup,
        )

        # The console shows the address the ROM intended; the flash BFM shows what it served.
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
