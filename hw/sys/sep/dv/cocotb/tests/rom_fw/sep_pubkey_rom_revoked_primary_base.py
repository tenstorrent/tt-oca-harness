# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Parameterised family: the primary manifest selects a revoked ROM key slot.

Six testcases (``sep_firmware_primary_pubkey_rom_{0..5}_revoked_key_test``) differ by
one integer -- the ROM public-key slot the primary selects, which is also the
``CHIPLET_PUBK_REVOKE`` bit that revokes it. The stimulus, the per-slot derivations
and the revocation assertions live here; each member sets ``_REVOKED_SLOT = N``.

The outcome shape is not uniform, which is why there are two bases. The shipped image
gives both slots ROM key index 0, so one revoke bit refuses one manifest or two:

  * slot 0 is terminal -- the bit refuses the primary AND the backup, the retry loop
    exhausts, and the run ends in ``MANIFEST_ALL_FAILED``;
  * slots 1-5 fail over and boot -- only the primary selects the revoked slot, the
    backup still selects unrevoked slot 0.

Which branch a member takes is measured, not written down. :meth:`_assert_outcome_shape`
reads the backup's selector out of the mutated buffer, so the split is pinned to its
actual cause -- both slots naming one ROM key -- rather than to ``slot == 0``. If the
packer ever gave the backup a different index, slot 0 would stop being terminal and
the terminal member would fail loudly rather than assert the wrong shape.

``PUBK_REVOKE=`` is the whole fuse word, echoed before this slot's bit is tested, so
every slot attempt that reaches the revocation check prints the same bitmap whether or
not it is revoked. The per-slot discriminator is the ``MANIFEST_ERR=`` code. On the
failover members the fuse echo therefore appears twice, and it is the second one,
after the backup read, that shows the booting slot ran the check and was allowed
through -- a ``PUBK_REVOKE=0x00000000`` from the backup would be wrong.
:meth:`check_efuse` additionally requires the bitmap to be exactly this slot's bit, so
a wider bitmap -- which could reject a manifest through a slot the testcase did not
select -- fails loudly.

The ROM authorizes a key BEFORE it consults the revocation bitmap, and both run before
the verifier: a passing boot logs ``PUBK_SEL``, ``PUBK_AUTHORIZED``, ``PUBK_REVOKE``,
then ``RSA_EXEC``. Every member is therefore built so that authorization SUCCEEDS --
the slot under test is grafted from the image signed by the key it names, so its
modulus matches the digest ``key_digests.c`` holds for that slot. Consequently:

  * every member would otherwise boot, because the manifest it reads is genuinely
    valid and genuinely authorized, so revocation is the sole cause of the rejection;
  * ``PUBK_UNAUTHORIZED`` is the load-bearing forbid -- it would mean the graft did not
    land and the slot was refused for its key rather than for the fuse -- and
    ``RSA_EXEC`` / ``RSA_VERIFY_OK`` pin that the refusal precedes the verifier.

Every member carries the same weight. Six signing keys ship and ``key_digests.c``
populates all six slots, so each member grafts in the primary slot of the image signed
by the key it names (:func:`select_primary_rom_slot`): the manifest the ROM reads is
authorized and fully sealed, and only the fuse bit refuses it. The family forbids
``RSA_EXEC`` on the primary to establish that the refusal lands before the verifier
rather than assume it.

The fuse bit is the slot number, and the authority is the register map rather than the
ROM's own header: ``CHIPLET_PUBK_REVOKE.select[7:0]`` is the ROM-key bitmap
(``regs/blocks/sep_efuse_map/sep_efuse_map.rdl:721-729``). The fused-key slots do NOT
continue that sequence -- they sit at bits 16 and above -- so nothing here may be
derived by counting past slot 5.

Every member runs a committed PROD preload, and both bases assert ``lc_raw() == 0x1``
and ``SBOOT_DIS == 0``, so the crypto chain cannot be opted out of by a manifest flag
and the revocation verdict is reached on the production path.

Entropy: slots 1-5 need ``+esrc_noise_force`` because their backup is valid and runs a
real RSA-3072 modexp. Slot 0 must not have it -- no slot reaches the verifier there,
and the member forbids ``RSA_EXEC`` to say so. Withholding it is a second, independent
guard: a ROM that did reach the verifier would stall in UrndRefresh rather than pass.
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

_EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"

# A ROM classical key is named by its own bitmap slot number.
PUBK_SEL_ROM_KEY = 0

_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"


def select_primary_rom_slot(buf: bytearray, slot_index: int) -> tuple[int, bool]:
    """Anchor the PRIMARY slot on ROM key slot ``slot_index``, signature intact.

    The mirror of ``sep_pubkey_rom_revoked_base.select_backup_rom_slot``, and shared
    with ``sep_firmware_primary_rom_key_valid_test`` so that the positive case and the
    revoke-0 case apply the SAME stimulus to the SAME bytes by construction rather
    than through two copies that could drift apart. Returns
    ``(encoded_selector, grafted)``.

    Slot 0 needs nothing: the shipped primary already selects it, so the buffer is the
    shipped image byte for byte. Slots 1-5 graft in the primary slot of the per-slot
    image signed by that key (``mm.rom_key_image``), which replaces manifest and
    payload as a unit and leaves the slot signed by the key its selector now names.

    That is what makes every member of this family the strict case. Rewriting the
    selector field in place -- what this did before the per-slot images existed --
    left the signature stale for slots 1-5, so those members could only show that
    revocation preempts a stale signature. Grafting leaves a manifest that is
    genuinely valid and genuinely authorized, and the only thing standing between it
    and a boot is the fuse bit. ``grafted`` is returned so the caller can pin which
    branch it took.
    """
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
    # The modulus must be the key the selector names -- which is the whole point of
    # the graft, and is what distinguishes an authorized-then-revoked manifest from
    # one the ROM would have refused anyway. No key_slot override: after the graft the
    # selector and the modulus agree, so resolving the selector is correct.
    mm.verify_public_key(buf, "primary")
    # Fully sealed, every slot, not just slot 0: payload hash, TOC digests,
    # manifest_hash over the signed region, and a signature that verifies under the key the
    # slot carries. If this fails the graft landed wrong and the run would refuse the
    # manifest for a reason this testcase is not about.
    pm.verify_sealed(buf, "primary")
    return got, grafted


class _primary_revoked_slot_mixin:
    """Per-slot derivations shared by both outcome shapes of the family.

    Subclasses set ``_REVOKED_SLOT`` and nothing else. Everything a member needs is
    derived from it in :meth:`__init_subclass__`, so the per-slot values are real
    class attributes -- greppable, and visible in the run log -- rather than hidden
    inside a method.
    """

    # Set by every concrete member. -1 makes an unset subclass fail immediately
    # instead of silently testing slot 0.
    _REVOKED_SLOT: int = -1

    # Derived; see __init_subclass__.
    _REVOKE_BITMAP: int = 0
    _PUBK_SEL_VALUE: int = 0
    _PUBK_SEL_ECHO: str = ""
    _REVOKE_ECHO: str = ""
    _KEY_REVOKED_ECHO: str = ""

    # True when the backup is expected to be refused by the same fuse bit, i.e.
    # the run is terminal. Set by the concrete base, checked against the image.
    _BACKUP_ALSO_REVOKED: bool = False

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        slot = cls._REVOKED_SLOT
        if slot < 0:
            # An intermediate base that has not chosen a slot yet is allowed; the
            # run-time asserts below catch it if it is ever executed.
            return
        assert 0 <= slot < mm.PUBK_SEL_NUM_ROM_KEYS, (
            f"{cls.__name__}: _REVOKED_SLOT {slot} is outside the ROM key table "
            f"[0, {mm.PUBK_SEL_NUM_ROM_KEYS}); an out-of-range index is the "
            f"separate PUBK_SLOT_RESERVED arm, not a "
            f"revocation testcase"
        )
        cls._REVOKE_BITMAP = 1 << slot
        cls._PUBK_SEL_VALUE = slot & 0xF
        cls._KEY_REVOKED_ECHO = f"MANIFEST_ERR=0x{MANIFEST_ERR_KEY_REVOKED:08x}"
        #  -- the fuse word and the selector the ROM
        # actually read, echoed back.
        cls._REVOKE_ECHO = f"PUBK_REVOKE=0x{cls._REVOKE_BITMAP:08x}"
        cls._PUBK_SEL_ECHO = f"PUBK_SEL=0x{cls._PUBK_SEL_VALUE:08x}"
        cls.efuse_preload = _EFUSE_DIR / f"sep_efuse_lc_prod_pubk_revoke{slot}.toml"

    # --- stimulus ----------------------------------------------------------
    def _plant_revoked_selector(self, buf: bytearray) -> None:
        got, grafted = select_primary_rom_slot(buf, self._REVOKED_SLOT)
        # Pin WHICH branch this member takes, so the family cannot silently degrade.
        # The shipped primary selects ROM slot 0, so slot 0 must need no graft and
        # every other slot must need one.
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
        """Tie the member's chosen outcome shape to the image that produces it.

        The family is terminal exactly when the BACKUP selects the revoked slot as
        well, because then one fuse bit refuses both manifests. Reading that out of
        the buffer -- rather than testing ``slot == 0`` -- means a packer change to
        the backup's ``rom_key_index`` breaks the member loudly instead of leaving
        it asserting the wrong shape.
        """
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
            f"(configs/secure_boot_test.yaml:43-45 and :112-114); that is no longer "
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
    """Slots 1-5: the primary selects a revoked slot, the backup boots.

    The backup still selects unrevoked ROM slot 0, so the run completes rather
    than ending terminally.
    """

    _BACKUP_ALSO_REVOKED = False

    primary_expected_error = MANIFEST_ERR_KEY_REVOKED
    # Revocation precedes rsa_3072_verify, so
    # the primary must never drive the verifier.
    primary_expected_rsa_starts = 0
    # Every other rejecting arm of the signature path, so the KEY_REVOKED verdict
    # cannot be confused with one of them. PUBK_UNAUTHORIZED is the load-bearing one:
    # the ROM authorizes before it consults the revocation bitmap, so seeing it would
    # mean the graft did not land and the slot was refused for its key rather than for
    # the fuse. PUBK_SLOT_UNPROVISIONED sits beside it to catch the digest table
    # shrinking back under this family. RSA_PKCS1_FAIL must not appear either -- the
    # backup is valid, so the only verifier run in this scenario succeeds.
    extra_forbidden = (
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_UNAUTHORIZED",
        "PUBK_SLOT_RESERVED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_OTP_EMPTY",
        "PUBK_ALGO_UNSUPPORTED",
        "RSA_PKCS1_FAIL",
    )
    # The backup's own selector, so "the backup booted" is tied to slot 0 rather
    # than to an unread selection. There is deliberately NO separate backup fuse
    # echo: the revocation check prints the whole 32-bit fuse WORD
    # unconditionally and only then tests this
    # slot's bit, so BOTH slot attempts print the same
    # ``PUBK_REVOKE=<bitmap>`` and the per-slot discriminator is
    # the revocation error code. Measured, not assumed: the slot-1 probe run
    # showed the backup echoing ``PUBK_REVOKE=0x00000002``.
    _BACKUP_SEL_ECHO = "PUBK_SEL=0x00000000"

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls._REVOKED_SLOT < 0:
            return
        # Class attributes, not instance ones: the base's marker assembly reads
        # primary_defect_marker through a classmethod, so an instance attribute set
        # in __init__ would be invisible to it and the required-marker tuple would
        # silently lose the defect token.
        cls.primary_defect_marker = cls._KEY_REVOKED_ECHO
        # The primary's selector, the shared fuse word, and the backup's selector.
        cls.extra_required = (cls._PUBK_SEL_ECHO, cls._REVOKE_ECHO, cls._BACKUP_SEL_ECHO)

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

        # The fuse word is read once per slot attempt, so exactly two echoes. This
        # is checked FIRST because the ordering assertions below index into the
        # list, and an empty list must fail as a readable assertion rather than an
        # IndexError.
        assert len(revokes) == 2, (
            f"{self._REVOKE_ECHO} appeared {len(revokes)} times at {revokes}, "
            f"expected exactly 2 -- the revocation check echoes the whole fuse word "
            f"once per slot attempt. Console: {console}"
        )

        # CHK-REVOKE-ATTRIBUTION: the ROM read THIS member's selector out of the
        # primary, consulted the fuse word, and refused THAT index -- in that
        # order, and all before the backup was read. Presence alone would be
        # satisfied by a backup-side echo or by another slot's bitmap, and then the
        # member's "slot N" claim would be unsupported. This is exactly the risk a
        # shared implementation introduces.
        assert 0 <= i_psrc < i_sel < revokes[0] < i_revoked < i_bsrc, (
            f"the revocation verdict is not attributable to the primary's slot "
            f"{self._REVOKED_SLOT}: primary@{i_psrc} -> {self._PUBK_SEL_ECHO}"
            f"@{i_sel} -> {self._REVOKE_ECHO}@{revokes} -> "
            f"{self._KEY_REVOKED_ECHO}@{i_revoked} -> backup@{i_bsrc}. "
            f"Console: {console}"
        )
        # The primary's selector and its revocation verdict are its own, exactly
        # once. The verdict is what discriminates the slots here -- not the fuse
        # echo, which both slots print identically.
        for marker in (self._PUBK_SEL_ECHO, self._KEY_REVOKED_ECHO):
            n = sum(1 for line in console if marker in line)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the primary's). "
                f"Console: {console}"
            )
        # The two fuse echoes must straddle the backup read. That is the assertion
        # that says the BACKUP also ran the revocation check and was PERMITTED -- it
        # consulted the same non-zero bitmap and produced no KEY_REVOKED of its own,
        # which is the whole reason this member fails over instead of terminating.
        assert revokes[0] < i_bsrc < revokes[1], (
            f"{self._REVOKE_ECHO} occurrences {revokes} do not straddle the backup "
            f"read@{i_bsrc}: the booting slot did not consult the revocation bitmap. "
            f"Console: {console}"
        )
        # And the backup's own selector, after the backup read, so the booting
        # slot's key selection is attributed rather than assumed.
        i_bsel = index_of(self._BACKUP_SEL_ECHO)
        assert i_bsrc < i_bsel < revokes[1], (
            f"the booting slot's key selection is unattributed: backup@{i_bsrc} -> "
            f"{self._BACKUP_SEL_ECHO}@{i_bsel} -> {self._REVOKE_ECHO}@{revokes[1]}. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-REVOKE-FAILOVER PASS: primary %s -> %s -> %s (slot %d refused once) -> "
            "backup %s -> %s again at line %d, permitted -> boot",
            self._PUBK_SEL_ECHO,
            self._REVOKE_ECHO,
            self._KEY_REVOKED_ECHO,
            self._REVOKED_SLOT,
            self._BACKUP_SEL_ECHO,
            self._REVOKE_ECHO,
            revokes[1],
        )


class sep_primary_pubkey_rom_revoked_terminal_base(
    _primary_revoked_slot_mixin, sep_backup_manifest_fail_base
):
    """Slot 0: one fuse bit refuses BOTH manifests, so the run is terminal.

    Both slots of the shipped image select ROM key 0, so this member plants no
    defect at all beyond confirming that selection: the flash image it runs is
    byte-identical to the shipped ``oca_secure_boot.bin``, and both manifests are
    provably sealed and bootable. The rejection therefore has exactly one cause.
    """

    _BACKUP_ALSO_REVOKED = True

    expected_error = MANIFEST_ERR_KEY_REVOKED
    primary_expected_error = MANIFEST_ERR_KEY_REVOKED
    # Every other rejecting arm of the signature path, plus proof the modulus never
    # reached the verifier. RSA_EXEC and RSA_VERIFY_OK are the load-bearing
    # forbids here: both manifests are otherwise valid, so without them a
    # revocation that did nothing would boot.
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

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls._REVOKED_SLOT >= 0:
            cls.backup_defect_marker = cls._KEY_REVOKED_ECHO

    # --- stimulus ----------------------------------------------------------
    def corrupt_primary(self, buf: bytearray) -> None:
        # NOT the base's default BAD_MAGIC trigger: the primary is the first slot
        # under test here and has to reach the signature path, exactly as the
        # reference's PRIMARY_PUBKEY_ROM_0_REVOKED_KEY modifies only
        # primary.manifest.public_key_sel.rom_key_index
        # (sep_firmware_secure_boot_test.py).
        self._plant_revoked_selector(buf)

    def corrupt_backup(self, buf: bytearray) -> None:
        # The backup carries no planted defect: it is refused by the same fuse bit
        # because the shipped image already points it at ROM slot 0. Assert that it
        # is untouched and provably bootable, so the terminal verdict cannot be
        # blamed on a damaged backup.
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

    # --- checks ------------------------------------------------------------
    def check_defect_attribution(self, console, i_backup: int) -> None:
        """Both slots print the marker, so the base's default is not applicable.

        The default requires the FIRST occurrence to follow the backup read, which
        would be false here and would also accept a run that never evaluated the
        backup. Instead: exactly two occurrences, one on each side of the backup
        read.
        """
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

        # The selector and the fuse word the ROM actually read, once per slot.
        # Without these the KEY_REVOKED verdicts could belong to some other slot
        # or some other bitmap.
        for marker in (self._PUBK_SEL_ECHO, self._REVOKE_ECHO):
            n = sum(1 for line in console if marker in line)
            assert n == 2, (
                f"{marker} appeared {n} times, expected exactly 2 (one per manifest "
                f"slot): the revocation verdicts cannot be attributed to ROM slot "
                f"{self._REVOKED_SLOT} under a 0x{self._REVOKE_BITMAP:x} bitmap. "
                f"Console: {console}"
            )
        # The terminal error code, once per slot. The shared base checks only that
        # MANIFEST_ERR= is PRESENT, and index_of() returns its FIRST occurrence --
        # which here is the primary's. So without this, "the run converged on
        # KEY_REVOKED" would rest on the primary's rejection alone and the backup's
        # own crypto verdict would be unasserted. Requiring two occurrences that
        # straddle the backup read attributes one to each slot.
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

        # CHK-ALL-SLOTS-EXHAUSTED: the retry loop ran out of slots, which is the
        # observable that distinguishes "both were refused" from "the ROM stopped
        # after the first". , reached only after the loop.
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

        # Device-side evidence: the console says which address the ROM INTENDED to
        # read; the BFM's transaction record says which address the device actually
        # served, and in what order. The base publishes the flash handle for
        # exactly this.
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
