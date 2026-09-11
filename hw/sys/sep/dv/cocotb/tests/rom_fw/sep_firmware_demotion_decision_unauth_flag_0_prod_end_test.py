# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END with a BL2 demotion REQUEST pending -> the request is ignored, locked.

Outcome **O1** of the [C15] decision table in
``rom_fw/sep_demotion_decision_base.py``; the PROD_END stimulus it shares with its
siblings is in ``rom_fw/sep_demotion_prod_end_base.py``.

**COVERED-BY-O1: this row adds no new ROM outcome, and that is stated first.**
``rom_main.c`` short-circuits on ``lc_state == LC_STATE_PROD_END`` and returns
having read none of the three manifest demotion inputs, so every PROD_END row of
the tracker lands on the same observable. Three siblings already cover it.

**WHAT THIS ROW ADDS THAT ITS THREE SIBLINGS CANNOT, AND IT IS NOT NOTHING.** It is
the only PROD_END member that plants ``boot_arguments.flag_args`` bit 0 -- the BL2
demotion request. ``auth_flag_0_prod_end`` plants the usage-constraints flag,
``no_flag_prod_end`` plants nothing and ``no_flag_prod_end_sel_bit_set`` plants the
selector bit. So this is the one PROD_END stimulus that carries a LIVE demotion
request through the whole boot and requires the ROM to drop it:

  * a ROM that read ``flag_args`` bit 0 before testing the lifecycle would take the
    ``else if (bl2_demote)`` arm, clear ``lock_demotion``, print
    ``DEMOTE: BL2 deferred, unlocked`` and ``DEMOTE_NOT_LOCKED``, and leave DEMOTE_1
    **entirely unwritten** -- outcome O4. This member forbids all three of those
    strings and requires ``lock == 1`` on BOTH registers, so that ROM fails here on
    the console channel and on the register channel independently;
  * the same bit is also what feeds ``bl2_demotion_decision`` into ``bl0_state`` and
    bit 2 of the boot measurement's ``demotion_bits`` (``rom_main.c``). At PROD_END
    neither is reached, so ``BL2_DEMOTE_DEC=`` is absent and the measurement word is
    ``MEAS_DEMOTE=0x00000002`` -- lock only. **That word is this row's second and
    strongest ROM-observable channel**: the same early read that would produce
    outcome O4 also sets ``demotion_bits`` bit 2, so a ROM with that defect prints
    ``MEAS_DEMOTE=0x00000006``, which is forbidden here. Without it the row would
    rest entirely on absent tokens and on the served-stimulus check.

The stimulus itself is asserted on two channels, because the ROM echoes none of it:
:meth:`check_manifest_stimulus` reads the planted triple back out of the packed
image before the run, and
:meth:`~sep_demotion_decision_base._check_stimulus_served` requires the flash DEVICE
to have returned exactly those bytes. The served ``flag_args`` word is what
separates this run from ``no_flag_prod_end`` at run time; the console cannot.

MARKER SUBSTITUTION. This ROM defines no demotion status code at all, so the
console tokens plus the DEMOTE_1/DEMOTE_2 register probes carry the whole verdict.
The lock requirements are an addition derived from this ROM's own behaviour, and
are disclosed in the entry's ``flow_deviation`` as well.

SCOPE, as for every member of this group: only the DECISION is checked. It also
feeds the KBKDF salt and three SKS UID keys, but BL0 derives none of them.

Needs ``+sep_crypto_edn_force``: PROD_END enforces secure boot (``lifecycle.c``), so
a full RSA-3072 modexp runs on OTBN.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base

# rom_main.c packs demotion_bits as {bl2_demote_m, lock_demotion, demotion_decision}
# and measurement.h echoes the low three bits as MEAS_DEMOTE=. On the PROD_END arm
# none of the manifest inputs is read, so bl2_demote_m stays false and the word is
# lock-only. A ROM that read flag_args bit 0 before testing the lifecycle would set
# bit 2 and print 0x6 instead -- which is why both values appear below.
_MEAS_LOCK_ONLY = "MEAS_DEMOTE=0x00000002"
_MEAS_BL2_COUNTED = "MEAS_DEMOTE=0x00000006"


@pyuvm.test()
class sep_firmware_demotion_decision_unauth_flag_0_prod_end_test(
        sep_demotion_prod_end_base):
    """PROD_END with flag_args[0] set: the BL2 request is dropped, both locked."""

    # The stimulus sets boot_arguments.BL2_demotion = 1 and nothing else, which is
    # flag_args bit 0. The selector bit and the authenticated flag stay clear.
    _SEL = 0
    _AUTH = 0
    _BL2 = 1

    # MEAS_DEMOTE= is the SECOND ROM-observable channel this row has, and the only
    # one on which it differs from a PROD_END row whose BL2 flag is clear. PLD_HASH_OK
    # is required for parity with the PROD members, whose base requires it.
    required_markers = sep_demotion_prod_end_base.required_markers + (
        _MEAS_LOCK_ONLY, "PLD_HASH_OK",
    )
    forbidden_markers = sep_demotion_prod_end_base.forbidden_markers + (
        _MEAS_BL2_COUNTED, "PLD_HASH_FAIL=",
    )
