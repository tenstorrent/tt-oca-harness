# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared PROD_END stimulus for the [S25] demotion-decision family.

The mechanism, the seven-outcome collapse map and the disclosed gaps are written
out once in ``rom_fw/sep_demotion_decision_base.py``. **Read that first.**

============================================================================
EVERY MEMBER OF THIS BASE PRODUCES THE SAME OUTCOME, BY CONSTRUCTION
============================================================================

``rom_main.c`` short-circuits on ``lc_state == LC_STATE_PROD_END`` and returns from the
block having read NONE of the three manifest demotion inputs -- the ``demotion_control``
is not read at all: the block returns before until, and ``demotion_control`` not until,
all inside the ``else`` at . So the outcome is **O1** for every combination of those
three inputs, and this base fixes the expected outcome rather than deriving it from a
member's declarations.

What still differs between members, and is therefore still declared per member,
is the STIMULUS -- and with it what a failure would mean. With ``_SEL = 1`` the
O1 outcome is reachable only if preempts the selector-bit arm at
: a ROM that tested BL1_DEMOTION_VALID first would produce O3a, which
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
    PROD_END only, and both re-sealed. This base sets the chiplet lifecycle selector bit in the
    shipped image, so ``oca_boot.c`` maps the live LC state into
    that bitmap and refuses the manifest with a lifecycle-constraint error code if the
    bit is clear. The boot therefore cannot complete unless the ROM decoded raw
    0x8 as PROD_END. The narrowing is per lifecycle
    (``sep_demotion_uid_checker.py``, written to both slots at
).
  * The full crypto chain. PROD_END enforces secure boot
    (``lifecycle.c``), so a real RSA-3072 modexp runs on OTBN and every
    member needs ``+esrc_noise_force``. ``SBOOT_OFF`` and
    ``FUSE: SBOOT_DIS: 1`` are forbidden: either would mean the run measured a
    non-secure boot under a PROD_END name.
  * ``LC=PROD`` is deliberately NOT forbidden, because it is a strict PREFIX of
    the required ``LC=PROD_END``. Discrimination in the other direction is the
    PROD members' job and they forbid ``LC=PROD_END``.

``sep_firmware_demotion_decision_auth_flag_0_prod_end_test`` (the O1
member) predates this module and carries the same skeleton inline. It is
deliberately NOT refactored onto this base: it is an approved, passing row whose
docstring is its own evidence record. The duplication is named here and there.
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
# The only lifecycle state these members permit.
LC_STATES_PROD_END_ONLY = 1 << mm.LIFECYCLE_STATE_BITS["PROD_END"]

PROD_END_PRELOAD = EFUSE_DIR / "sep_efuse_lc_prod_end.toml"


class sep_demotion_prod_end_base(sep_demotion_decision_base):
    """PROD_END lifecycle: the manifest demotion inputs are ignored, both locked."""

    # Subclass contract: the three manifest demotion inputs this member plants.
    # The ROM reads none of them on this path -- that IS the property under test --
    # so they are asserted from the artefact instead.
    _SEL = 0  # demotion_control BL1_DEMOTION_VALID
    _AUTH = 0  # demotion_control bit 0
    _BL2 = 0  # demotion_control bit 0

    efuse_preload = PROD_END_PRELOAD
    expected_lc_raw = LC_RAW_PROD_END
    expected_sboot_dis = 0

    # rom_main.c lc_write_demotion_2(false, true)
    # lc_write_demotion(false, true). demotion_reg is still its initialiser
    # because the else-branch that could set it never runs. DEMOTE_2 locked is the
    # discriminator no other row of the table can produce: is the ROM's only
    # lc_write_demotion_2 call and it is reached only here.
    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 1)

    demotion_required = ("DEMOTE: PROD_END lock", "DEMOTE_LOCKED")
    demotion_values = ()

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD_END,
        _PRIMARY_SRC,
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    # a lifecycle-constraint error code is load-bearing: the manifest permits PROD_END
    # ONLY, so its absence is what says the ROM decoded raw 0x8 correctly. The
    # rest exclude a boot that completed by failover or with a rejected slot.
    # BL1_DEMOTE= and BL2_DEMOTE_DEC= are forbidden automatically by the family
    # base, because they are DEMOTION_TOKENS this outcome does not require -- and
    # their absence is the direct observable that no manifest input was read.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        "SBOOT_OFF",
        "FUSE: SBOOT_DIS: 1",
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "RSA_PKCS1_FAIL",
        "PUBK_ALGO_UNSUPPORTED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_SLOT_RESERVED",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_OTP_EMPTY",
        "PUBK_UNAUTHORIZED",
    )

    # --- stimulus ----------------------------------------------------------
    def mutate_manifest(self, buf: bytearray) -> None:
        """Plant the member's inputs, then narrow the lifecycle and re-seal both.

        ``narrow_life_cycle_states`` is the LAST in-TBS write and it re-seals both
        slots, so anything planted above is inside the region that gets re-signed.
        The primary must stay fully signed here, unlike on the PROD members:
        PROD_END enforces secure boot, so an unsigned primary would be refused.
        """
        # One field, one write: the BL2 request is the conjunction of its own
        # pair, so a member's _BL2 sets both of those bits.
        mm.set_demotion(
            buf,
            "primary",
            bl1_valid=bool(self._SEL),
            bl1_enable=bool(self._AUTH),
            bl2_valid=bool(self._BL2),
            bl2_enable=bool(self._BL2),
        )
        narrow_life_cycle_states(
            self, buf, LC_STATES_PROD_END_ONLY, reseal_slots=("primary", "backup")
        )

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        """Read the three demotion inputs back out of the packed image.

        This is not optional and it is not duplication of the console. At PROD_END
        the ROM echoes NONE of the three, so an unplanted input produces exactly
        the log a planted-and-ignored one produces and the testcase would be green
        and vacuous.

        It is not the only channel, and an earlier draft of this docstring wrongly
        said it was. :meth:`~sep_demotion_decision_base._check_stimulus_served`
        requires the flash DEVICE to have returned exactly these bytes, which is
        the DUT-side half and is what makes the difference between two PROD_END
        members observable at RUN time rather than only in an offline artefact.
        This method is the offline half: it proves the mutation landed in the image
        before the transport is involved at all.
        """
        dc = mm.demotion_control(buf, "primary")
        sel = (dc >> mm.DEMOTION_BITS["BL1_DEMOTION_VALID"]) & 1
        auth = (dc >> mm.DEMOTION_BITS["BL1_DEMOTION_ENABLE"]) & 1
        bl2 = ((dc >> mm.DEMOTION_BITS["BL2_DEMOTION_VALID"]) & 1) & (
            (dc >> mm.DEMOTION_BITS["BL2_DEMOTION_ENABLE"]) & 1
        )
        lcs = mm.lifecycle_states(buf, "primary", "chiplet")

        assert (sel, auth, bl2) == (self._SEL, self._AUTH, self._BL2), (
            f"primary demotion_control=0x{dc:04x} decodes as BL1_VALID={sel}, "
            f"BL1_ENABLE={auth}, BL2 request={bl2}; this testcase plants "
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
            "CHK-STIMULUS-DEMOTION: primary demotion_control=0x%04x (BL1_VALID=%d "
            "BL1_ENABLE=%d BL2 request=%d), chiplet lifecycle_states=0x%08x. The "
            "ROM must ignore all of it because the part is at PROD_END, and their "
            "absence from the console is asserted by forbidding BL1_DEMOTE= and "
            "BL2_DEMOTE_DEC=",
            dc,
            sel,
            auth,
            bl2,
            lcs,
        )
