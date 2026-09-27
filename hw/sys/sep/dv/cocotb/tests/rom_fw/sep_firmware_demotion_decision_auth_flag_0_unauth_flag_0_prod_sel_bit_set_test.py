# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, BL1_DEMOTION_VALID set, BOTH demotion flags set -> BL1 wins and locks.

Outcome **O2b** of the [S25] decision table in
``rom_fw/sep_demotion_decision_base.py``; the PROD stimulus it shares with the
other three PROD members is in ``rom_fw/sep_demotion_prod_base.py``.

**THIS IS THE PRECEDENCE TEST, and it is the only member of the family that can
be one.** Both requests are present at once: ``demotion_control`` BL1_DEMOTION_ENABLE
asks BL0 to demote now, and ``demotion_control`` BL2 request asks for the
decision to be deferred to BL2. ``rom_main.c`` resolves it -- the selector
bit routes into the first arm, so ``demotion_reg`` is taken from ``demotion_control`` BL1_DEMOTION_ENABLE
 and ``lock_demotion`` is never touched. The deferral arm at
 is an ``else if`` and is therefore unreachable in this run.

The falsifying claim is on the LOCK bit. A ROM that let the ``demotion_control`` BL2 request reach
``lock_demotion`` -- by testing it before BL1_DEMOTION_VALID, or by clearing the
lock whenever the BL2 flag is set -- would produce ``DEMOTE_NOT_LOCKED`` and
``lcc_demote_lock_1_probe_o == 0``, i.e. outcome O4. **This member requires
DEMOTE_1 to read (demote 1, lock 1) with ``DEMOTE_LOCKED`` on the console and
``DEMOTE_NOT_LOCKED`` forbidden, so that ROM fails here and only here.** R3's O2a
sibling cannot make the claim: it leaves the ``demotion_control`` BL2 request clear, so nothing is
competing with BL1_DEMOTION_VALID.

**The ROM resolves more than a flag-only check can see.** A checker
inspects the BL2 request only when BL1_DEMOTION_VALID is CLEAR
(``sep_demotion_uid_checker.py``); with it set it looks at
``AUTH_FLAG_0`` alone, so O2a and O2b produce an identical
observable list and could not be told apart. This
ROM can, because ``rom_main.c`` prints ``BL2_DEMOTE_DEC=`` unconditionally on
every non-PROD_END arm, carrying the value stored for BL1. Porting
a flag-only pattern list would throw that resolution away, so
this member additionally requires ``BL2_DEMOTE_DEC=1`` and forbids
``BL2_DEMOTE_DEC=0`` -- which is what stops it accepting O2a's console. This is a
stronger assertion, made here rather than
presented as parity.

The distinction matters beyond bookkeeping: ``bl2_demotion_decision`` is what BL0
hands to BL1 (``rom_main.c``), so "BL1 demotes now" and "BL1 demotes now AND
BL2 was also asked to" are different states to hand over, and only the second is
exercised here.

No ``+esrc_noise_force``: secure boot is off, so the ROM never drives OTBN.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_unauth_flag_0_prod_sel_bit_set_test(
    sep_demotion_prod_base
):
    """PROD, selector set, both flags set: DEMOTE_1 demoted and locked, BL2 dec 1."""

    # +LC_STATE_PROD +SET_SELECTOR_BIT_17 +AUTH_FLAG_0 +UNAUTH_FLAG_0
    # (bootcode_regression.yaml).
    _SEL = 1
    _AUTH = 1
    _BL2 = 1

    demotion_required = ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED")
    demotion_values = ("BL1_DEMOTE=1", "BL2_DEMOTE_DEC=1")

    # rom_main.c lc_write_demotion(demotion_reg=true, lock=true). The lock is
    # the load-bearing half here -- see the docstring. DEMOTE_2 is written only at, i.e. only at PROD_END.
    expect_demote_1 = (1, 1)
    expect_demote_2 = (0, 0)
