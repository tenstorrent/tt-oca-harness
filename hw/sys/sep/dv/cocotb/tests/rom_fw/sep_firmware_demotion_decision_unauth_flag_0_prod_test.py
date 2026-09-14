# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, no selector, no BL1 flag, BL2 demotion requested -> DEMOTE_1 UNWRITTEN.

Outcome **O4** of the [C15] decision table in
``rom_fw/sep_demotion_decision_base.py``; the PROD stimulus is shared through
``rom_fw/sep_demotion_prod_base.py``. **Read the decision base first** -- it carries
the mechanism, the seven-outcome collapse map, the register evidence channel and the
disclosed gaps for the whole demotion group.

============================================================================
THIS ROW IS THE ANNOUNCED COLLAPSE SIBLING OF THE COMMITTED O4 MEMBER
============================================================================

``testlists/rom_fw.toml`` already names it: "COLLAPSE NOTE: unauth_flag_0_prod
drives (0, 0, 1) and produces this same O4
outcome." That is correct and is not argued with here. ``rom_main.c`` reaches the
deferred-unlocked arm on ``selector_bits[17] == 0 && flag_args[0] == 1``, and
``usage_constraints.flags`` is never read on that arm, so this row and
``..._auth_flag_0_unauth_flag_0_prod_test`` drive the SAME ROM PATH and produce the
same console and the same register state. **No new ROM path is claimed.**

Two things still separate them, and both are stated rather than implied.

**1. This is the MINIMAL O4, and the pair brackets the ignored input from both
sides.** The committed member sets ``usage_constraints.flags[0] = 1`` and shows the
ROM ignores it; this member leaves it CLEAR and shows the same outcome arises with
the BL2 request alone. A ROM that had made the deferral conditional on the BL1 flag
-- ``if (auth && bl2_demote)`` rather than ``else if (bl2_demote)`` -- would pass the
committed member unchanged and fail HERE, which is the one direction the committed
member cannot test. That is a negative control on input selection, not a second
sample of the same one.

**2. This row adds the measurement channel to O4, which no member of the family had.**
``rom_main.c`` packs ``demotion_bits = decision | (lock << 1) | (bl2_demote_m << 2)``
and ``include/measurement.h`` echoes the low three bits as ``MEAS_DEMOTE=``. On O4 the
word is **0x5** -- decision 1 from the BL2 request, lock 0, request 1 -- and 0x5 is
UNIQUE to O4 among the seven outcomes (O1/O3a/O5 give 0x2, O2a 0x3, O3b 0x6, O2b 0x7).
The other O4 member asserts no measurement value at all, so this is a channel only
this entry provides.

``MEAS_DEMOTE=0x00000007`` is forbidden as well: it is exactly what this stimulus would
produce if ``lock_demotion`` were never cleared. **It is depth, not an independent
check, and saying so matters.** ``rom_record_measurement`` has one call site
(``rom_main.c``), so ``MEAS_DEMOTE=`` prints exactly once per boot; with ``0x5``
already required, the ``0x7`` forbid cannot fail unless the required marker already has.

What the measurement DOES add over the console is a second read of ``lock_demotion`` at
a later point in the program -- the console prints ``DEMOTE_NOT_LOCKED`` from that local
at the register-write block, the measurement packs it afterwards -- so a ROM that
changed the value between those two points fails here. The register probe is the third
reading and the only one taken from hardware. **Precisely, though: ``lock == 0`` is also
the register's RESET value, so the probe shows the lock was never SET rather than that
it was cleared.** The exact transition count below is what turns that into an
observation; see the residual-vacuity note.

**THE UPSTREAM DIVERGENCE DOES NOT BITE THIS MEMBER, AND THAT HAD TO BE CHECKED.**
``demotion_bits`` bit 2 carries the BL2 REQUEST on this ROM and the
BL2 DECISION upstream, so the two ROMs disagree wherever a request is present but does
not decide. That needs ``selector_bits[17] == 1``. Here the selector is CLEAR, so the
``bl2_demotion_decision`` is assigned in exactly the ``else`` arm this stimulus
takes, so bit 2 is 1 either way. **0x5 is therefore the value under both readings
of the field**, and the assertion does not pre-judge the open question.

============================================================================
WHAT THE REGISTER EVIDENCE MUST BE, AND WHY A FINAL READ IS NOT ENOUGH
============================================================================

O4 is the only outcome where ``lc_write_demotion`` is never called, so DEMOTE_1 is left
at its reset value. ``expect_demote_1 = (0, 0)`` IS that reset value, so an end-of-run
read alone is weak evidence -- **for the LOCK half specifically**, which an unresolved
probe would satisfy. The STATE half is already protected: the rails are differentially
encoded and :func:`~sep_demotion_decision_base._decode_demote` raises on ``0b00``, so a
dead state probe fails rather than reading as "not demoted".

Following the committed O4 member, the sample count is pinned EXACTLY at 1
(``demote_changes_min = demote_changes_max = 1``): the monitor must record the reset
sample and nothing else, for the whole simulation including BL1's execution.
**Against the family default this bound is not "stricter" but DISJOINT** -- ``(1, 1)``
and ``(2, None)`` accept no run in common, so the two cannot be ordered on strength, and
the inherited phrase "stricter than the default" is wrong as written. The claim that
does hold, and the one that matters, is that it was not loosened to let this row pass:
the value is forced by the ROM -- ``rom_main.c`` clears ``lock_demotion``, so
``lc_write_demotion`` cannot execute and the monitor is physically unable to record a
second sample -- and ``outcome_for()`` pins ``(1, 1)`` to O4 at import time, so no
member can retune it.

The residual vacuity the committed member discloses applies here identically: with both
registers unwritten this row alone cannot prove the LOCK probes are live. The bound is
the same -- the O2b and PROD_END members drive ``lk1`` and ``lk2`` 0 -> 1 through the
same wiring in the same regression, and so does this batch's own O5 row, whose run
records ``lk1`` 0 -> 1.

============================================================================
PORT FIDELITY
============================================================================

Reference entry ``+UNAUTH_FLAG_0 +SECURE_BOOT_DIS +LC_STATE_PROD``. The packer
turns those into
``boot_arguments.BL2_demotion = 1``, ``usage_constraints.selectors.BL1_demotion = 0``,
``usage_constraints.BL1_demotion = 0`` (no ``+AUTH_FLAG_0``) and
``boot_arguments.secure_boot = 0``, and its ``_build_expected_patterns`` expects
``STATUS: DEMOTION_NOT_SELECTED`` + ``STATUS: DEMOTION_NOT_LOCKED``.

MARKER SUBSTITUTION: this ROM defines no demotion status code
(``grep -n DEMOT bootrom/prod/include/status_values.h`` is empty), so the console
tokens plus the register probes carry the whole verdict, and a register probe is
stronger than a scraped string. SCOPE: only the DECISION is checked; its
KBKDF/SKS/UID consumers have no BL0-side equivalent here.

No ``+sep_crypto_edn_force``: secure boot is off, so the ROM never drives OTBN.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base

# rom_main.c packs demotion_bits as {bl2_demote_m, lock_demotion, demotion_decision};
# measurement.h echoes the low three bits. O4 is the only outcome of the seven whose
# word is 0x5 -- the BL2 request both decided and was counted, and the lock was cleared.
# 0x7 is the same stimulus with lock_demotion left set, i.e. the defect this row exists
# to catch.
_MEAS_DEFERRED_UNLOCKED = "MEAS_DEMOTE=0x00000005"
_MEAS_DEFERRED_STILL_LOCKED = "MEAS_DEMOTE=0x00000007"


@pyuvm.test()
class sep_firmware_demotion_decision_unauth_flag_0_prod_test(sep_demotion_prod_base):
    """PROD, selector clear, BL1 flag clear, BL2 flag set: unlocked, DEMOTE_1 unwritten."""

    # +UNAUTH_FLAG_0 +SECURE_BOOT_DIS +LC_STATE_PROD, and no +SET_SELECTOR_BIT_17 and
    # no +AUTH_FLAG_0. The absent +AUTH_FLAG_0 is the whole
    # difference from the committed O4 member and is what makes this the minimal O4.
    _SEL = 0
    _AUTH = 0
    _BL2 = 1

    demotion_required = ("DEMOTE: BL2 deferred, unlocked", "BL2_DEMOTE_DEC=",
                         "DEMOTE_NOT_LOCKED")
    demotion_values = ("BL2_DEMOTE_DEC=1",)

    # rom_main.c clears lock_demotion, so lc_write_demotion never runs and DEMOTE_1
    # keeps its reset value; DEMOTE_2 is written only on the PROD_END arm.
    expect_demote_1 = (0, 0)
    expect_demote_2 = (0, 0)

    # Exactly one sample -- the reset one -- for the whole simulation. See the
    # docstring: this is what makes "never written" an observation rather than a value
    # that happens to match, and it covers BL1's execution too.
    demote_changes_min = 1
    demote_changes_max = 1

    # The measurement word is this row's second ROM channel and the family's first on
    # O4. 0x7 is the same stimulus with the lock left set.
    required_markers = sep_demotion_prod_base.required_markers + (
        _MEAS_DEFERRED_UNLOCKED,
    )
    forbidden_markers = sep_demotion_prod_base.forbidden_markers + (
        _MEAS_DEFERRED_STILL_LOCKED,
    )
