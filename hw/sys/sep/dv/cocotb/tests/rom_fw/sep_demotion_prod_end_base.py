# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared PROD_END stimulus for the [C15] demotion-decision family.

The mechanism, the seven-outcome collapse map and the disclosed gaps are written
out once in ``rom_fw/sep_demotion_decision_base.py``. **Read that first.**

============================================================================
EVERY MEMBER OF THIS BASE PRODUCES THE SAME OUTCOME, BY CONSTRUCTION
============================================================================

``rom_main.c`` short-circuits on ``lc_state == LC_STATE_PROD_END`` and returns
from the block having read NONE of the three manifest demotion inputs -- the
selector bit, ``usage_constraints.flags`` and ``flag_args`` are consulted only
inside the ``else``. So the outcome is **O1** for every combination of those
three inputs, and this base fixes the expected outcome rather than deriving it
from a member's declarations. **Five stimuli share this one observable.** They
are five stimuli on one outcome, not five coverage points, and each member says
so in its own docstring.

What still differs between members, and is therefore still declared per member,
is the STIMULUS -- and with it what a failure would mean. With ``_SEL = 1`` the
O1 outcome is reachable only if the short-circuit preempts the selector-bit arm:
a ROM that tested the selector bit first would produce O3a, which
differs on DEMOTE_2 (never written) and prints ``BL1_DEMOTE=0`` and
``BL2_DEMOTE_DEC=0`` where O1 prints ``DEMOTE: PROD_END lock``. With all three
inputs clear there is no such control, because the two orderings agree.

============================================================================
WHAT THE MEMBERS SHARE
============================================================================

  * ``sep_efuse_lc_prod_end.toml``, raw LC state 0x8. Its differential encoding
    ``0x78`` and the authority for it (``sep_efuse_map.rdl:565-566`` for the
    encoding rule, ``hw/ip/efuse/rtl/efuse_pkg.sv:51-59`` for ``LC_PROD_END``)
    are recorded in the preload itself.
  * Both slots' ``life_cycle_states`` narrowed from the shipped ``0x7`` to
    PROD_END only, and both re-sealed. ``selector_bits`` bit 16 is set in the
    shipped image, so ``manifest_load.c`` maps the live LC state into
    that bitmap and refuses the manifest with ``LC_USAGE_CONSTRAINT_FAIL`` if the
    bit is clear. The boot therefore cannot complete unless the ROM decoded raw
    0x8 as PROD_END. This mirrors the reference, which narrows per lifecycle
    (``sep_demotion_uid_checker.py``, written to both slots).
  * The full crypto chain. PROD_END enforces secure boot
    (``lifecycle.c``), so a real RSA-3072 modexp runs on OTBN and every
    member needs ``+sep_crypto_edn_force``. ``SBOOT_OFF`` and
    ``FUSE: SBOOT_DIS: 1`` are forbidden: either would mean the run measured a
    non-secure boot under a PROD_END name.
  * ``LC=PROD`` is not forbidden, because it is a strict PREFIX of
    the required ``LC=PROD_END``. Discrimination in the other direction is the
    PROD members' job and they forbid ``LC=PROD_END``.

``sep_firmware_demotion_decision_auth_flag_0_prod_end_test`` (the O1 member)
carries the same skeleton inline rather than subclassing this base, so a change to
the skeleton must be applied in both places.
"""

from __future__ import annotations

from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_decision_base import (
    EFUSE_DIR,
    narrow_life_cycle_states,
    sep_demotion_decision_base,
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

_LC_PROD_END = "LC=PROD_END"  # lifecycle.c
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# lifecycle.h -- the raw 4-bit LC state the preload's 0x78 encodes.
LC_RAW_PROD_END = 0x8
# manifest.h -- LC_STATES_BIT_PROD_END, the only state these members permit.
LC_STATES_PROD_END_ONLY = 1 << mm.LC_STATES_BIT_PROD_END

PROD_END_PRELOAD = EFUSE_DIR / "sep_efuse_lc_prod_end.toml"


class sep_demotion_prod_end_base(sep_demotion_decision_base):
    """PROD_END lifecycle: the manifest demotion inputs are ignored, both locked."""

    # Subclass contract: the three manifest demotion inputs this member plants.
    # The ROM reads none of them on this path -- that IS the property under test --
    # so they are asserted from the artefact instead.
    _SEL = 0  # usage_constraints.selector_bits bit 17
    _AUTH = 0  # usage_constraints.flags bit 0
    _BL2 = 0  # boot_arguments.flag_args bit 0

    efuse_preload = PROD_END_PRELOAD
    expected_lc_raw = LC_RAW_PROD_END
    expected_sboot_dis = 0

    # rom_main.c: lc_write_demotion_2(false, true) then
    # lc_write_demotion(false, true). demotion_reg keeps its initialiser
    # because the else-branch that could set it never runs. DEMOTE_2 locked is the
    # discriminator no other row of the table can produce: that is the ROM's only
    # lc_write_demotion_2 call and it is reached only here.
    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 1)

    demotion_required = ("DEMOTE: PROD_END lock", "DEMOTE_LOCKED")
    demotion_values = ()

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD_END,
        _PRIMARY_SRC,
        "RSA_VERIFY_START",
        "SIG_VALID",
        "CRYPTO_VALIDATE_OK",
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    # LC_USAGE_CONSTRAINT_FAIL is load-bearing: the manifest permits PROD_END
    # ONLY, so its absence is what says the ROM decoded raw 0x8 correctly. The
    # rest exclude a boot that completed by failover or with a rejected slot.
    # BL1_DEMOTE= and BL2_DEMOTE_DEC= are forbidden automatically by the family
    # base, because they are DEMOTION_TOKENS this outcome does not require -- and
    # their absence is the direct observable that no manifest input was read.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        "LC_USAGE_CONSTRAINT_FAIL",
        "SBOOT_OFF",
        "FUSE: SBOOT_DIS: 1",
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "CRYPTO_FAIL=",
        "RSA_VERIFY_FAIL",
        "VERSION_ROLLBACK",
        "KEY_REVOKED",
        "BAD_SIG_TYPE=",
        "BAD_KEY_SEL",
        "BAD_KEY_IDX",
        "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY",
        "PUBK_HASH_MISMATCH",
    )

    # --- stimulus ----------------------------------------------------------
    def mutate_manifest(self, buf: bytearray) -> None:
        """Plant the member's inputs, then narrow the lifecycle and re-seal both.

        ``narrow_life_cycle_states`` is the LAST in-TBS write and it re-seals both
        slots, so anything planted above is inside the region that gets re-signed.
        The primary must stay fully signed here, unlike on the PROD members:
        PROD_END enforces secure boot, so an unsigned primary would be refused.
        """
        if self._SEL:
            mm.set_selector_bit(buf, "primary", mm.SELECTOR_BIT_BL1_DEMOTION, True)
        if self._AUTH:
            mm.set_usage_flags_bit(
                buf, "primary", mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, True
            )
        if self._BL2:
            mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_BL2_DEMOTION, True)
        narrow_life_cycle_states(
            self, buf, LC_STATES_PROD_END_ONLY, reseal_slots=("primary", "backup")
        )

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        """Read the three demotion inputs back out of the packed image.

        This is not optional and it is not duplication of the console. At PROD_END
        the ROM echoes NONE of the three, so an unplanted input produces exactly
        the log a planted-and-ignored one produces and the testcase would be green
        and vacuous: assert the stimulus, not only the outcome.

        It is not the only channel:
        :meth:`~sep_demotion_decision_base._check_stimulus_served`
        requires the flash DEVICE to have returned exactly these bytes, which is
        the DUT-side half and is what makes the difference between two PROD_END
        members observable at RUN time rather than only in an offline artefact.
        This method is the offline half: it proves the mutation landed in the image
        before the transport is involved at all.
        """
        sel_bits = mm.selector_bits(buf, "primary")
        sel = (sel_bits >> mm.SELECTOR_BIT_BL1_DEMOTION) & 1
        flags = mm.usage_flags(buf, "primary")
        auth = (flags >> mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION) & 1
        bl2 = (mm.get_flag_args(buf, "primary") >> mm.FLAG_ARGS_BIT_BL2_DEMOTION) & 1
        lcs = mm.life_cycle_states(buf, "primary")

        assert (sel, auth, bl2) == (self._SEL, self._AUTH, self._BL2), (
            f"primary demotion inputs decoded as selector_bits[17]={sel}, "
            f"usage_flags[0]={auth}, flag_args[0]={bl2}; this testcase plants "
            f"({self._SEL}, {self._AUTH}, {self._BL2}). The ROM ignores all three "
            f"at PROD_END, so no console line reflects it and a wrong triple "
            f"would still produce a green run. The other channel that can see it "
            f"is the device record, asserted by _check_stimulus_served()"
        )
        assert lcs == LC_STATES_PROD_END_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{LC_STATES_PROD_END_ONLY:08x} (PROD_END only)"
        )
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: primary selector_bits[%d]=%d, usage_flags[%d]=%d, "
            "flag_args[%d]=%d, life_cycle_states=0x%08x. rom_main.c:383 must ignore "
            "all three because the part is at PROD_END, and their absence from the "
            "console is asserted by forbidding BL1_DEMOTE= and BL2_DEMOTE_DEC=",
            mm.SELECTOR_BIT_BL1_DEMOTION,
            sel,
            mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION,
            auth,
            mm.FLAG_ARGS_BIT_BL2_DEMOTION,
            bl2,
            lcs,
        )
