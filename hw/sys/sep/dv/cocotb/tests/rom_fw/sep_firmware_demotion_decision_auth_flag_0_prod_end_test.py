# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END + BL1 demotion flag set -> the flag is IGNORED, both registers locked.

Outcome **O1** of the [C15] decision table in ``rom_fw/sep_demotion_decision_base.py``,
which is where the mechanism, the collapse map and the disclosed gaps are written out
once. Read that first.

WHAT THIS TESTCASE ACTUALLY PROVES, stated precisely because the honest claim is
narrower than the name suggests. The stimulus is "the manifest requests BL1 demotion
and the part is at PROD_END", and the required behaviour is that **the request is not
honoured**: ``rom_main.c`` short-circuits on ``lc_state == LC_STATE_PROD_END``
before ``usage_constraints.flags`` is read, so the ROM writes DEMOTE_1
non-demoted and locked, additionally locks DEMOTE_2, and boots. The demotion flag
being SET rather than clear is what makes this a test of the override rather than of
the default.

**THIS IS ONE OF FIVE STIMULI THAT SHARE THIS OUTCOME.** ``+AUTH_FLAG_0``,
``+UNAUTH_FLAG_0`` and ``+SET_SELECTOR_BIT_17`` are all unobservable at PROD_END for
the same structural reason, so ``no_flag_prod_end``, ``no_flag_prod_end_sel_bit_set``,
``auth_flag_0_prod_end``, ``unauth_flag_0_prod_end`` and ``unauth_flag_30_prod_end``
are five stimuli on one observable. The other four are covered-by-O1, not four more
coverage points.

PROD_END BOOT. Raw LC 0x8 exercises three ROM paths, not one: the demotion
short-circuit above,
``lc_state_enforces_secure_boot`` returning true for PROD_END
(``bootrom/prod/src/lifecycle.c:69-73``) so the crypto chain runs on the lifecycle's
authority, and ``lc_state_to_manifest_bit`` mapping PROD_END to
``LC_STATES_BIT_PROD_END`` (``lifecycle.c``).

**THE LIFECYCLE DECODE IS ASSERTED, NOT ASSUMED.** Both slots' ``life_cycle_states``
are narrowed from the shipped 0x7 to 0x4 -- PROD_END only -- exactly as the reference
does (``sep_demotion_uid_checker.py``). ``selector_bits``
bit 16 is set in the shipped image, so ``manifest_load.c`` maps the live LC
state into that bitmap and refuses the manifest with ``LC_USAGE_CONSTRAINT_FAIL`` if
the bit is clear. The boot therefore cannot complete unless the ROM decoded raw 0x8
as PROD_END. Without this narrowing the shipped 0x7 would accept any of three states
and the run would prove nothing about which one was decoded.

Evidence, on both channels:

  * ``LC=PROD_END`` (``lifecycle.c``) -- the ROM's own decode of the fuse.
    Note ``LC=PROD`` is a strict PREFIX of this string, so it is not in the
    forbidden list; the discrimination in the other direction is the PROD
    member's job and it forbids ``LC=PROD_END``;
  * ``DEMOTE: PROD_END lock`` (``rom_main.c``) and ``DEMOTE_LOCKED``, each
    exactly once and after ``MANIFEST_OK``; and **every other [C15]
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

Needs ``+sep_crypto_edn_force``: PROD_END enforces secure boot (``lifecycle.c``),
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
# manifest.h -- LC_STATES_BIT_PROD_END, the only bit this testcase permits.
_LC_STATES_PROD_END_ONLY = 1 << mm.LC_STATES_BIT_PROD_END


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
        "RSA_VERIFY_START",
        "SIG_VALID",
        "CRYPTO_VALIDATE_OK",
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    # LC_USAGE_CONSTRAINT_FAIL is load-bearing here: the manifest permits PROD_END
    # ONLY, so its absence is what says the ROM decoded raw 0x8 correctly. SBOOT_OFF
    # would mean PROD_END did not enforce secure boot. The rest exclude a boot that
    # completed by failover or with a rejected slot.
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
        # +AUTH_FLAG_0 -> usage_constraints.BL1_demotion, i.e. flags bit 0
        # (sep_demotion_uid_checker.py sets it on the PRIMARY only, and the
        # reference's own decision table makes it the BL1 demotion request).
        mm.set_usage_flags_bit(buf, "primary", mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, True)
        # Narrowing life_cycle_states is the last in-TBS write, and it re-seals both
        # slots, so the flag write above is inside the region that gets re-signed.
        narrow_life_cycle_states(
            self, buf, _LC_STATES_PROD_END_ONLY, reseal_slots=("primary", "backup")
        )

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        flags = mm.usage_flags(buf, "primary")
        bit = (flags >> mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION) & 1
        assert bit == 1, (
            f"primary usage_constraints.flags is 0x{flags:08x} with the BL1 demotion "
            f"bit clear. This testcase's entire content is 'the manifest REQUESTS "
            f"demotion and PROD_END refuses it', and the ROM never echoes this field "
            f"on the PROD_END path (rom_main.c:383 returns before :395), so a "
            f"stimulus that failed to land would produce exactly the log a correct "
            f"run produces"
        )
        # The other two manifest demotion inputs stay CLEAR, so this run isolates
        # the flag. Their being ignored is part of the same short-circuit, but a
        # testcase named auth_flag_0 must not silently also drive them.
        sel = mm.selector_bits(buf, "primary")
        sel_bit = (sel >> mm.SELECTOR_BIT_BL1_DEMOTION) & 1
        bl2 = (mm.get_flag_args(buf, "primary") >> mm.FLAG_ARGS_BIT_BL2_DEMOTION) & 1
        assert sel_bit == 0 and bl2 == 0, (
            f"primary selector_bits[{mm.SELECTOR_BIT_BL1_DEMOTION}]={sel_bit} and "
            f"flag_args[{mm.FLAG_ARGS_BIT_BL2_DEMOTION}]={bl2}; both must be 0 so "
            f"this run drives the AUTH flag alone"
        )
        lcs = mm.life_cycle_states(buf, "primary")
        assert lcs == _LC_STATES_PROD_END_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{_LC_STATES_PROD_END_ONLY:08x} (PROD_END only)"
        )
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: primary usage_constraints.flags bit %d = 1 "
            "(BL1 demotion REQUESTED), selector_bits[%d] = 0, flag_args[%d] = 0, "
            "life_cycle_states = 0x%08x. The ROM must ignore all three because the "
            "part is at PROD_END",
            mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION,
            mm.SELECTOR_BIT_BL1_DEMOTION,
            mm.FLAG_ARGS_BIT_BL2_DEMOTION,
            lcs,
        )
