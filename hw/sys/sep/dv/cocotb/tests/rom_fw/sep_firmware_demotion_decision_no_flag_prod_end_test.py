# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END with no demotion request at all -> not demoted, both registers locked.

Outcome **O1** of the [C15] decision table in
``rom_fw/sep_demotion_decision_base.py``; the PROD_END stimulus it shares with its
sibling is in ``rom_fw/sep_demotion_prod_end_base.py``.

**COVERED-BY-O1, AND THIS ROW ADDS NO ROM COVERAGE. Stated first because it is the
honest claim and burying it would be the whole problem.** ``rom_main.c``
returns before any of the three manifest demotion inputs is read, so at PROD_END
every combination of them produces this same outcome, which
``sep_firmware_demotion_decision_auth_flag_0_prod_end_test`` covers. This row drives
the *baseline* combination -- all three inputs clear -- which is the one
combination for which the PROD_END short-circuit is not even load-bearing: a ROM
that evaluated ``selector_bits[17]`` first would take the ``else`` at
``rom_main.c``, and the only difference would be the console tokens and
DEMOTE_2. So unlike its ``sel_bit_set`` sibling, this member is not a negative
control on the short-circuit ORDER; it is the null stimulus.

What it does still assert, per run and on both channels:

  * that a part at PROD_END with a manifest that asks for nothing is **still**
    locked down -- ``DEMOTE: PROD_END lock`` (``rom_main.c``) and
    ``DEMOTE_LOCKED``, each exactly once and after ``MANIFEST_OK``,
    with **every other [C15] string forbidden**. ``BL1_DEMOTE=`` and
    ``BL2_DEMOTE_DEC=`` absent is the direct observable that the ``else`` arm
    never ran;
  * DEMOTE_1 = (demote 0, lock 1) **and DEMOTE_2 = (demote 0, lock 1)** read from
    the lifecycle controller. DEMOTE_2 locked is producible by no other row of the
    table: ``rom_main.c`` is the ROM's only ``lc_write_demotion_2`` call;
  * that all three manifest inputs really are clear -- read back from the packed
    image before the run AND required of the bytes the flash DEVICE served
    (``CHK-STIMULUS-SERVED``). Those two assertions are what distinguish this row
    from its two O1 siblings, since the ROM's console cannot: all three PROD_END
    rows print byte-identical demotion output, and the served ``selector_bits``
    word is the only run-time observable on which they differ;
  * that the ROM decoded raw LC 0x8 as PROD_END, because both slots'
    ``life_cycle_states`` are narrowed to PROD_END only and
    ``manifest_load.c`` refuses the manifest otherwise.

The reference expects only ``STATUS: DEMOTION_NOT_SELECTED`` for the PROD_END row
and appends no lock expectation at all (``sep_demotion_uid_checker.py``).
There is no architected demotion status code on this ROM, so the console tokens
plus the register channel are the substitution -- and the DEMOTE_1/DEMOTE_2 lock
requirements are an ADDITION derived from this ROM (``rom_main.c``), not a port of
anything the reference checks.

Needs ``+sep_crypto_edn_force``: PROD_END enforces secure boot
(``lifecycle.c``), so a full RSA-3072 modexp runs on OTBN. The RSA
assertions are untouched.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base


@pyuvm.test()
class sep_firmware_demotion_decision_no_flag_prod_end_test(sep_demotion_prod_end_base):
    """PROD_END, no manifest demotion request: not demoted, both registers locked."""

    # +LC_STATE_END_PROD only -- no +SET_SELECTOR_BIT_17, +AUTH_FLAG_0 or
    # +UNAUTH_FLAG_0 (bootcode_regression.yaml).
    _SEL = 0
    _AUTH = 0
    _BL2 = 0
