# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Parameterised family: the BACKUP manifest selects a REVOKED ROM key slot.

Six testcases (``sep_firmware_backup_pubkey_rom_{0..5}_revoked_key_test``) differ
from one another by ONE integer -- the ROM public-key slot the backup selects and
the ``CHIPLET_PUBK_REVOKE`` bit that revokes it. The scenario, the assertions and
the eFuse preconditions live here once; each member is a module whose only
substantive line is ``_REVOKED_SLOT = N``. Writing six near-identical files would
mean six places for a future correction to be applied in five of them.

Parameterising the SCENARIO must not parameterise away the EVIDENCE. Every member
still asserts its own selector (``PUBK_SEL=``), its own fuse word
(``PUBK_REVOKE=``) and its own revocation index (``KEY_REVOKED idx=``), all three
derived from its own ``_REVOKED_SLOT``, so a run of slot N cannot satisfy slot M's
checks. :meth:`check_efuse` additionally requires the fuse bitmap to be EXACTLY
this slot's bit, so a wider bitmap -- which could reject the manifest through a
slot the testcase did not select -- fails loudly instead of passing.

WHY REVOCATION IS THE ONLY POSSIBLE VERDICT, PER SLOT. ``validate_signature``
consults the fuse bitmap (``manifest_crypto.c``) BEFORE the compiled-in digest
table and before ``rsa_3072_verify``. What ``key_digests.c`` holds for a slot
decides which forbidden marker is load-bearing for that member:

  * **slot 0** binds to the dev0 modulus the backup actually carries, so it would
    otherwise boot (``configs/secure_boot_test.yaml``); revocation is the sole
    cause of the rejection and ``RSA_VERIFY_START`` / ``SIG_VALID`` are the
    load-bearing forbids there;
  * **slots 1-5** hold another key's digest under ``TEST_BUILD``, so they would
    otherwise be rejected as ``PUBK_HASH_MISMATCH``.

**REVOCATION-FIRST IS WHAT SPLITS THIS FAMILY.** Because the fuse bitmap is read
before the digest bind, forbidding ``PUBK_HASH_MISMATCH`` is what pins the
ORDER: a ROM that consulted the digest table first would report it instead of
``KEY_REVOKED``, and the members for
slots 1-5 would fail. That order also decides how much each member proves:

  * **slot 0** establishes the strong property -- revocation refuses an otherwise
    fully valid, correctly signed, bootable image;
  * **slots 1-5** establish the weaker property that revocation PREEMPTS the
    digest arms, because only the dev0 signing key ships in this tree, so a
    slot-N selector cannot be re-bound to slot N's key
    (see :func:`select_backup_rom_slot`).

Revocation-first is the fail-closed order and is not a defect, but the narrowing
is why slot 0 carries this family's real weight.

Slot 0 is therefore the STRICTEST member of this family, not a case to avoid: it
is the only one whose backup manifest is valid in every other respect. It is also
the matched partner of ``sep_firmware_backup_rom_key_valid_test``, which applies
the IDENTICAL flash stimulus (:func:`select_backup_rom_slot` with slot 0, after the
same ``mm.set_identifier`` failover trigger)
and differs only in leaving ``CHIPLET_PUBK_REVOKE`` clear -- fuse clear boots,
bit 0 set is refused, on the same bytes.

THE FUSE BIT IS THE SLOT NUMBER, and the authority for that is the register map,
not the ROM's own header: ``CHIPLET_PUBK_REVOKE.select[7:0]`` is the ROM-key
bitmap (``sep_efuse_map.rdl``) and the ROM
indexes it with the manifest's key index directly (``manifest_crypto.c``).
The fused-key slots do NOT continue that sequence -- they sit at bits 16 and
above -- so nothing here may be derived by counting past slot 5.

No ``+sep_crypto_edn_force`` on any member: revocation precedes the signature
step, so OTBN is never driven.
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

# public_key_sel is {index:4, selection:3}; PUBK_SEL_ROM_KEY is 0 (manifest.h),
# so a ROM-slot selector is just the index.
PUBK_SEL_ROM_KEY = 0


def select_backup_rom_slot(buf: bytearray, slot_index: int) -> tuple[int, bool]:
    """Point the backup's ``public_key_sel`` at ROM key slot ``slot_index``.

    Shared with ``sep_firmware_backup_rom_key_valid_test`` so that the positive
    case and the revoke-0 case apply the SAME stimulus to the SAME bytes by
    construction rather than through two copies that could drift apart. Both
    callers pair it with the standard ``mm.set_identifier(buf, "primary")``
    failover trigger, so with ``slot_index == 0`` the two produce byte-identical
    flash images and differ only in ``CHIPLET_PUBK_REVOKE``. Returns
    ``(encoded_selector, tbs_changed)``.

    ``tbs_changed`` is what the caller asserts the consequences of, and it is
    measured rather than assumed. The shipped backup already selects ROM slot 0
    (``configs/secure_boot_test.yaml``), so for slot 0 the write is a
    no-op: the TBS is untouched, the manifest stays fully sealed and its dev0
    signature stays valid. For slots 1-5 the write changes the TBS, so
    ``manifest_hash`` is recomputed and the signature goes stale -- which is
    harmless only because revocation is reached first, and the family forbids
    ``RSA_VERIFY_START`` to prove that rather than assume it.
    """
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
    # The modulus is never touched by this stimulus, so the backup must still
    # carry the dev0 key the ROM has in slot 0. verify_public_key() also proves
    # OFF_PUBLIC_KEY still addresses the modulus, so a packer change turns into a
    # loud failure here rather than a negative test passing for the wrong reason.
    mm.verify_public_key(buf, "backup")
    if not tbs_changed:
        # Nothing in the signed region moved, so the slot must still be completely
        # sealed: payload hash, TOC digests, manifest hash and a dev0 signature
        # that verifies. This is the assertion that makes slot 0 the strict case
        # -- the manifest is provably valid and only the fuse refuses it.
        pm.verify_sealed(buf, "backup")
    else:
        # The selector write invalidated the signature. Assert that too: if the
        # signature somehow still verified, the write did not land in the TBS and
        # the selector under test is not the one the ROM will read.
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
    """Primary fails over -> backup selects revoked ROM slot N -> terminal.

    Subclasses set ``_REVOKED_SLOT`` and nothing else. Everything a member needs
    is derived from it in :meth:`__init_subclass__`, so the per-slot values are
    real class attributes -- greppable, and visible in the run log -- rather than
    hidden inside a method.
    """

    # Set by every concrete member. -1 makes an unset subclass fail immediately
    # instead of silently testing slot 0.
    _REVOKED_SLOT: int = -1

    # Derived; see __init_subclass__.
    _REVOKE_BITMAP: int = 0
    _PUBK_SEL_VALUE: int = 0
    _PUBK_SEL_ECHO: str = ""
    _REVOKE_ECHO: str = ""

    expected_error = MANIFEST_ERR_KEY_REVOKED
    # Every other arm of validate_signature, so the KEY_REVOKED verdict cannot be
    # confused with one of them, plus proof the modulus never reached the
    # verifier. PUBK_HASH_MISMATCH is load-bearing for slots 1-5: seeing it would
    # mean the digest table was consulted before the fuse bitmap. RSA_VERIFY_START
    # and SIG_VALID are load-bearing for slot 0, whose manifest is otherwise
    # valid, so without them a revocation that did nothing would boot.
    # ROM_KEY_EMPTY cannot occur -- every slot has a digest -- and is forbidden
    # only so a table that lost an entry fails here instead of silently.
    extra_forbidden = ("ROM_KEY_EMPTY", "PUBK_HASH_MISMATCH", "RSA_VERIFY_START",
                       "SIG_VALID", "CRYPTO_VALIDATE_OK", "BAD_KEY_IDX",
                       "BAD_KEY_SEL", "FUSE_KEY_EMPTY", "VERSION_ROLLBACK",
                       "BAD_SIG_TYPE=")

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        slot = cls._REVOKED_SLOT
        if slot < 0:
            # An intermediate subclass that has not chosen a slot yet is allowed;
            # run_scenario's own asserts catch it if it is ever executed.
            return
        assert 0 <= slot < mm.PUBK_SEL_NUM_ROM_KEYS, (
            f"{cls.__name__}: _REVOKED_SLOT {slot} is outside the ROM key table "
            f"[0, {mm.PUBK_SEL_NUM_ROM_KEYS}); an out-of-range index is the "
            f"separate BAD_KEY_IDX arm (manifest_crypto.c:174-177), not a "
            f"revocation testcase"
        )
        cls._REVOKE_BITMAP = 1 << slot
        cls._PUBK_SEL_VALUE = slot & 0xF
        # manifest_crypto.c -- simputshex32("KEY_REVOKED idx=", index).
        cls.backup_defect_marker = f"KEY_REVOKED idx=0x{slot:08x}"
        # manifest_crypto.c -- the fuse word and the selector the ROM
        # actually read, echoed back.
        cls._REVOKE_ECHO = f"PUBK_REVOKE=0x{cls._REVOKE_BITMAP:08x}"
        cls._PUBK_SEL_ECHO = f"PUBK_SEL=0x{cls._PUBK_SEL_VALUE:08x}"
        cls.efuse_preload = _EFUSE_DIR / f"sep_efuse_lc_prod_pubk_revoke{slot}.toml"

    # --- stimulus ----------------------------------------------------------
    def corrupt_backup(self, buf: bytearray) -> None:
        got, tbs_changed = select_backup_rom_slot(buf, self._REVOKED_SLOT)
        # Pin WHICH branch this member must take, so the family cannot silently
        # degrade. The shipped backup selects ROM slot 0, so slot 0 must be the
        # no-op write (leaving a fully sealed manifest, the strict case) and every
        # other slot must be a real TBS change. If the packer's backup
        # `rom_key_index` ever moved off 0, member 0 would otherwise slide onto the
        # weaker stale-signature branch and lose its "strictest member" status with
        # nothing failing -- which is exactly the silent-weakening class this
        # family's shared implementation could introduce.
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
        # The selector and the fuse word the ROM actually read. Without these the
        # KEY_REVOKED verdict could belong to some other slot or some other
        # bitmap, and this member's "slot N" claim would be unsupported -- which
        # is exactly the risk a shared implementation introduces.
        for marker in (self._PUBK_SEL_ECHO, self._REVOKE_ECHO):
            assert any(marker in line for line in console), (
                f"ROM never printed {marker}: the revocation verdict cannot be "
                f"attributed to ROM slot {self._REVOKED_SLOT} under a "
                f"0x{self._REVOKE_BITMAP:x} bitmap. Console: {console}"
            )
        # Exactly once: the primary dies at BAD_MAGIC before any crypto runs, so a
        # second occurrence would mean a slot this testcase did not account for
        # also reached key selection.
        n_revoked = sum(1 for line in console if self.backup_defect_marker in line)
        assert n_revoked == 1, (
            f"{self.backup_defect_marker} appeared {n_revoked} times, expected "
            f"exactly 1 (the backup's). Console: {console}"
        )
        self.logger.info(
            "CHK-REVOKE-ECHO: ROM read %s and %s, and refused slot %d exactly once",
            self._PUBK_SEL_ECHO, self._REVOKE_ECHO, self._REVOKED_SLOT,
        )
