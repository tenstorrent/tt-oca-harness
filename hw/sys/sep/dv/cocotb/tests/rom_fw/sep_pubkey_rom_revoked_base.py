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
(``PUBK_REVOKE=``) and its own revocation index (the revocation error code), all three
derived from its own ``_REVOKED_SLOT``, so a run of slot N cannot satisfy slot M's
checks. :meth:`check_efuse` additionally requires the fuse bitmap to be EXACTLY
this slot's bit, so a wider bitmap -- which could reject the manifest through a
slot the testcase did not select -- fails loudly instead of passing.

WHY REVOCATION IS THE ONLY POSSIBLE VERDICT, per slot. The signature path resolves the
selector, AUTHORIZES the key against the compiled-in digest table, consults the fuse
bitmap, and only then runs ``rsa_3072_verify``: a passing boot logs ``PUBK_SEL``,
``PUBK_AUTHORIZED``, ``PUBK_REVOKE``, ``RSA_EXEC`` in that order. ``key_digests.c``
populates all six slots, each with a different key.

Every member is therefore built to pass authorization: the backup slot is grafted from
the image signed by the key it names, so its modulus matches that slot's digest. Each
member would otherwise boot, which is what leaves revocation as the sole cause of the
rejection, with ``RSA_EXEC`` / ``RSA_VERIFY_OK`` pinning that the refusal lands before
the verifier and ``PUBK_UNAUTHORIZED`` pinning that the graft landed at all. On this
platform, therefore:

  * **every slot** establishes the strong property -- revocation refuses an
    otherwise fully valid, correctly signed, bootable image. Six signing keys ship
    and ``key_digests.c`` populates all six slots, so each member grafts in the
    backup slot of the image signed by the key it names (see
    :func:`select_backup_rom_slot`) rather than rewriting a selector and leaving
    the signature stale.

Revocation-first is the fail-closed order and is not a defect.

Slot 0 is not a case to avoid, and since the graft it is no longer the only member
whose backup manifest is valid in every other respect -- all six are. It is the
matched partner of ``sep_firmware_backup_rom_key_valid_test``, which applies
the IDENTICAL flash stimulus (:func:`select_backup_rom_slot` with slot 0, after the
same ``mm.break_magic`` failover trigger)
and differs only in leaving ``CHIPLET_PUBK_REVOKE`` clear -- fuse clear boots,
bit 0 set is refused, on the same bytes.

The fuse bit is the slot number, and the authority for that is the register map, not the
ROM's own header: ``CHIPLET_PUBK_REVOKE.select[7:0]`` is the ROM-key bitmap
(``regs/blocks/sep_efuse_map/sep_efuse_map.rdl:721-729``) and the ROM indexes it with
the manifest's key index directly. The fused-key slots do NOT continue that sequence --
they sit at bits 16 and above -- so nothing here may be derived by counting past slot 5.

No ``+esrc_noise_force`` on any member: revocation precedes the signature
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

_EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"

# A ROM classical key is named by its own bitmap slot number,
# so a ROM-slot selector is just the index.
PUBK_SEL_ROM_KEY = 0


def select_backup_rom_slot(buf: bytearray, slot_index: int) -> tuple[int, bool]:
    """Anchor the BACKUP slot on ROM key slot ``slot_index``, signature intact.

    Shared with ``sep_firmware_backup_rom_key_valid_test`` so that the positive case
    and the revoke-0 case apply the SAME stimulus to the SAME bytes by construction
    rather than through two copies that could drift apart. Both callers pair it with
    the standard ``mm.break_magic(buf, "primary")`` failover trigger, so with
    ``slot_index == 0`` the two produce byte-identical flash images and differ only in
    ``CHIPLET_PUBK_REVOKE``. Returns ``(encoded_selector, grafted)``.

    Slot 0 needs nothing: the shipped backup already selects it. Slots 1-5 graft in
    the backup slot of the per-slot image signed by that key
    (``mm.rom_key_image``), which moves manifest and payload as a unit and leaves the
    slot signed by the key its selector now names.

    That makes every member the strict case. Rewriting the selector field in place --
    what this did before the per-slot images existed -- left the signature stale for
    slots 1-5, so those members could only show that revocation preempts a stale
    signature. The mirror of ``select_primary_rom_slot``; see it for the rest.
    """
    grafted = slot_index != 0
    if grafted:
        mm.graft_slot(buf, mm.rom_key_image(slot_index).read_bytes(), "backup")

    got = mm.get_public_key_sel(buf, "backup")
    expected = slot_index & 0xF
    assert got == expected, (
        f"backup public_key_sel is 0x{got:04x}, expected 0x{expected:04x}: the "
        f"{'grafted' if grafted else 'shipped'} backup slot does not select ROM key "
        f"{slot_index}, so this testcase would revoke a slot it never named"
    )
    # Selector and modulus agree after the graft, so resolving the selector is the
    # right check and needs no override -- and it is what separates an authorized
    # manifest the fuse refuses from one the ROM would have refused anyway.
    mm.verify_public_key(buf, "backup")
    # Fully sealed, every slot: payload hash, TOC digests, manifest_hash over the TBS
    # and a signature that verifies under the key the slot carries.
    pm.verify_sealed(buf, "backup")
    return got, grafted


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
    # Every other arm of the signature path, so the KEY_REVOKED verdict cannot be
    # confused with one of them, plus proof the modulus never reached the
    # verifier. PUBK_SLOT_UNPROVISIONED is load-bearing for slots 1-5 (they ARE empty, so
    # seeing it would mean the digest table was consulted before the fuse bitmap);
    # RSA_EXEC and RSA_VERIFY_OK are load-bearing for slot 0 (its manifest is
    # otherwise valid, so without them a revocation that did nothing would boot).
    extra_forbidden = (
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_UNAUTHORIZED",
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "PUBK_SLOT_RESERVED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_OTP_EMPTY",
        "PUBK_ALGO_UNSUPPORTED",
    )

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
            f"separate PUBK_SLOT_RESERVED arm, not a "
            f"revocation testcase"
        )
        cls._REVOKE_BITMAP = 1 << slot
        # public_key_select is a 128-bit bitmap, so the slot IS the bit position.
        cls._PUBK_SEL_VALUE = slot
        cls.backup_defect_marker = f"MANIFEST_ERR=0x{MANIFEST_ERR_KEY_REVOKED:08x}"
        # The fuse word and the selector the ROM actually read, echoed back.
        cls._REVOKE_ECHO = f"PUBK_REVOKE=0x{cls._REVOKE_BITMAP:08x}"
        cls._PUBK_SEL_ECHO = f"PUBK_SEL=0x{cls._PUBK_SEL_VALUE:08x}"
        cls.efuse_preload = _EFUSE_DIR / f"sep_efuse_lc_prod_pubk_revoke{slot}.toml"

    # --- stimulus ----------------------------------------------------------
    def corrupt_backup(self, buf: bytearray) -> None:
        got, grafted = select_backup_rom_slot(buf, self._REVOKED_SLOT)
        # Pin WHICH branch this member must take, so the family cannot silently
        # degrade. The shipped backup selects ROM slot 0, so slot 0 must need no graft
        # and every other slot must need one. If the packer's backup selector ever
        # moved off 0, member 0 would otherwise start grafting over a slot that was
        # already anchored elsewhere, with nothing failing.
        expect_grafted = self._REVOKED_SLOT != 0
        assert grafted == expect_grafted, (
            f"slot {self._REVOKED_SLOT}: backup grafted={grafted}, expected "
            f"{expect_grafted}. The shipped backup manifest no longer selects ROM "
            f"slot 0 (configs/oca_secure_boot_test.yaml), so this member is no longer "
            f"testing what its docstring claims"
        )
        self.logger.info(
            "CHK-STIMULUS-REVOKED-SLOT: backup public_key_sel=0x%04x (ROM key slot "
            "%d, revoked by CHIPLET_PUBK_REVOKE bit %d); backup manifest %s, and fully "
            "sealed either way -- authorized, valid, and refused only by the fuse",
            got,
            self._REVOKED_SLOT,
            self._REVOKED_SLOT,
            f"grafted from {mm.rom_key_image(self._REVOKED_SLOT).name}"
            if grafted
            else "the shipped slot, untouched",
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
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
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
            self._PUBK_SEL_ECHO,
            self._REVOKE_ECHO,
            self._REVOKED_SLOT,
        )
