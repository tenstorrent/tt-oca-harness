# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Parameterised family: the primary manifest selects a revoked ROM key slot.

Both shipped slots select ROM key 0: revoking slot 0 refuses both manifests (terminal),
revoking slots 1-5 refuses only the primary. Fused-key revoke bits start at bit 16, so
no bit here may be derived by counting past slot 5.
"""

from __future__ import annotations

from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_KEY_REVOKED,
    sep_backup_manifest_fail_base,
)
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

_EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"

PUBK_SEL_ROM_KEY = 0


def select_primary_rom_slot(buf: bytearray, slot_index: int) -> tuple[int, bool]:
    grafted = slot_index != 0
    if grafted:
        mm.graft_slot(buf, mm.rom_key_image(slot_index).read_bytes(), "primary")

    got = mm.get_public_key_sel(buf, "primary")
    expected = slot_index & 0xF
    assert got == expected, (
        f"primary public_key_sel is 0x{got:04x}, expected 0x{expected:04x}: the "
        f"{'grafted' if grafted else 'shipped'} primary slot does not select ROM key "
        f"{slot_index}, so this testcase would revoke a slot it never named"
    )
    # A modulus the selector does not name is refused for its key, not for the fuse.
    mm.verify_public_key(buf, "primary")
    pm.verify_sealed(buf, "primary")
    return got, grafted


class _primary_revoked_slot_mixin:
    _REVOKED_SLOT: int = -1

    _REVOKE_BITMAP: int = 0
    _PUBK_SEL_VALUE: int = 0
    _PUBK_SEL_ECHO: str = ""
    _REVOKE_ECHO: str = ""
    _KEY_REVOKED_ECHO: str = ""

    _BACKUP_ALSO_REVOKED: bool = False

    def __init_subclass__(cls, **kwargs) -> None:
        # Derive before super(): a base hook later in the MRO validates these at import.
        if cls._REVOKED_SLOT >= 0:
            cls._derive_slot_fields()
            cls._derive_member_fields()
        super().__init_subclass__(**kwargs)

    @classmethod
    def _derive_member_fields(cls) -> None:
        pass

    @classmethod
    def _derive_slot_fields(cls) -> None:
        slot = cls._REVOKED_SLOT
        assert 0 <= slot < mm.PUBK_SEL_NUM_ROM_KEYS, (
            f"{cls.__name__}: _REVOKED_SLOT {slot} is outside the ROM key table "
            f"[0, {mm.PUBK_SEL_NUM_ROM_KEYS}); an out-of-range index is the "
            f"separate PUBK_SLOT_RESERVED arm, not a "
            f"revocation testcase"
        )
        cls._REVOKE_BITMAP = 1 << slot
        cls._PUBK_SEL_VALUE = slot & 0xF
        cls._KEY_REVOKED_ECHO = f"MANIFEST_ERR=0x{MANIFEST_ERR_KEY_REVOKED:08x}"
        cls._REVOKE_ECHO = f"PUBK_REVOKE=0x{cls._REVOKE_BITMAP:08x}"
        cls._PUBK_SEL_ECHO = f"PUBK_SEL=0x{cls._PUBK_SEL_VALUE:08x}"
        cls.efuse_preload = _EFUSE_DIR / f"sep_efuse_lc_prod_pubk_revoke{slot}.toml"

    def _plant_revoked_selector(self, buf: bytearray) -> None:
        got, grafted = select_primary_rom_slot(buf, self._REVOKED_SLOT)
        expect_grafted = self._REVOKED_SLOT != 0
        assert grafted == expect_grafted, (
            f"slot {self._REVOKED_SLOT}: primary grafted={grafted}, expected "
            f"{expect_grafted}. The shipped primary manifest no longer selects ROM "
            f"slot 0 (configs/oca_secure_boot_test.yaml), so this member is no longer "
            f"testing what its docstring claims"
        )
        self._assert_outcome_shape(buf)
        self.logger.info(
            "CHK-STIMULUS-REVOKED-SLOT PASS: primary public_key_sel=0x%04x (ROM key slot "
            "%d, revoked by CHIPLET_PUBK_REVOKE bit %d); primary manifest %s, and "
            "fully sealed either way -- authorized, valid, and refused only by the fuse",
            got,
            self._REVOKED_SLOT,
            self._REVOKED_SLOT,
            f"grafted from {mm.rom_key_image(self._REVOKED_SLOT).name}"
            if grafted
            else "the shipped slot, untouched",
        )

    def _assert_outcome_shape(self, buf: bytearray) -> None:
        backup_sel = mm.get_public_key_sel(buf, "backup")
        backup_revoked = (
            bool(self._REVOKE_BITMAP & (1 << (backup_sel & 0xF)))
            and ((backup_sel >> 4) & 0x7) == PUBK_SEL_ROM_KEY
        )
        assert backup_revoked == self._BACKUP_ALSO_REVOKED, (
            f"slot {self._REVOKED_SLOT}: the backup selector is 0x{backup_sel:04x}, "
            f"so 'the backup is refused by the same fuse bit' is {backup_revoked}, "
            f"but this member is built on the "
            f"{'TERMINAL' if self._BACKUP_ALSO_REVOKED else 'FAILOVER'} base which "
            f"requires {self._BACKUP_ALSO_REVOKED}. The outcome shape of this family "
            f"depends on both slots naming ROM key 0 "
            f"(configs/oca_secure_boot_test.yaml); that is no longer "
            f"true, so the member's expected outcome is wrong"
        )
        self.logger.info(
            "CHK-STIMULUS-OUTCOME-SHAPE: backup selector 0x%04x, refused by bitmap "
            "0x%x = %s -> %s expected",
            backup_sel,
            self._REVOKE_BITMAP,
            backup_revoked,
            "TERMINAL" if backup_revoked else "FAILOVER",
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
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
        )


class sep_primary_pubkey_rom_revoked_failover_base(
    _primary_revoked_slot_mixin, sep_primary_fail_backup_boot_base
):
    _BACKUP_ALSO_REVOKED = False

    primary_expected_error = MANIFEST_ERR_KEY_REVOKED
    # Revocation precedes rsa_3072_verify, so the primary must never drive the verifier.
    primary_expected_rsa_starts = 0
    # PUBK_UNAUTHORIZED would mean the key, not the fuse, refused the grafted slot.
    extra_forbidden = (
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_UNAUTHORIZED",
        "PUBK_SLOT_RESERVED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_OTP_EMPTY",
        "PUBK_ALGO_UNSUPPORTED",
        "RSA_PKCS1_FAIL",
    )
    # Both attempts echo the same whole fuse word; only the error code is per slot.
    _BACKUP_SEL_ECHO = "PUBK_SEL=0x00000000"

    @classmethod
    def _derive_member_fields(cls) -> None:
        cls.primary_defect_marker = cls._KEY_REVOKED_ECHO
        cls.primary_ordered = (cls._PUBK_SEL_ECHO, "PUBK_AUTHORIZED", cls._REVOKE_ECHO)
        cls.primary_absent = ("FUSE_VER=", "MANIFEST_OK")
        cls.extra_required = (cls._PUBK_SEL_ECHO, cls._REVOKE_ECHO, cls._BACKUP_SEL_ECHO)

    def corrupt_primary(self, buf: bytearray) -> None:
        self._plant_revoked_selector(buf)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        primary, backup = oc.split_attempts(console)

        tail = [line for _, line in primary.markers][-2:]
        assert oc.count(tail[:1], self._REVOKE_ECHO) == 1, (
            f"the line before {self._KEY_REVOKED_ECHO} is not {self._REVOKE_ECHO} "
            f"(primary attempt ends {tail}): the refusal is not the revocation check's"
        )
        b_ordered = (
            self._BACKUP_SEL_ECHO,
            "PUBK_AUTHORIZED",
            self._REVOKE_ECHO,
            "RSA_EXEC",
            "RSA_VERIFY_OK",
            "MANIFEST_OK",
            "PAYLOAD_OK",
        )
        oc.assert_attempt(
            backup,
            error=None,
            stage="accepted",
            ordered=b_ordered,
            absent=(self._KEY_REVOKED_ECHO, self._PUBK_SEL_ECHO),
        )
        # The fuse word is echoed once per slot attempt; the selector and verdict are the primary's.
        for marker, want_n in (
            (self._REVOKE_ECHO, 2),
            (self._PUBK_SEL_ECHO, 1),
            (self._KEY_REVOKED_ECHO, 1),
        ):
            n = oc.count(console, marker)
            assert n == want_n, (
                f"{marker} appeared {n} times, expected exactly {want_n}. Console: {console}"
            )
        self.logger.info(
            "CHK-REVOKE-FAILOVER PASS: primary@%d-%d %s -> PUBK_AUTHORIZED -> %s -> %s "
            "(slot %d refused) -> backup@%d-%d %s",
            primary.first,
            primary.last,
            self._PUBK_SEL_ECHO,
            self._REVOKE_ECHO,
            self._KEY_REVOKED_ECHO,
            self._REVOKED_SLOT,
            backup.first,
            backup.last,
            " -> ".join(b_ordered),
        )


class sep_primary_pubkey_rom_revoked_terminal_base(
    _primary_revoked_slot_mixin, sep_backup_manifest_fail_base
):
    _BACKUP_ALSO_REVOKED = True

    expected_error = MANIFEST_ERR_KEY_REVOKED
    primary_expected_error = MANIFEST_ERR_KEY_REVOKED
    # Both manifests are otherwise valid, so a revocation that did nothing reaches RSA_EXEC.
    extra_forbidden = (
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_UNAUTHORIZED",
        "RSA_EXEC",
        "RSA_PKCS1_FAIL",
        "RSA_VERIFY_OK",
        "PUBK_SLOT_RESERVED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_OTP_EMPTY",
        "PUBK_ALGO_UNSUPPORTED",
    )

    @classmethod
    def _derive_member_fields(cls) -> None:
        cls.backup_defect_marker = cls._KEY_REVOKED_ECHO

    def corrupt_primary(self, buf: bytearray) -> None:
        # Not the base's BAD_MAGIC default: the primary must reach the signature path.
        self._plant_revoked_selector(buf)

    def corrupt_backup(self, buf: bytearray) -> None:
        # No planted defect: the shipped backup already selects the revoked ROM slot 0.
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
            "signed region and RSA verification of its shipped signature against the dev0 "
            "modulus, whose SHA-256 is the ROM's compiled-in slot-0 digest. Both "
            "manifests are genuinely bootable and one fuse bit refuses both",
            got,
        )

    def check_defect_attribution(self, console, i_backup: int) -> None:
        # Both slots print the marker, so require one on each side of the backup read.
        hits = [i for i, line in enumerate(console) if self.backup_defect_marker in line]
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
            self.backup_defect_marker,
            hits,
            i_backup,
            self._REVOKED_SLOT,
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
        # The base finds only the first MANIFEST_ERR=, the primary's; require one per slot.
        crypto_fail = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_backup = next(
            (
                i
                for i, line in enumerate(console)
                if f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}" in line
            ),
            -1,
        )
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
            f"ROM never printed MANIFEST_ALL_FAILED: the "
            f"retry loop did not exhaust, so the run is not the both-slots-refused "
            f"outcome this member claims. Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-SLOTS-REFUSED: %s and %s each twice, %s at lines %s straddling "
            "the backup read@%d, then MANIFEST_ALL_FAILED",
            self._PUBK_SEL_ECHO,
            self._REVOKE_ECHO,
            crypto_fail,
            hits,
            i_backup,
        )

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
            p_idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            b_idx,
            mm.BACKUP_MANIFEST_OFFSET,
        )
