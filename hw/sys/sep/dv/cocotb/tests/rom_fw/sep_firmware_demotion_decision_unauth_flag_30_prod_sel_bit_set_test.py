# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD with secure boot ENFORCED, selector bit 17 set, BL1 flag clear -> locked.

Outcome **O3a** of the [C15] decision table in
``rom_fw/sep_demotion_decision_base.py``. **Read that file first**: it carries the
mechanism, the seven-outcome collapse map, the register evidence channel and the
disclosed gaps for the whole demotion group.

============================================================================
WHY THIS MEMBER DOES NOT INHERIT ``sep_demotion_prod_base``
============================================================================

Every other PROD member of this family runs with secure boot OFF: they port
``+SECURE_BOOT_DIS``, which burns the ``sboot_dis`` eFuse, clears ``flag_args``
bit 30 and forces ``signature_type = NO_SIGNATURE``. **This row's reference entry
carries no ``+SECURE_BOOT_DIS``**, so its primary manifest is
genuinely signed and, at PROD, ``secure_boot_enabled`` enforces secure boot
regardless of the manifest flag (``manifest_load.c``). Inheriting the
secure-boot-disabled base would have replaced this member's stimulus with a
different one, so the PROD skeleton is written out here instead.

**That makes this row the only demotion member whose [C15] decision is taken after a
full crypto chain**, and that is real coverage rather than a technicality. The
decision block reads the manifest out of ``bl0_state`` after ``rom_manifest_boot``
returns OK (``rom_main.c``), and on every other PROD member that manifest arrived
through the unsigned path. Here it arrives through RSA-3072 verification on OTBN, so
``RSA_VERIFY_START``, ``SIG_VALID`` and ``CRYPTO_VALIDATE_OK`` are REQUIRED and
``SBOOT_OFF`` / ``FUSE: SBOOT_DIS: 1`` are FORBIDDEN -- the exact inverse of
``sep_firmware_demotion_decision_no_flag_prod_sel_bit_set_test``, which drives the
same three demotion inputs. The two rows are therefore not duplicates: their
consoles differ in the whole secure-boot half.

============================================================================
THE ``+UNAUTH_FLAG_30`` HALF IS INERT ON THIS ROM
============================================================================

``+UNAUTH_FLAG_30`` sets ``boot_arguments.skip_SHA256``, i.e. ``flag_args`` bit 31.
``FLAG_ARGS_BIT_SKIP_SHA256`` is defined at ``bootrom/prod/include/manifest.h``
and read by NOTHING under ``bootrom/prod/src`` -- the only two ``flag_args`` bits
with a reader are bit 30 and bit 0. So on the demotion path this row is
covered-by-O3a, and the bit that names it changes no ROM behaviour at all.

**AND AT THIS LIFECYCLE THE BIT IS IGNORED BY DESIGN, SO NOTHING IS LOST.**
``check_sha256_enabled()`` returns
true immediately when secure boot is on, then returns true again for every lifecycle
except ``LC_STATE_TEST_DEV``, and only in TEST_DEV does it test the bit. This row runs at
PROD with secure boot ENFORCED, so it clears that gate twice over. The ROM-wide
gap is real but bites the TEST_DEV hash-skip members, which are different
testcases.

Bounded, and disclosed here and in the row's ``flow_deviation``:

  * the demotion decision under test is real and is asserted on both channels;
  * the expectation for ``+UNAUTH_FLAG_30`` is identical to the no-flag one, so
    the demotion verdict asserted here is unaffected. What is lost is the
    hash-skip behaviour, a different feature covered by different testcases;
  * the planted bit is still asserted, on the packed image by
    :meth:`check_manifest_stimulus` and on the bytes the flash DEVICE served by
    :meth:`~sep_demotion_decision_base._check_stimulus_served`. Neither is a ROM
    observable.

============================================================================
WHAT THE DEMOTION HALF ASSERTS
============================================================================

``rom_main.c`` takes the selector arm and copies ``usage_constraints.flags`` bit 0 --
clear -- into ``demotion_reg``, printing ``BL1_DEMOTE=0``; ``lock_demotion`` keeps
its initialiser, so ``lc_write_demotion(0, 1)`` runs and DEMOTE_1 reads **not demoted
but LOCKED**. ``BL2_DEMOTE_DEC=0`` is required and ``BL2_DEMOTE_DEC=1`` forbidden,
both derived from ``_BL2`` by the shared mixin. The lock half is the part the console
cannot check -- ``DEMOTE_LOCKED`` is printed from a local -- so
``lcc_demote_lock_1_probe_o`` is what says the register was actually locked, and
``lock == 1`` with ``demote == 0`` is the one combination that separates
"locked, not demoted" from "never written".

MARKER SUBSTITUTION: this ROM defines no demotion status code, so the console
tokens plus the DEMOTE_1/DEMOTE_2 register probes carry the whole verdict. SCOPE:
only the DECISION is checked; its UID/KBKDF consumers have no BL0-side equivalent
here.

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

# Shipped flag_args is 0x40000000 (bit 30, secure_boot), which this row KEEPS -- the
# reference passes no +SECURE_BOOT_DIS -- and adds bit 31.
_EXPECTED_FLAG_ARGS = (1 << mm.FLAG_ARGS_BIT_SECURE_BOOT) | (1 << mm.FLAG_ARGS_BIT_SKIP_SHA256)

# measurement.h echoes the low three bits of rom_main.c's demotion_bits. With the BL1
# flag clear, the lock set and no BL2 request, the word is lock-only; the O3b sibling,
# which differs only in the BL2 request, prints 0x6.
_MEAS_LOCKED_BL2_ABSENT = "MEAS_DEMOTE=0x00000002"
_MEAS_LOCKED_BL2_COUNTED = "MEAS_DEMOTE=0x00000006"


@pyuvm.test()
class sep_firmware_demotion_decision_unauth_flag_30_prod_sel_bit_set_test(
        _demotion_prod_mixin, sep_demotion_decision_base):
    """PROD, secure boot on, selector set, BL1 flag clear: DEMOTE_1 locked, not demoted."""

    # +UNAUTH_FLAG_30 +LC_STATE_PROD +SET_SELECTOR_BIT_17, and NO +SECURE_BOOT_DIS
    # and no +AUTH_FLAG_0 / +UNAUTH_FLAG_0.
    _SEL = 1
    _AUTH = 0
    _BL2 = 0

    efuse_preload = PROD_PRELOAD
    expected_lc_raw = LC_RAW_PROD
    expected_sboot_dis = 0

    demotion_required = ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED")
    demotion_values = ("BL1_DEMOTE=0", "BL2_DEMOTE_DEC=0")

    # rom_main.c: lc_write_demotion(demotion_reg=false, lock=true). DEMOTE_2 is
    # written only on the PROD_END arm, so it stays at its reset value -- observable
    # as lock == 0 because the field is write-one-to-set.
    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD, _PRIMARY_SRC, "RSA_VERIFY_START", "SIG_VALID",
        "CRYPTO_VALIDATE_OK", "PLD_HASH_OK", "MANIFEST_HASH_OK",
        _MEAS_LOCKED_BL2_ABSENT, "BL1_COPIED", "BL1_JUMP=",
    )
    # LC_USAGE_CONSTRAINT_FAIL decides the outcome: the manifest permits PROD only, so
    # its absence is what says the ROM decoded raw 0x1 as PROD. SBOOT_OFF and
    # FUSE: SBOOT_DIS: 1 are forbidden because this row's whole difference from its
    # O3a sibling is that secure boot is ENFORCED; either would mean the run measured
    # the sibling's path under this name. LC=PROD is required rather than LC=PROD_END
    # forbidden-only, because "LC=PROD" is a strict prefix of "LC=PROD_END" and only
    # the longer string discriminates.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _LC_PROD_END, "LC_USAGE_CONSTRAINT_FAIL", "SBOOT_OFF", "FUSE: SBOOT_DIS: 1",
        _BACKUP_SRC, "MANIFEST_ERR=", "MANIFEST_ALL_FAILED", "CRYPTO_FAIL=",
        "RSA_VERIFY_FAIL", "VERSION_ROLLBACK", "KEY_REVOKED", "BAD_SIG_TYPE=",
        "BAD_KEY_SEL", "BAD_KEY_IDX", "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY",
        "PUBK_HASH_MISMATCH", "PLD_HASH_MISMATCH", "PLD_HASH_FAIL=",
        "MANIFEST_HASH_MISMATCH", _MEAS_LOCKED_BL2_COUNTED,
    )

    # --- stimulus ----------------------------------------------------------
    def mutate_manifest(self, buf: bytearray) -> None:
        """Selector bit, then the PROD narrowing and re-seal, then ``skip_SHA256``.

        Order is not arbitrary. ``set_selector_bit`` writes inside the TBS and
        re-hashes; ``narrow_life_cycle_states`` is the LAST in-TBS write and re-seals
        BOTH slots, so the primary stays fully signed -- which it must, because PROD
        enforces secure boot here. ``flag_args`` is outside the TBS
        (``manifest.h``), so the last write needs no re-hash and cannot invalidate
        the seal.
        """
        # This member writes only the selector bit, so the other two inputs must be
        # the ones the decision table was cross-checked against. sep_demotion_prod_base
        # derives its three writes from the same attributes; here the relation is
        # asserted instead, so changing a bit without changing the stimulus fails
        # before the simulation rather than measuring a different row of the table.
        assert (self._SEL, self._AUTH, self._BL2) == (1, 0, 0), (
            f"this member plants ONLY selector_bits[{mm.SELECTOR_BIT_BL1_DEMOTION}] "
            f"and relies on usage_constraints.flags[0] and flag_args[0] being clear "
            f"in the shipped image, but it declares "
            f"(_SEL, _AUTH, _BL2) = ({self._SEL}, {self._AUTH}, {self._BL2}) for "
            f"outcome {self._OUTCOME}. Drive the other two bits or restore (1, 0, 0)"
        )
        mm.set_selector_bit(buf, "primary", mm.SELECTOR_BIT_BL1_DEMOTION, True)
        narrow_life_cycle_states(self, buf, LC_STATES_PROD_ONLY,
                                 reseal_slots=("primary", "backup"))
        before = mm.get_flag_args(buf, "primary")
        mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_SKIP_SHA256, True)
        after = mm.get_flag_args(buf, "primary")
        assert after == before | (1 << mm.FLAG_ARGS_BIT_SKIP_SHA256), (
            f"primary flag_args is 0x{after:08x} after the write, expected "
            f"0x{before | (1 << mm.FLAG_ARGS_BIT_SKIP_SHA256):08x}; the mutation did "
            f"not land"
        )
        self.logger.info(
            "CHK-STIMULUS-SKIP-SHA256: primary flag_args 0x%08x -> 0x%08x (bit %d "
            "set). No ROM code reads this bit, so the only "
            "channels that can see it are the packed image and the bytes the flash "
            "device serves", before, after, mm.FLAG_ARGS_BIT_SKIP_SHA256,
        )

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        """Read every mutated field back out of the packed image, before the run.

        Not duplication of the console. The ROM never echoes the selector bit, and it
        echoes ``flags[0]`` only as the value it copied -- so a selector bit that
        failed to land would send the run down the ``else`` arm and produce a
        DIFFERENT but still plausible log. ``flag_args`` bit 31 is echoed by nothing
        at all.
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
            f"(secure_boot bit {mm.FLAG_ARGS_BIT_SECURE_BOOT} KEPT, plus skip_SHA256 "
            f"bit {mm.FLAG_ARGS_BIT_SKIP_SHA256}). Clearing bit "
            f"{mm.FLAG_ARGS_BIT_SECURE_BOOT} here would be porting a "
            f"+SECURE_BOOT_DIS this reference entry does not carry"
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
            "secure_boot KEPT, bit %d=1 skip_SHA256), signature_type=%d (RSA-3072), "
            "life_cycle_states=0x%08x. Forbidden neighbouring values: %s",
            self._OUTCOME, mm.SELECTOR_BIT_BL1_DEMOTION, sel,
            mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, auth, fa,
            mm.FLAG_ARGS_BIT_BL2_DEMOTION, bl2, mm.FLAG_ARGS_BIT_SECURE_BOOT,
            mm.FLAG_ARGS_BIT_SKIP_SHA256, sigtype, lcs,
            ", ".join(self._VALUE_FORBIDS),
        )
