# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, BL1_DEMOTION_VALID clear, BL2 demotion requested -> DEMOTE_1 left UNWRITTEN.

Outcome **O4** of the [S25] decision table in
``rom_fw/sep_demotion_decision_base.py``; the PROD stimulus it shares with the
other three PROD members is in ``rom_fw/sep_demotion_prod_base.py``.

**THIS IS THE HIGHEST-VALUE ROW OF THE WHOLE DEMOTION GROUP.** It is the only one
of the seven outcomes where:

  * ``lock_demotion`` goes false (``rom_main.c``) -- on every other path it
    keeps its initialiser;
  * ``DEMOTE_NOT_LOCKED`` is printed  instead of ``DEMOTE_LOCKED``;
  * ``lc_write_demotion`` is **never called**, because is false, so
    DEMOTE_1 is left entirely unwritten at its reset value.

``+AUTH_FLAG_0`` is also set and is IGNORED, for the same reason as in the O5
sibling: ``demotion_control`` BL1_DEMOTION_VALID is clear, so ``rom_main.c`` does not take
the first arm and ``demotion_control`` is never read. The deferral is
decided by the ``demotion_control`` BL2 request alone.

**THE UNWRITTEN REGISTER IS ASSERTED THROUGH THE TRANSITION RECORD, NOT THROUGH
AN END-OF-RUN READ, AND THAT IS DELIBERATE.** ``expect_demote_1 = (0, 0)`` is
also the reset value, so a final-value read alone would be satisfied by a probe
that never resolved -- the base says as much for DEMOTE_2 at its
``_check_demote_registers`` disclosure. This member therefore pins the sample
count EXACTLY (``demote_changes_min = demote_changes_max = 1``): the monitor must
record the reset sample and **nothing else**, for the entire simulation. That is
strictly stronger than the family default ``>= 2``, not a relaxation of it, and
it is the reason the base's bound is parameterised rather than lowered.

It also discharges a caveat R3 recorded for exactly this testcase. O4 is the only
outcome with ``lock == 0``, and ``sep_lifecycle_ctrl.sv`` derive
the DEMOTE field's software write-enable from ``~lock``, so on O4 the register
stays writeable by later software. R3 judged an end-of-run read sound "for these
two members, whose runs stop at the BL1 handoff" -- but BL1 is not a stub here:
``dv/fw/tests/bl1_pass_test/bl1_pass_test.c`` runs to completion and the harness
gates on the PASS it writes. An exact transition count covers the whole run
including BL1, so this member does not rely on that assumption at all.

**Residual vacuity, disclosed.** With both registers unwritten, this member alone
cannot prove the LOCK probes are live -- an all-zero lock probe would satisfy it.
Two things bound that. The ``state`` rails are checked per run: they are
differentially encoded ``{~demote, demote}`` and
:func:`~sep_demotion_decision_base._decode_demote` raises on ``0b00``, so a dead
or X state probe fails rather than reading as "not demoted". And the lock probes
are demonstrably live in the same regression: the O2b sibling drives
``lk1`` 0 -> 1 and R3's PROD_END member drives ``lk2`` 0 -> 1 through the same
wiring. The cross-member argument is stated here rather than left implicit.

No ``+esrc_noise_force``: secure boot is off, so the ROM never drives OTBN.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_unauth_flag_0_prod_test(sep_demotion_prod_base):
    """PROD, selector clear, BL2 flag set: deferral unlocked, DEMOTE_1 unwritten."""

    # +LC_STATE_PROD +AUTH_FLAG_0 +UNAUTH_FLAG_0, no +SET_SELECTOR_BIT_17
    # (bootcode_regression.yaml).
    _SEL = 0
    _AUTH = 1
    _BL2 = 1

    demotion_required = ("DEMOTE: BL2 deferred, unlocked", "BL2_DEMOTE_DEC=", "DEMOTE_NOT_LOCKED")
    demotion_values = ("BL2_DEMOTE_DEC=1",)

    # Neither register is written: rom_main.c is false so never runs, and
    # is PROD_END-only. Both therefore read their reset value (0, 0).
    expect_demote_1 = (0, 0)
    expect_demote_2 = (0, 0)

    # The whole simulation must contain exactly ONE probe sample -- the reset one.
    # See the docstring: this is what makes "never written" an observation rather
    # than a value that happens to match, and it covers BL1's execution too.
    demote_changes_min = 1
    demote_changes_max = 1
