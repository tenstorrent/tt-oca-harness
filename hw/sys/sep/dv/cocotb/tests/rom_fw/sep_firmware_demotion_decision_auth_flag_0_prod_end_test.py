# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END + BL1 demotion flag set -> the flag is IGNORED, both registers locked.

Outcome **O1** of the [S25] decision table in ``rom_fw/sep_demotion_decision_base.py``,
which is where the mechanism, the collapse map and the disclosed gaps are written out
once. Read that first.

WHAT THIS TESTCASE ACTUALLY PROVES, stated precisely because the honest claim is
narrower than the name suggests. The stimulus is "the manifest requests BL1 demotion
and the part is at PROD_END", and the required behaviour is that **the request is not
honoured**: ``rom_main.c`` short-circuits on ``lc_state == LC_STATE_PROD_END``
before ``demotion_control`` is read, so the ROM writes DEMOTE_1
non-demoted and locked, additionally locks DEMOTE_2, and boots. The demotion flag
being SET rather than clear is what makes this a test of the override rather than of
the default.

**THIS IS ONE OF FOUR STIMULI THAT SHARE THIS OUTCOME.** ``+AUTH_FLAG_0``,
``+UNAUTH_FLAG_0`` and ``+SET_SELECTOR_BIT_17`` are all unobservable at PROD_END for
the same structural reason, so ``no_flag_prod_end``, ``no_flag_prod_end_sel_bit_set``,
``auth_flag_0_prod_end`` and ``unauth_flag_0_prod_end`` are four stimuli on one
observable. The other three are covered-by-O1, not three more
coverage points.

FIRST PROD_END BOOT IN THIS TESTLIST. Before this testcase every rom_fw eFuse preload
selected TEST_DEV (raw 0x0) or PROD (raw 0x1); nothing exercised raw 0x8. That makes
three ROM paths newly covered, not one: the demotion short-circuit above,
``lc_state_enforces_secure_boot`` returning true for PROD_END
(``bootrom/prod/src/lifecycle.c:69-73``) so the crypto chain runs on the lifecycle's
authority, and ``lc_state_to_manifest_bit`` mapping PROD_END to
the PROD_END lifecycle bit (``lifecycle.c``).

**THE LIFECYCLE DECODE IS ASSERTED, NOT ASSUMED.** Both slots' ``life_cycle_states``
are narrowed from the shipped 0x7 to 0x4 -- PROD_END only. ``selector_bits``
bit 16 is set in the shipped image, so ``oca_boot.c`` maps the live LC
state into that bitmap and refuses the manifest with a lifecycle-constraint error code if
the bit is clear. The boot therefore cannot complete unless the ROM decoded raw 0x8
as PROD_END. Without this narrowing the shipped 0x7 would accept any of three states
and the run would prove nothing about which one was decoded.

Evidence, on both channels:

  * ``LC=PROD_END`` (``lifecycle.c``) -- the ROM's own decode of the fuse.
    Note ``LC=PROD`` is a strict PREFIX of this string, so it is deliberately NOT in
    the forbidden list; the discrimination in the other direction is the PROD
    member's job and it forbids ``LC=PROD_END``;
  * ``DEMOTE: PROD_END lock`` (``rom_main.c``) and ``DEMOTE_LOCKED``, each exactly once and after ``MANIFEST_OK``; and **every other [S25]
    string forbidden** -- in particular ``BL1_DEMOTE=`` and ``BL2_DEMOTE_DEC=``,
    whose absence is the direct observable that the manifest inputs were never read;
  * DEMOTE_1 = (demote 0, lock 1) and **DEMOTE_2 = (demote 0, lock 1)**. DEMOTE_2 is
    the discriminator that no other row of the table can produce: ``rom_main.c``
    is the only ``lc_write_demotion_2`` call in the ROM and it is reached only here,
    so every other outcome leaves DEMOTE_2 at lock 0;
  * the manifest flag itself, read back from the packed image before the run. It is
    the one input the ROM never echoes on this path, and an unset flag produces
    exactly the log a set-but-ignored flag produces, so without this assertion the
    testcase would be green and vacuous.

Needs ``+esrc_noise_force``: PROD_END enforces secure boot (``lifecycle.c``),
so a full RSA-3072 modexp runs on OTBN. The RSA assertions are untouched.
"""

from __future__ import annotations

import pyuvm
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
_LC_RAW_PROD_END = 0x8
# The only lifecycle bit this testcase permits.
_LC_STATES_PROD_END_ONLY = 1 << mm.LIFECYCLE_STATE_BITS["PROD_END"]


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_prod_end_test(sep_demotion_decision_base):
    """PROD_END overrides a set BL1 demotion flag: no demotion, both registers locked."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_prod_end.toml"
    expected_lc_raw = _LC_RAW_PROD_END
    expected_sboot_dis = 0

    # rom_main.c lc_write_demotion_2(false, true)
    # lc_write_demotion(false, true) -- demotion_reg is still its initialiser
    # (:377) because the else-branch that could set it never runs.
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
    # a lifecycle-constraint error code is load-bearing here: the manifest permits PROD_END
    # ONLY, so its absence is what says the ROM decoded raw 0x8 correctly. SBOOT_OFF
    # would mean PROD_END did not enforce secure boot. The rest exclude a boot that
    # completed by failover or with a rejected slot.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        "SBOOT_OFF",
        "FUSE: SBOOT_DIS: 1",
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "MANIFEST_ERR=",
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
        # +AUTH_FLAG_0 -> usage_constraints.BL1_demotion, i.e. flags bit 0
        # (sep_demotion_uid_checker.py sets it on the PRIMARY only, and the
        # reference's own decision table makes it the BL1 demotion request).
        mm.set_demotion(buf, "primary", bl1_valid=False, bl1_enable=True)
        # Narrowing life_cycle_states is the last in-signed region write, and it re-seals both
        # slots, so the flag write above is inside the region that gets re-signed.
        narrow_life_cycle_states(
            self, buf, _LC_STATES_PROD_END_ONLY, reseal_slots=("primary", "backup")
        )

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        dc = mm.demotion_control(buf, "primary")
        bit = (dc >> mm.DEMOTION_BITS["BL1_DEMOTION_ENABLE"]) & 1
        assert bit == 1, (
            f"primary demotion_control is 0x{dc:04x} with the BL1 demotion enable "
            f"bit clear. This testcase's entire content is 'the manifest REQUESTS "
            f"demotion and PROD_END refuses it', and the ROM never echoes this field "
            f"on the PROD_END path (rom_main.c:383 returns before :395), so a "
            f"stimulus that failed to land would produce exactly the log a correct "
            f"run produces"
        )
        # The other two manifest demotion inputs stay CLEAR, so this run isolates
        # the flag. Their being ignored is part of the same short-circuit, but a
        # testcase named auth_flag_0 must not silently also drive them.
        sel_bit = (dc >> mm.DEMOTION_BITS["BL1_DEMOTION_VALID"]) & 1
        bl2 = ((dc >> mm.DEMOTION_BITS["BL2_DEMOTION_VALID"]) & 1) & (
            (dc >> mm.DEMOTION_BITS["BL2_DEMOTION_ENABLE"]) & 1
        )
        assert sel_bit == 0 and bl2 == 0, (
            f"primary demotion_control=0x{dc:04x} has BL1_VALID={sel_bit} and BL2 "
            f"request={bl2}; both must be 0 so "
            f"this run drives the AUTH flag alone"
        )
        lcs = mm.lifecycle_states(buf, "primary", "chiplet")
        assert lcs == _LC_STATES_PROD_END_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{_LC_STATES_PROD_END_ONLY:08x} (PROD_END only)"
        )
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: primary demotion_control bit %d = 1 "
            "(BL1 demotion REQUESTED with BL1_VALID clear and no BL2 request), "
            "life_cycle_states = 0x%08x. The ROM must ignore all three because the "
            "part is at PROD_END",
            dc,
            lcs,
        )
