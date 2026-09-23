# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Parameterised family: the BACKUP manifest selects a REVOKED ROM key slot.

Each member sets _REVOKED_SLOT. Slot 0 shows revocation refuses a valid image; slots 1-5
hold other keys' digests, so they prove only that revocation is checked first.
"""

from __future__ import annotations

from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_KEY_REVOKED,
    sep_backup_manifest_fail_base,
)

_EFUSE_DIR = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"
)

# public_key_sel is {index:4, selection:3}; ROM-key selection is 0, so selector == index.
PUBK_SEL_ROM_KEY = 0


def select_backup_rom_slot(buf: bytearray, slot_index: int) -> tuple[int, bool]:
    # Slot 0 is a no-op write on the shipped backup; any other slot makes the signature stale.
    base = mm.slot_base("backup")
    tbs_before = bytes(buf[base:base + mm.TBS_LEN])
    mm.set_public_key_sel(buf, "backup", selection=PUBK_SEL_ROM_KEY, index=slot_index)
    tbs_after = bytes(buf[base:base + mm.TBS_LEN])
    tbs_changed = tbs_before != tbs_after

    got = mm.get_public_key_sel(buf, "backup")
    expected = slot_index & 0xF
    assert got == expected, (
        f"backup public_key_sel encoded as 0x{got:04x}, expected 0x{expected:04x} "
        f"(selection=PUBK_SEL_ROM_KEY, index={slot_index})"
    )
    # The modulus is untouched, so the backup must still carry the dev0 key held in ROM slot 0.
    mm.verify_public_key(buf, "backup")
    if not tbs_changed:
        # Nothing signed moved, so the slot must still be fully sealed.
        pm.verify_sealed(buf, "backup")
    else:
        # If the signature still verifies, the selector write missed the TBS.
        n, e_pub, _d = pm.load_rsa_private_key()
        sig = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES])
        assert not pm.verify_pkcs1v15_sha256(tbs_after, sig, n, e_pub), (
            "backup signature still verifies after the selector was changed; the "
            "write did not land inside the TBS, so the ROM would read the original "
            "selector and this testcase would prove nothing about slot "
            f"{slot_index}"
        )
        mm.verify_layout(buf, "backup")
    return got, tbs_changed


class sep_pubkey_rom_revoked_base(sep_backup_manifest_fail_base):

    # Set by every member; -1 stops an unset subclass from silently testing slot 0.
    _REVOKED_SLOT: int = -1

    # Derived; see __init_subclass__.
    _REVOKE_BITMAP: int = 0
    _PUBK_SEL_VALUE: int = 0
    _PUBK_SEL_ECHO: str = ""
    _REVOKE_ECHO: str = ""

    expected_error = MANIFEST_ERR_KEY_REVOKED
    # Other validate_signature arms, and proof the ROM reached neither the digest table nor RSA.
    extra_forbidden = ("ROM_KEY_EMPTY", "PUBK_HASH_MISMATCH", "RSA_VERIFY_START",
                       "SIG_VALID", "CRYPTO_VALIDATE_OK", "BAD_KEY_IDX",
                       "BAD_KEY_SEL", "FUSE_KEY_EMPTY", "VERSION_ROLLBACK",
                       "BAD_SIG_TYPE=")

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        slot = cls._REVOKED_SLOT
        if slot < 0:
            # An intermediate subclass may leave the slot unset; run_scenario's asserts catch it.
            return
        assert 0 <= slot < mm.PUBK_SEL_NUM_ROM_KEYS, (
            f"{cls.__name__}: _REVOKED_SLOT {slot} is outside the ROM key table "
            f"[0, {mm.PUBK_SEL_NUM_ROM_KEYS}); an out-of-range index is the "
            f"separate BAD_KEY_IDX arm (manifest_crypto.c:174-177), not a "
            f"revocation testcase"
        )
        # Bits 0-5 revoke ROM key slots; fused-key slots start at bit 16, so stop at slot 5.
        cls._REVOKE_BITMAP = 1 << slot
        cls._PUBK_SEL_VALUE = slot & 0xF
        cls.backup_defect_marker = f"KEY_REVOKED idx=0x{slot:08x}"
        cls._REVOKE_ECHO = f"PUBK_REVOKE=0x{cls._REVOKE_BITMAP:08x}"
        cls._PUBK_SEL_ECHO = f"PUBK_SEL=0x{cls._PUBK_SEL_VALUE:08x}"
        cls.efuse_preload = _EFUSE_DIR / f"sep_efuse_lc_prod_pubk_revoke{slot}.toml"

    # --- stimulus ----------------------------------------------------------
    def corrupt_backup(self, buf: bytearray) -> None:
        got, tbs_changed = select_backup_rom_slot(buf, self._REVOKED_SLOT)
        # Slot 0 must stay a no-op write so it remains the fully sealed strict case.
        expect_changed = self._REVOKED_SLOT != 0
        assert tbs_changed == expect_changed, (
            f"slot {self._REVOKED_SLOT}: TBS changed={tbs_changed}, expected "
            f"{expect_changed}. The shipped backup manifest no longer selects ROM "
            f"slot 0 (configs/secure_boot_test.yaml:112-114), so this member is no "
            f"longer testing what its docstring claims"
        )
        self.logger.info(
            "CHK-STIMULUS-REVOKED-SLOT: backup public_key_sel=0x%04x (ROM key slot "
            "%d, revoked by CHIPLET_PUBK_REVOKE bit %d); TBS changed=%s, backup "
            "manifest %s",
            got, self._REVOKED_SLOT, self._REVOKED_SLOT, tbs_changed,
            "re-hashed, signature now stale" if tbs_changed
            else "untouched and still fully sealed with a valid dev0 signature",
        )

    def check_efuse(self, image) -> None:
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == self._REVOKE_BITMAP, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected "
            f"0x{self._REVOKE_BITMAP:x}: exactly bit {self._REVOKED_SLOT} must be "
            f"blown -- a wider bitmap could reject the manifest through a slot "
            f"this testcase did not select"
        )
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364 then :369) and would "
            f"terminate the run before revocation is reached"
        )

    # --- checks ------------------------------------------------------------
    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        # The selector and fuse word the ROM read tie KEY_REVOKED to this slot and bitmap.
        for marker in (self._PUBK_SEL_ECHO, self._REVOKE_ECHO):
            assert any(marker in line for line in console), (
                f"ROM never printed {marker}: the revocation verdict cannot be "
                f"attributed to ROM slot {self._REVOKED_SLOT} under a "
                f"0x{self._REVOKE_BITMAP:x} bitmap. Console: {console}"
            )
        # The primary dies at BAD_MAGIC before crypto, so only the backup reaches key selection.
        n_revoked = sum(1 for line in console if self.backup_defect_marker in line)
        assert n_revoked == 1, (
            f"{self.backup_defect_marker} appeared {n_revoked} times, expected "
            f"exactly 1 (the backup's). Console: {console}"
        )
        self.logger.info(
            "CHK-REVOKE-ECHO: ROM read %s and %s, and refused slot %d exactly once",
            self._PUBK_SEL_ECHO, self._REVOKE_ECHO, self._REVOKED_SLOT,
        )
