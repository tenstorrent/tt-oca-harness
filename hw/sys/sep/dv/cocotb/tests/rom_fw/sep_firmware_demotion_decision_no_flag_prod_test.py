# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD with secure boot ENFORCED, no demotion input at all -> locked, not demoted.

Outcome **O5** of the [C15] decision table in
``rom_fw/sep_demotion_decision_base.py``. **Read that file first**: it carries the
mechanism, the seven-outcome collapse map, the register evidence channel and the
disclosed gaps for the whole demotion group.

============================================================================
SECURE BOOT IS ENFORCED HERE, WHICH IS WHAT SEPARATES THIS FROM ITS O5 SIBLING
============================================================================

The three demotion input bits are the O5 triple, the same as
``..._auth_flag_0_prod_test``, so the two are NOT distinguished by the decision
inputs. They are distinguished by the secure-boot half of the run.

This member plants no ``+SECURE_BOOT_DIS``: the primary stays signed, and at PROD
``secure_boot_enabled`` (``manifest_load.c``) enforces secure boot regardless of
the manifest flag. The sibling runs the opposite configuration -- sboot_dis fuse
burned, ``signature_type = NO_SIGNATURE``, ``flag_args`` bit 30 cleared.

The two consoles therefore differ across the whole secure-boot half:
``RSA_VERIFY_START`` / ``SIG_VALID`` / ``CRYPTO_VALIDATE_OK`` are REQUIRED here and
FORBIDDEN there, and ``SBOOT_OFF`` / ``FUSE: SBOOT_DIS: 1`` are the inverse. **This
is the only O5 whose decision is taken after a full RSA-3072 chain**, which is real
coverage rather than a technicality: ``rom_main.c`` reads the manifest out of
``bl0_state`` after ``rom_manifest_boot`` returned OK, and on the sibling that
manifest arrived through the unsigned path.

``sep_demotion_prod_base`` is deliberately NOT inherited: its ``mutate_manifest``
plants a ``+SECURE_BOOT_DIS`` that would replace this member's stimulus with a
different one. Only :class:`_demotion_prod_mixin` is composed, for the
decision-table cross-check, which belongs to the non-PROD_END arm rather than to
the secure-boot-disabled skeleton.

============================================================================
WHAT THIS ROW ASSERTS, AND WHAT IT CANNOT
============================================================================

All three manifest demotion inputs are clear in the shipped image and this row plants
NONE of them -- its only mutation is the lifecycle narrowing. ``rom_main.c`` takes
neither the selector arm nor the BL2-request arm, so ``demotion_reg`` stays false,
``lock_demotion`` keeps its initialiser, ``lc_write_demotion(0, 1)`` runs, and DEMOTE_1
reads **not demoted but LOCKED**. ``BL1_DEMOTE=`` is never printed at all and the base
forbids that whole token; ``BL2_DEMOTE_DEC=0`` is required and ``=1`` forbidden, both
derived from ``_BL2`` by the shared mixin.

**Stated plainly: on the demotion axis this is the weakest falsifier of the PROD
members, and its value is in the crypto half.** (Not of the whole family: the committed
``..._no_flag_prod_end_test`` is weaker still, and
``rom_fw/sep_demotion_decision_base.py`` records that it "adds no falsifying power at
all" because PROD_END short-circuits before any manifest input is read.) With every
input clear this row cannot catch a ROM that mis-selects between inputs -- the committed
``..._auth_flag_0_prod_test`` is the negative control for that, and it needs
``flags[0]`` SET to be one. What this row does
falsify is that a fully-signed, fully-verified PROD boot with no demotion request is
NOT demoted, and that the register is nonetheless locked so later software cannot set
it. The lock half is the part the console cannot check -- ``DEMOTE_LOCKED`` is printed
from a local -- so ``lcc_demote_lock_1_probe_o == 1`` with ``demote == 0`` is what
separates "locked, not demoted" from "never written".

``MEAS_DEMOTE=0x00000002`` is the second ROM channel. It does NOT discriminate O5 from
O3a or O1, which share the value; the console tokens do that, and the base forbids
every [C15] string this outcome does not produce.

**THE FORBIDDEN MEASUREMENT VALUE IS 0x5, AND WORKING OUT WHY IS THE POINT.** The
single-fault neighbour of this stimulus is the ROM reading a BL2 request that the image
does not contain. With the selector still clear that takes the ``else if (bl2_demote)``
arm, so ``lock_demotion`` goes false and ``demotion_decision`` becomes the request:
``1 | (0 << 1) | (1 << 2)`` = **0x5**, which is O4's value. ``0x6`` is O3b and requires
the selector bit to be misread AS WELL, so it is a two-fault neighbour. Both are
forbidden — 0x5 because it is the reachable error, 0x6 only as depth. Recorded because
an earlier draft forbade 0x6 alone and justified it as the BL2-request error, which is
wrong: that is the correct neighbour for the ``sel = 1`` sibling this file's skeleton was
adapted from, and the justification did not survive the change of selector value.
``outcome_for()`` does not cover the measurement word, so it is the one expectation in
this family with no automatic cross-check.

``MEAS_SBOOT=0x00000001`` is required as a third channel. It carries
``bl0_state->secure_boot`` as the measurement consumed it, which is a different reading
from the console path markers and is 0 on the secure-boot-disabled sibling.

Bit 2 of ``demotion_bits`` carries the BL2 REQUEST. Here ``flag_args[0]`` is
clear, so that bit is 0 and the word is 0x2.

============================================================================
PORT FIDELITY
============================================================================

``sep_demotion_uid_checker.py`` ``_build_expected_patterns`` expects
``STATUS: DEMOTION_NOT_SELECTED`` + ``STATUS: DEMOTION_LOCKED`` for this row.

MARKER SUBSTITUTION: this ROM defines no demotion status code
(``grep -n DEMOT bootrom/prod/include/status_values.h`` is empty), so the console
tokens plus the register probes carry the whole verdict. SCOPE: only the DECISION
is checked; its KBKDF/SKS/UID consumers have no BL0-side equivalent here.

Needs ``+sep_crypto_edn_force``: secure boot is enforced, so a real RSA-3072 modexp
runs on OTBN.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_decision_base import (
    EFUSE_DIR,
    narrow_life_cycle_states,
    sep_demotion_decision_base,
)
# The outcome cross-check belongs to the non-PROD_END arm of the table, not to the
# secure-boot-disabled skeleton, so it is reused here while sep_demotion_prod_base's
# +SECURE_BOOT_DIS stimulus deliberately is not.
from rom_fw.sep_demotion_prod_base import (
    LC_RAW_PROD,
    LC_STATES_PROD_ONLY,
    _demotion_prod_mixin,
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

_LC_PROD = "LC=PROD"                               # lifecycle.c
_LC_PROD_END = "LC=PROD_END"                       # lifecycle.c
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

PROD_PRELOAD = EFUSE_DIR / "sep_efuse_lc_prod.toml"

# Shipped flag_args is 0x40000000 (bit 30, secure_boot) and this member changes
# NOTHING in it.
_EXPECTED_FLAG_ARGS = 1 << mm.FLAG_ARGS_BIT_SECURE_BOOT

# measurement.h echoes the low three bits of rom_main.c's demotion_bits. With no
# decision, the lock set and no BL2 request the word is lock-only. 0x5 is this stimulus
# with the BL2 request misread -- the selector stays clear, so the deferred-unlocked arm
# runs and the request becomes the decision. 0x6 needs the selector misread too.
_MEAS_LOCKED_BL2_ABSENT = "MEAS_DEMOTE=0x00000002"
_MEAS_DEFERRED_UNLOCKED = "MEAS_DEMOTE=0x00000005"
_MEAS_LOCKED_BL2_COUNTED = "MEAS_DEMOTE=0x00000006"

# The measurement's own reading of bl0_state->secure_boot (manifest_load.c), which is 0
# on the secure-boot-disabled O5 sibling.
_MEAS_SBOOT_ON = "MEAS_SBOOT=0x00000001"


@pyuvm.test()
class sep_firmware_demotion_decision_no_flag_prod_test(
        _demotion_prod_mixin, sep_demotion_decision_base):
    """PROD, secure boot on, no demotion input: DEMOTE_1 locked, not demoted."""

    # +LC_STATE_PROD only -- no +SECURE_BOOT_DIS, no +SET_SELECTOR_BIT_17, no
    # +AUTH_FLAG_0 and no +UNAUTH_FLAG_* (bootcode_regression.yaml).
    _SEL = 0
    _AUTH = 0
    _BL2 = 0

    efuse_preload = PROD_PRELOAD
    expected_lc_raw = LC_RAW_PROD
    expected_sboot_dis = 0

    demotion_required = ("DEMOTE: BL2 deferred, lock non-demoted", "BL2_DEMOTE_DEC=",
                         "DEMOTE_LOCKED")
    demotion_values = ("BL2_DEMOTE_DEC=0",)

    # rom_main.c: neither arm is taken, so lc_write_demotion(demotion_reg=false,
    # lock=true) runs. DEMOTE_2 is written only on the PROD_END arm, so it stays at its
    # reset value -- observable as lock == 0 because the field is write-one-to-set.
    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD, _PRIMARY_SRC, "RSA_VERIFY_START", "SIG_VALID",
        "CRYPTO_VALIDATE_OK", "PLD_HASH_OK", "MANIFEST_HASH_OK",
        _MEAS_LOCKED_BL2_ABSENT, _MEAS_SBOOT_ON, "BL1_COPIED", "BL1_JUMP=",
    )
    # SBOOT_OFF and FUSE: SBOOT_DIS: 1 are forbidden because this row's whole
    # difference from the committed O5 member is that secure boot is ENFORCED; either
    # would mean the run measured that member's path under this name.
    # LC_USAGE_CONSTRAINT_FAIL decides the outcome: the manifest permits PROD only, so its
    # absence is what says the ROM decoded raw 0x1 as PROD. LC=PROD is required rather
    # than relying on forbidding LC=PROD_END alone, because "LC=PROD" is a strict prefix
    # of "LC=PROD_END" and only the longer string discriminates.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _LC_PROD_END, "LC_USAGE_CONSTRAINT_FAIL", "SBOOT_OFF", "FUSE: SBOOT_DIS: 1",
        _BACKUP_SRC, "MANIFEST_ERR=", "MANIFEST_ALL_FAILED", "CRYPTO_FAIL=",
        "RSA_VERIFY_FAIL", "VERSION_ROLLBACK", "KEY_REVOKED", "BAD_SIG_TYPE=",
        "BAD_KEY_SEL", "BAD_KEY_IDX", "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY",
        "PUBK_HASH_MISMATCH", "PLD_HASH_MISMATCH", "PLD_HASH_FAIL=",
        "MANIFEST_HASH_MISMATCH", "ENC_WITHOUT_SBOOT",
        _MEAS_DEFERRED_UNLOCKED, _MEAS_LOCKED_BL2_COUNTED,
    )

    # --- stimulus ----------------------------------------------------------
    def mutate_manifest(self, buf: bytearray) -> None:
        """Narrow the lifecycle to PROD and re-seal BOTH slots. Nothing else.

        This row's three demotion inputs are all clear in the shipped image, so it
        plants none of them; the narrowing is what makes the boot's success say the
        ROM decoded PROD. Both slots are re-sealed because the primary must stay
        genuinely signed -- PROD enforces secure boot here, and an unsigned primary
        would be refused and the boot would come from the backup, which carries no
        demotion stimulus and would produce O5 under this row's name anyway.
        """
        # The stimulus below plants nothing, so the shipped image's three demotion
        # fields must already be the triple the decision table was cross-checked
        # against. Asserting the relation here fails before the simulation rather than
        # measuring a different row of the table under this name.
        assert (self._SEL, self._AUTH, self._BL2) == (0, 0, 0), (
            f"this member plants NO demotion input and relies on "
            f"selector_bits[{mm.SELECTOR_BIT_BL1_DEMOTION}], "
            f"usage_constraints.flags[{mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION}] "
            f"and flag_args[{mm.FLAG_ARGS_BIT_BL2_DEMOTION}] all being clear in the "
            f"shipped image, but it declares (_SEL, _AUTH, _BL2) = "
            f"({self._SEL}, {self._AUTH}, {self._BL2}) for outcome {self._OUTCOME}. "
            f"Drive the bits it declares or restore (0, 0, 0)"
        )
        narrow_life_cycle_states(self, buf, LC_STATES_PROD_ONLY,
                                 reseal_slots=("primary", "backup"))

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        """Read the demotion inputs and the secure-boot surface out of the image.

        Not duplication of the console. The ROM never echoes the selector bit and
        echoes ``flags[0]`` only when the selector is set, so on this row two of the
        three inputs are invisible in the log: a shipped image that had one of them SET
        would send the run down a different arm and still produce a plausible console.
        The signature-type and flag_args assertions are the other half -- they are what
        say this run is the secure-boot-ENFORCED variant rather than the committed O5
        member's path.
        """
        sel_bits = mm.selector_bits(buf, "primary")
        sel = (sel_bits >> mm.SELECTOR_BIT_BL1_DEMOTION) & 1
        flags = mm.usage_flags(buf, "primary")
        auth = (flags >> mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION) & 1
        fa = mm.get_flag_args(buf, "primary")
        bl2 = (fa >> mm.FLAG_ARGS_BIT_BL2_DEMOTION) & 1
        sigtype = mm.get_signature_type(buf, "primary")
        lcs = mm.life_cycle_states(buf, "primary")

        assert (sel, auth, bl2) == (self._SEL, self._AUTH, self._BL2), (
            f"primary demotion inputs decoded as selector_bits[17]={sel}, "
            f"usage_flags[0]={auth}, flag_args[0]={bl2}; this testcase drives "
            f"({self._SEL}, {self._AUTH}, {self._BL2}) for outcome {self._OUTCOME}. "
            f"Any other triple is a different row of the decision table measured "
            f"under this testcase's name"
        )
        assert fa == _EXPECTED_FLAG_ARGS, (
            f"primary flag_args is 0x{fa:08x}, expected 0x{_EXPECTED_FLAG_ARGS:08x} "
            f"(bit {mm.FLAG_ARGS_BIT_SECURE_BOOT} secure_boot KEPT and nothing else "
            f"set). Clearing bit {mm.FLAG_ARGS_BIT_SECURE_BOOT} here would be porting "
            f"a +SECURE_BOOT_DIS this reference entry does not carry"
        )
        assert sigtype == mm.SIG_TYPE_RSA_3072, (
            f"primary signature_type is {sigtype}, expected "
            f"{mm.SIG_TYPE_RSA_3072}: this row's primary must stay genuinely signed, "
            f"because PROD enforces secure boot and an unsigned slot would be refused "
            f"and the boot would come from the backup, which carries no demotion "
            f"stimulus"
        )
        assert lcs == LC_STATES_PROD_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{LC_STATES_PROD_ONLY:08x} (PROD only)"
        )
        mm.verify_layout(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: outcome %s -- primary selector_bits[%d]=%d, "
            "usage_flags[%d]=%d, flag_args=0x%08x (bit %d=%d BL2, bit %d=1 "
            "secure_boot KEPT), signature_type=%d (RSA-3072), "
            "life_cycle_states=0x%08x. No demotion input is planted by this row. "
            "Forbidden neighbouring values: %s",
            self._OUTCOME, mm.SELECTOR_BIT_BL1_DEMOTION, sel,
            mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, auth, fa,
            mm.FLAG_ARGS_BIT_BL2_DEMOTION, bl2, mm.FLAG_ARGS_BIT_SECURE_BOOT,
            sigtype, lcs, ", ".join(self._VALUE_FORBIDS),
        )
