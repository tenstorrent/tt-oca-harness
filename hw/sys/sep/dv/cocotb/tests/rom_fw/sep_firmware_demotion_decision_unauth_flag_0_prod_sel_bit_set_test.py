# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, selector bit 17 set, BL1 flag clear, BL2 flag SET -> BL1 wins, not demoted.

Outcome **O3b** of the [C15] decision table in
``rom_fw/sep_demotion_decision_base.py`` -- **the last of the seven outcomes with no
coverage on this platform**, named as such by that file and by
``sep_firmware_demotion_decision_no_flag_prod_sel_bit_set_test``. The PROD stimulus
it shares with the other PROD members is in ``rom_fw/sep_demotion_prod_base.py``.

============================================================================
WHY O3b IS THE ONE THAT CATCHES A REAL CLASS OF BUG
============================================================================

It is the only row of the table where the two demotion flags DISAGREE and the
authenticated one says no:

  ==============================================  ====  ====  ==========  ==========
  testcase                                        auth  bl2   BL1_DEMOTE  DEMOTE_1
                                                                          (dem, lock)
  ==============================================  ====  ====  ==========  ==========
  ``..._auth_flag_0_prod_sel_bit_set`` (O2a)      1     0     1           (1, 1)
  ``..._auth_flag_0_unauth_flag_0_..._set`` (O2b) 1     1     1           (1, 1)
  ``..._no_flag_prod_sel_bit_set`` (O3a)          0     0     0           (0, 1)
  **this one (O3b)**                              **0** **1** **0**       **(0, 1)**
  ==============================================  ====  ====  ==========  ==========

``rom_main.c`` takes the selector arm and copies ``usage_constraints.flags`` bit 0 --
and ONLY that bit -- into ``demotion_reg``. ``flag_args`` bit 0 is read on the same
pass, but only into ``bl2_demotion_decision`` for BL1 to consume; it must not reach
DEMOTE_1. So a ROM that ORed the two flags together, or that fell through to the
``else if (bl2_demote)`` arm when the authenticated flag was clear, produces a
DIFFERENT result on this stimulus and on no other:

  * ORing them gives ``BL1_DEMOTE=1`` and DEMOTE_1 = (1, 1). This member requires
    ``BL1_DEMOTE=0``, forbids ``BL1_DEMOTE=1`` (the base derives that forbid from
    ``_AUTH``) and requires DEMOTE_1 = (0, 1) from the register probe;
  * falling through to the BL2 arm gives ``DEMOTE: BL2 deferred, unlocked``,
    ``DEMOTE_NOT_LOCKED`` and DEMOTE_1 left **entirely unwritten** -- outcome O4.
    All three of those strings are forbidden here and ``lock == 1`` is required, so
    that ROM fails on the console and on the register channel independently.

O3a cannot make either claim: with both flags clear an OR and a copy agree. That is
why this row, not O3a, is the discriminating half of the pair -- and the two differ
in exactly one stimulus bit, which is what makes the comparison a controlled one.

**``BL2_DEMOTE_DEC=1`` is required and ``BL2_DEMOTE_DEC=0`` forbidden.** The BL2
request must still be RECORDED for BL1 while being kept out of the register: the ROM
stores it into ``bl0_state`` unconditionally on this arm and echoes it. A ROM that
suppressed the record whenever the selector bit was set would satisfy every
register assertion here and fail this one.

**AND THE BOOT MEASUREMENT CARRIES THE SAME SPLIT, WHICH IS WHAT SEPARATES THIS ROW
FROM O3a ON THE CONSOLE.** ``rom_main.c`` packs ``demotion_bits`` as
``{bl2_demote_m, lock_demotion, demotion_decision}`` and ``measurement.h`` echoes the
low three bits. Here ``demotion_decision`` is the BL1 flag (clear), the lock is set
and bit 2 carries the BL2 request that did not decide, so the word is
``MEAS_DEMOTE=0x00000006`` -- the only outcome of the seven that produces it. Its O3a
sibling, identical in the register pair and in ``BL1_DEMOTE=``, prints
``0x00000002``. Requiring one and forbidding the other makes the pair mutually
exclusive on a second ROM channel, and catches a ROM that dropped the
decided-versus-requested distinction from the measurement while still writing
DEMOTE_1 correctly.

**THE MEASUREMENT WORD IS WHERE THE FIELD NAME AND THE CODE DISAGREE, AND THIS
MEMBER IS ONE OF ONLY TWO THAT CAN SEE IT.** This ROM assigns
``bl2_demote_m`` unconditionally in the non-PROD_END arm, BEFORE the selector test
(``rom_main.c``), so bit 2 carries the BL2 REQUEST. The upstream
``demotion_kdf_measurement`` assigns
``bl2_demotion_decision`` only inside the ``else`` arm taken when the selector bit is
CLEAR, so there bit 2 carries the BL2 DECISION and this stimulus would produce
``0x00000002``. This ROM's own ``include/measurement.h`` names the field for the
decision while the code supplies the request, so the divergence is internal as well.

**The expectation is derived from THIS ROM's source**, before the run, and the
measurement assertion is an addition rather than a required check. The divergence
between the field name and the value the code supplies is disclosed here rather
than resolved.

============================================================================
DISCLOSURES
============================================================================

MARKER SUBSTITUTION. This ROM defines no demotion status code at all, so the
console tokens plus the DEMOTE_1/DEMOTE_2 register probes carry the whole verdict.

SCOPE: only the DECISION is checked. It also feeds the KBKDF salt and three SKS
UID keys, but BL0 derives none of them and only stores the value for BL1.

``+SECURE_BOOT_DIS`` is ported on all three of its surfaces by
``rom_fw/sep_demotion_prod_base.py`` -- the ``sboot_dis`` eFuse, ``flag_args`` bit 30
and ``signature_type = NO_SIGNATURE``. Read that module's docstring for why dropping
any one of them would silently substitute a backup boot for the stimulus.

No ``+sep_crypto_edn_force``: secure boot is off, so the ROM never drives OTBN.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base

# rom_main.c packs demotion_bits as {bl2_demote_m, lock_demotion, demotion_decision}
# and measurement.h echoes the low three bits as MEAS_DEMOTE=. This row is the only
# outcome of the seven whose word is 0x6: the decision bit is the BL1 flag (clear),
# the lock bit is set, and bit 2 carries the BL2 request that did NOT decide. Its O3a
# sibling, which differs only in that request, prints 0x2.
_MEAS_LOCKED_BL2_COUNTED = "MEAS_DEMOTE=0x00000006"
_MEAS_LOCKED_BL2_ABSENT = "MEAS_DEMOTE=0x00000002"


@pyuvm.test()
class sep_firmware_demotion_decision_unauth_flag_0_prod_sel_bit_set_test(
        sep_demotion_prod_base):
    """PROD, selector set, BL1 flag clear, BL2 flag set: not demoted but locked."""

    # The measurement word is this row's second independent ROM channel, and the one
    # that separates it from its O3a sibling on the CONSOLE rather than only in the
    # register pair -- which the two outcomes share.
    required_markers = sep_demotion_prod_base.required_markers + (
        _MEAS_LOCKED_BL2_COUNTED,
    )
    forbidden_markers = sep_demotion_prod_base.forbidden_markers + (
        _MEAS_LOCKED_BL2_ABSENT,
    )

    # +UNAUTH_FLAG_0 +LC_STATE_PROD +SET_SELECTOR_BIT_17 +SECURE_BOOT_DIS.
    # +UNAUTH_FLAG_0 sets boot_arguments.BL2_demotion,
    # +SET_SELECTOR_BIT_17 sets usage_constraints.selectors.BL1_demotion, and
    # +AUTH_FLAG_0 is absent so usage_constraints.BL1_demotion stays 0.
    _SEL = 1
    _AUTH = 0
    _BL2 = 1

    demotion_required = ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED")
    demotion_values = ("BL1_DEMOTE=0", "BL2_DEMOTE_DEC=1")

    # rom_main.c: the selector arm copies usage_constraints.flags bit 0 (clear) into
    # demotion_reg and lock_demotion keeps its initialiser, so lc_write_demotion(0, 1).
    # DEMOTE_2 is written only on the PROD_END arm, so it stays at its reset value --
    # observable as lock == 0 because the field is write-one-to-set.
    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)
