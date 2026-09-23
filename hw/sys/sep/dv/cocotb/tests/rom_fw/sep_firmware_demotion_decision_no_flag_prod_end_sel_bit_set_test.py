# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END + BL1_DEMOTION_VALID set -> the selector is PREEMPTED, both locked.

Outcome **O1** of the [S25] decision table in
``rom_fw/sep_demotion_decision_base.py``; the PROD_END stimulus it shares with its
sibling is in ``rom_fw/sep_demotion_prod_end_base.py``.

**COVERED-BY-O1 ON THE OUTCOME, BUT NOT ON WHAT A FAILURE WOULD MEAN, and the
difference is this row's entire justification.** ``rom_main.c`` returns before
any manifest demotion input is read, so at PROD_END every combination of the three
produces the same observable, which
``sep_firmware_demotion_decision_auth_flag_0_prod_end_test`` covers. This row adds
no ROM path. What it adds is a **negative control on the short-circuit ORDER**:

  * BL1_DEMOTION_VALID is SET. If did not preempt, the
    ROM would take the first arm of the ``else``, copy ``demotion_control``
    bit 0 into ``demotion_reg``, and produce outcome **O3a** -- which differs from
    O1 on four independent observables at once: ``BL1_DEMOTE=0`` present,
    ``BL2_DEMOTE_DEC=0`` present, ``DEMOTE: PROD_END lock`` absent, and DEMOTE_2
    left unwritten (lock 0) instead of locked;
  * all four of those are asserted here. ``BL1_DEMOTE=`` and ``BL2_DEMOTE_DEC=``
    are forbidden by the family base, because they are ``DEMOTION_TOKENS`` this
    outcome does not require; ``DEMOTE: PROD_END lock`` is required exactly once
    and after ``MANIFEST_OK``; and ``expect_demote_2 = (0, 1)`` requires the
    register that only ``rom_main.c`` can write;
  * and BL1_DEMOTION_VALID itself is asserted on TWO channels -- the packed
    artefact and the bytes the flash DEVICE served
    (``CHK-STIMULUS-SERVED``). The second is what makes this row's stimulus differ
    from its two O1 siblings' at RUN time and not merely offline, which matters
    precisely because their consoles are identical.

Neither of the other two PROD_END rows can make that claim. R3's
``auth_flag_0_prod_end`` sets ``demotion_control`` BL1_DEMOTION_ENABLE with the selector CLEAR, so the ROM
would ignore the flag under either ordering; ``no_flag_prod_end`` leaves all three
inputs clear, so the two orderings agree exactly. **BL1_DEMOTION_VALID is the one
manifest input whose value changes the non-PROD_END outcome on its own, which is
why setting it is what turns a duplicate stimulus into an ordering test.**

That said, the claim is bounded and is not "this row covers a new ROM path". It is: same
outcome, same code path, one more defect class excluded.

There is no architected demotion status code on this ROM, so the console tokens plus the
register channel are the substitution; the DEMOTE_1/DEMOTE_2 lock requirements are an
ADDITION derived from ``rom_main.c``.

Needs ``+esrc_noise_force``: PROD_END enforces secure boot
(``lifecycle.c``), so a full RSA-3072 modexp runs on OTBN.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base


@pyuvm.test()
class sep_firmware_demotion_decision_no_flag_prod_end_sel_bit_set_test(sep_demotion_prod_end_base):
    """PROD_END with BL1_DEMOTION_VALID set: the request is never consulted."""

    # +LC_STATE_END_PROD +SET_SELECTOR_BIT_17, no +AUTH_FLAG_0 and no
    # +UNAUTH_FLAG_0 (bootcode_regression.yaml).
    _SEL = 1
    _AUTH = 0
    _BL2 = 0
