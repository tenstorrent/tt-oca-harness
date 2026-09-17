# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, selector bit 17 CLEAR, BL1 demotion flag set -> the flag is IGNORED.

Outcome **O5** of the [C15] decision table in
``rom_fw/sep_demotion_decision_base.py``; the PROD stimulus it shares with the
other three PROD members is in ``rom_fw/sep_demotion_prod_base.py``. Read the
first of those for the mechanism and the second for ``+SECURE_BOOT_DIS``.

**THIS IS A NEGATIVE CONTROL, AND THAT IS ITS WHOLE VALUE.** ``+AUTH_FLAG_0``
sets ``usage_constraints.flags`` bit 0 -- the BL1 demotion request -- while
``selector_bits`` bit 17 stays clear. ``rom_main.c`` therefore does not take
the first arm, and the request is discarded: BL0
takes the ``else``, prints ``DEMOTE: BL2 deferred, lock non-demoted``
and writes DEMOTE_1 **not demoted, locked**.

A ROM that read ``flags[0]`` without first testing the selector bit -- or that
ORed the two -- would write ``demote = 1`` here and this testcase would fail on
the register channel. **The falsifying claim is ``expect_demote_1 = (0, 1)``
against a manifest that asked for demotion.**

Two members of the family have that property and neither of the other five does:
this one and the O4 sibling, which also sets ``flags[0]`` with the selector clear
and would catch a ROM that routed into the selector arm on ``flags[0]`` alone.
They are not interchangeable, because they catch it through different failures --
here a WRONG VALUE in a written register, there a register written AT ALL. The
O2a member sets both bits, so its ``demote = 1`` is correct under either reading,
and the three PROD_END members never reach the ``else``.

The reference makes the same distinction for the same reason: with the selector
bit clear its checker expects ``STATUS: DEMOTION_NOT_SELECTED`` regardless of
``+AUTH_FLAG_0`` (``sep_demotion_uid_checker.py``, which reads
``UNAUTH_FLAG_0`` and never ``AUTH_FLAG_0``).

**Collapse note.** ``no_flag_prod`` (no testcase) drives
(sel, auth, bl2) = (0, 0, 0) and produces this same O5 outcome, so it is
covered-by-O5. On the DEMOTION inputs the two differ only in
``usage_constraints.flags`` bit 0 -- which this member asserts from the packed
image before the run, because the ROM never echoes it on this path. They are not
identical stimuli overall: ``bootcode_regression.yaml`` carries no
``+SECURE_BOOT_DIS``, so a port of that row would run a SIGNED primary with
secure boot enforced, and this one runs an unsigned primary with the chicken bit
burned. What THIS row adds over it on the demotion path is the falsification
above; what it does not add is a second ROM path.

Both members' registers are read at the END of simulation, after BL1 has run to
completion. That is sound here for a reason worth stating: DEMOTE_1 is written
locked, ``sep_lifecycle_ctrl.sv`` derives the DEMOTE field's
software write-enable from ``~lock``, and the LOCK field is
write-one-to-set with no hardware clear (``sep_lifecycle_ctrl.rdl:23-36``), so
neither field can be walked back by BL1 or by anything after it.

No ``+sep_crypto_edn_force``: secure boot is off, so the ROM never drives OTBN.
``RSA_VERIFY_START`` is forbidden, so if that ever changed this entry would fail
rather than silently start needing the shortcut.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_prod_test(sep_demotion_prod_base):
    """PROD, selector bit clear, BL1 flag set: request ignored, DEMOTE_1 (0, 1)."""

    # +LC_STATE_PROD +AUTH_FLAG_0, no +SET_SELECTOR_BIT_17 and no +UNAUTH_FLAG_0
    # (bootcode_regression.yaml).
    _SEL = 0
    _AUTH = 1
    _BL2 = 0

    demotion_required = (
        "DEMOTE: BL2 deferred, lock non-demoted",
        "BL2_DEMOTE_DEC=",
        "DEMOTE_LOCKED",
    )
    demotion_values = ("BL2_DEMOTE_DEC=0",)

    # rom_main.c lc_write_demotion(demotion_reg=false, lock=true). demotion_reg
    # keeps its initialiser because the selector arm never runs. DEMOTE_2 is
    # written only at PROD_END, so lock 0 here means never written -- sound
    # because the field is write-one-to-set (sep_lifecycle_ctrl.rdl:31-36).
    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)
