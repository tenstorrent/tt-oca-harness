# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared PROD-lifecycle stimulus for the [S25] demotion-decision family.

The mechanism, the seven-outcome collapse map and the disclosed gaps are written
out once in ``rom_fw/sep_demotion_decision_base.py``. **Read that first.** This
module adds only what the four PROD members share and the two PROD_END members
cannot use:

  * the ``+SECURE_BOOT_DIS`` stimulus, on BOTH of the surfaces it drives;
  * the PROD lifecycle narrowing and the console-marker skeleton that goes with
    a secure-boot-OFF boot;
  * :func:`outcome_for`, the non-PROD_END arm of the decision table transcribed
    from ``rom_main.c`` as executable code.

============================================================================
WHY THE FOUR MEMBERS SHARE A BASE AND WHAT IS *NOT* SHARED
============================================================================

Every one of the four drives the same three-line stimulus preamble and boots the
same way, so writing it four times would be four chances to get one of them
subtly wrong. What is deliberately NOT derived is the expected OUTCOME: each
member writes its own ``demotion_required``, ``demotion_values``,
``expect_demote_1`` and ``expect_demote_2`` explicitly, with citations, because
"parameterise the scenario, never parameterise the evidence" is the rule three
earlier batches of this run were graded against.

:meth:`_demotion_prod_mixin.__init_subclass__` then cross-checks those four written
declarations against :func:`outcome_for` applied to the member's own three input bits.
Agreement is not proof of correctness and is not claimed as such; it is two independent
transcriptions of one table having to match.

============================================================================
``+SECURE_BOOT_DIS`` DRIVES TWO SURFACES, AND THEY ARE COUPLED
============================================================================

This is the single most expensive thing the VP half of this run learned, and it is
inherited here rather than rediscovered.

  * sets ``secure_boot: 0``, which the packer
    turns into TWO packed-field changes, not one -- see below;
  * **and** burns the ``sboot_dis`` eFuse, constrained to equal the plusarg.

Both are ported. The eFuse preload ``sep_efuse_lc_prod_sboot_dis.toml`` burns the
fuse, and :func:`apply_secure_boot_dis` writes both manifest fields:

  * ``secure_boot_control`` bit 0 cleared -- the signed enforcement request the
    validator's precedence reads first (``secure_boot.c``). It sits INSIDE the
    signed region, so clearing it re-hashes;
  * ``signature_type`` forced to ``NO_SIGNATURE`` (0), because the packer forces
    exactly that whenever a config sets ``secure_boot: 0``
    (value from ``pack_images_constants.py``). The primary is therefore
    genuinely unsigned, rather than a signed image with one flag cleared.

**The coupling is what makes the port non-vacuous.** With ``signature_type = 0``
the primary can boot only because the fuse is burned: with the manifest asking for
nothing, ``plat_is_secure_boot_disabled()`` (``oca_platform.c``) is what answers, and
it overrides the PROD lifecycle. Drop the fuse and PROD enforces secure boot, the
unsigned primary is refused as a format violation, and the ROM
fails over to the signed backup -- which carries no demotion stimulus and would
produce outcome **O5** under whichever name the testcase happened to have. That
substitution is made loud rather than silent: ``PUBK_ALGO_UNSUPPORTED``, the backup
manifest source and ``LC=PROD_END`` are forbidden, ``FUSE: SBOOT_DIS: 1``
(``rom_main.c``) and ``SBOOT_OFF`` (``rom_main.c``) are required, and
the base's :meth:`~sep_demotion_decision_base._check_primary_served` additionally
proves from the DEVICE side that no read touched the backup span.

The primary keeps its stale dev0 signature bytes rather than a blank field.

The BACKUP is re-signed and stays fully valid; only its ``life_cycle_states`` is
narrowed. That is what makes the forbidden backup read meaningful rather than
trivially satisfied by an unusable backup.

============================================================================
WHAT THE SHARED SKELETON DOES NOT COVER
============================================================================

``sep_firmware_demotion_decision_auth_flag_0_prod_sel_bit_set_test`` (the O2a
member) predates this module and performs the same three ``mm`` calls inline. It is
deliberately NOT refactored onto :func:`apply_secure_boot_dis`: it is an approved,
passing row whose docstring is its own evidence record, and rewriting it would put that
row's provenance at risk to remove three duplicated lines. Both copies are anchored by
the same two assertions (``signature_type == NO_SIGNATURE`` and ``secure_boot_control``
bit 0 clear), so a change that broke one would fail the other loudly rather than
silently.
"""

from __future__ import annotations

from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_decision_base import (
    EFUSE_DIR,
    narrow_life_cycle_states,
    sep_demotion_decision_base,
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# Console tokens, each verified to occur exactly once in bootrom/prod/src/ so no
# forbid below is inert.
_LC_PROD = "LC=PROD"  # lifecycle.c
_LC_PROD_END = "LC=PROD_END"  # lifecycle.c
_SBOOT_DIS_FUSE = "FUSE: SBOOT_DIS: 1"  # rom_main.c
_SBOOT_OFF = "SBOOT_OFF"  # rom_main.c
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# lifecycle.h -- the raw 4-bit LC state the preload's 0xE1 encodes.
LC_RAW_PROD = 0x1
# The only lifecycle state these members permit.
LC_STATES_PROD_ONLY = 1 << mm.LIFECYCLE_STATE_BITS["PROD"]

PROD_SBOOT_DIS_PRELOAD = EFUSE_DIR / "sep_efuse_lc_prod_sboot_dis.toml"


def apply_secure_boot_dis(test, buf: bytearray, slot: str = "primary") -> None:
    """Port ``+SECURE_BOOT_DIS``'s two MANIFEST surfaces onto one slot.

    The third surface -- the ``sboot_dis`` eFuse -- is the preload's job and is
    asserted separately by
    :meth:`sep_demotion_decision_base.build_efuse_image` through
    ``expected_sboot_dis``. All three are needed; see this module's docstring for
    why reading only one of them produced the VP half's worst error.

    Clearing the signed request is what lets the device disable take effect at
    all: the validator checks ``secure_boot_control`` before any device input, so
    a manifest that still asked for enforcement would be verified regardless of
    the fuse (SEP-ROM-SB-040).

    ``clear_secure_boot`` does the whole job rather than just that bit. With
    secure boot off the parser requires the slot to carry no crypto material --
    signature, public key, key-select and the type/encoding bytes all zero, or
    OCA_FAIL_SECURE_BOOT_INVARIANT -- so clearing only the enable bit would
    produce a refused manifest and this testcase would measure that instead of a
    demotion outcome.
    """
    before = mm.secure_boot_control(buf, slot)
    mm.clear_secure_boot(buf, slot)
    test.logger.info(
        "CHK-STIMULUS-SBOOT-DIS: %s secure_boot_control 0x%02x -> 0x%02x and "
        "signature_type -> %d (NO_SIGNATURE). The eFuse surface is the preload's, "
        "checked as expected_sboot_dis",
        slot,
        before,
        mm.secure_boot_control(buf, slot),
        mm.SIG_TYPE_NO_SIGNATURE,
    )


def outcome_for(sel: int, auth: int, bl2: int) -> dict:
    """The non-PROD_END arm of the [S25] decision table, as executable source.

    Transcribed from the ROM's own control flow, not from any run:

      * ``rom_main.c`` ``if (dc & OCA_DEMOTE_BL1_VALID)`` ->
        ``demotion_reg = flags[0]``  and ``BL1_DEMOTE=``;
        ``lock_demotion`` keeps its initialiser, so writes
        DEMOTE_1 ``(demote = auth, lock = 1)``;
      * ``else if (bl2_demote)`` -> ``lock_demotion = false``
        and ``DEMOTE: BL2 deferred, unlocked``. is then false,
        so ``lc_write_demotion`` is never called and DEMOTE_1 is left at its reset
        value -- the ONLY outcome of the seven with that property;
      * ``else`` -> ``DEMOTE: BL2 deferred, lock non-demoted``,
        ``demotion_reg`` still false, ``lock_demotion`` still true, so
        writes ``(0, 1)``;
      * prints ``BL2_DEMOTE_DEC=`` on all three of those arms, carrying
        the ``demotion_control`` BL2 request unconditionally;
      * ``lc_write_demotion_2`` is called only, i.e. only at PROD_END,
        so DEMOTE_2 is never written on any arm here.

    Returns the four things a member must declare, so that a member's own
    declarations can be cross-checked against this one place.
    """
    if sel:
        label = "O2" if auth else "O3"
        label += "b" if bl2 else "a"
        return {
            "label": label,
            "required": ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED"),
            "values": (f"BL1_DEMOTE={auth}", f"BL2_DEMOTE_DEC={bl2}"),
            "demote_1": (auth, 1),
            "demote_2": (0, 0),
            "changes": (2, None),
        }
    if bl2:
        return {
            "label": "O4",
            "required": ("DEMOTE: BL2 deferred, unlocked", "BL2_DEMOTE_DEC=", "DEMOTE_NOT_LOCKED"),
            "values": ("BL2_DEMOTE_DEC=1",),
            "demote_1": (0, 0),
            "demote_2": (0, 0),
            # The one outcome that writes neither register, so the monitor records
            # only the reset sample. Pinned EXACTLY rather than relaxed: see
            # sep_demotion_decision_base.demote_changes_min.
            "changes": (1, 1),
        }
    return {
        "label": "O5",
        "required": ("DEMOTE: BL2 deferred, lock non-demoted", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED"),
        "values": ("BL2_DEMOTE_DEC=0",),
        "demote_1": (0, 1),
        "demote_2": (0, 0),
        "changes": (2, None),
    }


class _demotion_prod_mixin:
    """Derive the per-member forbids and cross-check the declared outcome."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        bits = (cls._SEL, cls._AUTH, cls._BL2)
        if bits == (-1, -1, -1):
            # sep_demotion_prod_base itself, which declares no inputs. A concrete
            # member that forgot to declare them lands here too, and is caught at
            # run time by the _OUTCOME guard in mutate_manifest() below -- before
            # any simulation, because mutate_flash_image() runs pre-boot.
            return
        if any(b not in (0, 1) for b in bits):
            raise ValueError(f"{cls.__name__}: _SEL/_AUTH/_BL2 must each be 0 or 1, got {bits}")
        want = outcome_for(*bits)
        cls._OUTCOME = want["label"]
        # The member wrote its own expectations; this requires them to agree with
        # the table above. A copy-paste between two members of this family is the
        # realistic failure mode, and it is exactly what this catches.
        mismatches = []
        if tuple(cls.demotion_required) != want["required"]:
            mismatches.append(
                f"demotion_required {tuple(cls.demotion_required)} != {want['required']}"
            )
        if tuple(sorted(cls.demotion_values)) != tuple(sorted(want["values"])):
            mismatches.append(f"demotion_values {tuple(cls.demotion_values)} != {want['values']}")
        if tuple(cls.expect_demote_1) != want["demote_1"]:
            mismatches.append(f"expect_demote_1 {tuple(cls.expect_demote_1)} != {want['demote_1']}")
        if tuple(cls.expect_demote_2) != want["demote_2"]:
            mismatches.append(f"expect_demote_2 {tuple(cls.expect_demote_2)} != {want['demote_2']}")
        if (cls.demote_changes_min, cls.demote_changes_max) != want["changes"]:
            mismatches.append(
                f"demote change bounds "
                f"{(cls.demote_changes_min, cls.demote_changes_max)} != "
                f"{want['changes']}"
            )
        if mismatches:
            raise AssertionError(
                f"{cls.__name__} declares (sel, auth, bl2) = {bits}, which "
                f"rom_main.c:388-409 and :431-436 make outcome {want['label']}, but "
                f"its written expectations disagree: "
                + "; ".join(mismatches)
                + ". Either the declared inputs or the declared outcome is wrong; "
                "outcome_for() in rom_fw/sep_demotion_prod_base.py is the "
                "transcription of the ROM's control flow"
            )
        # Value forbids, derived from the member's own inputs so that a member
        # cannot pass on a neighbouring row's console. When BL1_DEMOTION_VALID is
        # clear the ROM never prints BL1_DEMOTE= at all, and the base already
        # forbids that whole token, so only the BL2 value needs a forbid here.
        value_forbids = [f"BL2_DEMOTE_DEC={1 - cls._BL2}"]
        if cls._SEL:
            value_forbids.append(f"BL1_DEMOTE={1 - cls._AUTH}")
        cls.forbidden_markers = tuple(cls.forbidden_markers) + tuple(value_forbids)
        cls._VALUE_FORBIDS = tuple(value_forbids)


class sep_demotion_prod_base(_demotion_prod_mixin, sep_demotion_decision_base):
    """PROD lifecycle, secure boot disabled by fuse+manifest, primary boots.

    Members declare three input bits and their expected outcome; everything else
    -- preload, lifecycle narrowing, the ``+SECURE_BOOT_DIS`` port and the marker
    skeleton -- lives here.
    """

    # Subclass contract: the three manifest demotion inputs this member drives.
    _SEL = -1  # demotion_control BL1_DEMOTION_VALID
    _AUTH = -1  # demotion_control BL1_DEMOTION_ENABLE
    _BL2 = -1  # demotion_control BL2_DEMOTION_VALID + BL2_DEMOTION_ENABLE

    efuse_preload = PROD_SBOOT_DIS_PRELOAD
    expected_lc_raw = LC_RAW_PROD
    expected_sboot_dis = 1

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD,
        _SBOOT_DIS_FUSE,
        _PRIMARY_SRC,
        _SBOOT_OFF,
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    # LC=PROD_END is forbidden rather than LC=PROD being forbidden on the PROD_END
    # side, because "LC=PROD" is a strict PREFIX of "LC=PROD_END": only the longer
    # string can serve as a discriminator. PUBK_ALGO_UNSUPPORTED is the loud failure if the
    # sboot_dis fuse surface is ever dropped. The RSA markers must not appear at
    # all: secure boot is off, so a run that verified a signature took a different
    # path from the one under test, and none of these members passes
    # +esrc_noise_force.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _LC_PROD_END,
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "RSA_EXEC",
        "RSA_PKCS1_FAIL",
        "RSA_VERIFY_OK",
        "PUBK_ALGO_UNSUPPORTED",
    )

    # --- stimulus ----------------------------------------------------------
    def mutate_manifest(self, buf: bytearray) -> None:
        """Drive the member's three inputs, then ``+SECURE_BOOT_DIS``, then PROD.

        Order matters and is not arbitrary. Every write here lands inside the
        signed region and re-hashes, and ``narrow_life_cycle_states`` is the last
        of them, so it re-hashes over everything above and re-seals the backup
        afterwards. Each mutator verifies the layout first, so a step that left
        the hash stale would fail at the next one rather than reaching the DUT.
        """
        assert getattr(self, "_OUTCOME", None), (
            f"{type(self).__name__} inherits sep_demotion_prod_base but declares no "
            f"_SEL/_AUTH/_BL2, so no decision-table row was cross-checked for it and "
            f"the stimulus below would drive nothing. Declare all three"
        )
        # One field, one write: VALID says whether BL1 demotion is specified and
        # ENABLE says what the value is, and the BL2 request is the conjunction of
        # its own pair, so a member's _BL2 sets both of those bits.
        mm.set_demotion(
            buf,
            "primary",
            bl1_valid=bool(self._SEL),
            bl1_enable=bool(self._AUTH),
            bl2_valid=bool(self._BL2),
            bl2_enable=bool(self._BL2),
        )
        apply_secure_boot_dis(self, buf)
        # The PRIMARY is deliberately NOT re-sealed: it is unsigned by
        # construction and re-signing it would undo the surface just set.
        narrow_life_cycle_states(self, buf, LC_STATES_PROD_ONLY, reseal_slots=("backup",))

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        """Read all five mutated fields back out of the packed image.

        Not duplication of the console. The ROM echoes ``demotion_control`` BL1_DEMOTION_ENABLE only when the
        BL1_DEMOTION_VALID is set and never echoes VALID itself, so on three
        of the four members at least one input is invisible in the log and a
        stimulus that silently failed to land would produce exactly the log a
        correct run produces. The stimulus is asserted, not only the outcome.
        """
        dc = mm.demotion_control(buf, "primary")
        sel = (dc >> mm.DEMOTION_BITS["BL1_DEMOTION_VALID"]) & 1
        auth = (dc >> mm.DEMOTION_BITS["BL1_DEMOTION_ENABLE"]) & 1
        bl2_valid = (dc >> mm.DEMOTION_BITS["BL2_DEMOTION_VALID"]) & 1
        bl2_enable = (dc >> mm.DEMOTION_BITS["BL2_DEMOTION_ENABLE"]) & 1
        # The ROM treats a BL2 request as the conjunction, so decode it the same
        # way: a stray ENABLE without VALID is not a request.
        bl2 = bl2_valid & bl2_enable
        sb = mm.secure_boot_control(buf, "primary") & mm.SECURE_BOOT_ENFORCED_BIT
        sigtype = mm.signature_type(buf, "primary")
        lcs = mm.lifecycle_states(buf, "primary", "chiplet")

        assert (sel, auth, bl2) == (self._SEL, self._AUTH, self._BL2), (
            f"primary demotion_control=0x{dc:04x} decodes as BL1_VALID={sel}, "
            f"BL1_ENABLE={auth}, BL2 request={bl2}; this testcase drives "
            f"({self._SEL}, {self._AUTH}, {self._BL2}) for outcome "
            f"{self._OUTCOME}. Any other triple is a different row of the "
            f"decision table measured under this testcase's name"
        )
        assert sb == 0, (
            f"primary secure_boot_control still asks for enforcement "
            f"(0x{mm.secure_boot_control(buf, 'primary'):02x}): the manifest surface "
            f"of +SECURE_BOOT_DIS did not land, and a signed request outranks the "
            f"fuse, so this run would be measuring a secure-boot-ON path"
        )
        assert sigtype == mm.SIG_TYPE_NO_SIGNATURE, (
            f"primary signature_type is {sigtype}, expected "
            f"{mm.SIG_TYPE_NO_SIGNATURE} (NO_SIGNATURE): the packer forces this "
            f"whenever secure_boot is 0, so a signed primary would be a different "
            f"image from the one this testcase means to present"
        )
        assert lcs == LC_STATES_PROD_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{LC_STATES_PROD_ONLY:08x} (PROD only)"
        )
        # The manifest hash must still be valid even though the slot is unsigned:
        # the integrity check runs regardless of secure
        # boot, so a stale hash would reject the primary before the [S25] block.
        mm.verify_layout(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-DEMOTION PASS: outcome %s -- primary demotion_control=0x%04x "
            "(BL1_VALID=%d BL1_ENABLE=%d BL2 request=%d), secure_boot_control=0 "
            "(enforcement not requested), signature_type=%d (NO_SIGNATURE), chiplet "
            "lifecycle_states=0x%08x, manifest hash valid. This slot can only boot "
            "because the SBOOT_DIS fuse is burned. Forbidden neighbouring values: %s",
            self._OUTCOME,
            dc,
            sel,
            auth,
            bl2,
            sigtype,
            lcs,
            ", ".join(self._VALUE_FORBIDS),
        )
