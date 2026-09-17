# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, BL1_DEMOTION_VALID set, ENABLE clear -> not demoted, locked.

Outcome **O3a** of the [S25] decision table in
``rom_fw/sep_demotion_decision_base.py``; the PROD stimulus it shares with the
other three PROD members is in ``rom_fw/sep_demotion_prod_base.py``.

This is the arm where the manifest decides, deciding NOT to demote.
BL1_DEMOTION_VALID is set, so ``rom_main.c`` takes the first arm and
copies ``demotion_control`` BL1_DEMOTION_ENABLE -- which is clear -- into
``demotion_reg``, printing ``BL1_DEMOTE=0``.
``lock_demotion`` keeps its initialiser, so writes DEMOTE_1
**not demoted but LOCKED**.

**It is the exact complement of R3's O2a member on the value channel and its
partner on the lock channel**, which is what makes the pair a real test of the
copy rather than of the branch:

  ==========================================  ==========  ==========  ==========
  testcase                                    flags[0]    BL1_DEMOTE  DEMOTE_1
                                                                      (dem, lock)
  ==========================================  ==========  ==========  ==========
  ``..._auth_flag_0_prod_sel_bit_set`` (O2a)  1           1           (1, 1)
  this one (O3a)                              0           0           **(0, 1)**
  ==========================================  ==========  ==========  ==========

One stimulus bit, one echoed value, one register bit, all three moving together.
A ROM that latched a constant into ``demotion_reg``, or that wrote the register
from the wrong local, passes one of the two and fails the other.

**The lock half is the part the console cannot check.** ``DEMOTE_LOCKED`` is
printed from ``lock_demotion`` (``rom_main.c``), a local computed 30 lines
earlier, so only ``lcc_demote_lock_1_probe_o`` can say the ROM actually locked the
register. Here the lock is set while ``demote`` stays 0, which is the one
combination that separates "locked, not demoted" from "never written" -- and
"never written" is what the O4 sibling produces. Those two rows differ on the
register channel in exactly the ``lock`` bit.

**Collapse note.** ``unauth_flag_30_prod_sel_bit_set`` (no testcase) drives the same
three demotion inputs, so on the demotion path it is
covered-by-O3a. It is not the same stimulus overall: it adds ``+UNAUTH_FLAG_30``
(``skip_SHA256``) and, per ``bootcode_regression.yaml``, carries no
``+SECURE_BOOT_DIS``, so a port of that row would run a signed primary under
enforced secure boot. Neither difference is a demotion input. Outcome
**O3b** (``unauth_flag_0_prod_sel_bit_set``: selector set, BL1 flag clear, BL2
flag SET) has no testcase; it is the case that would fail a ROM which ORed the
``demotion_control`` BL1_DEMOTION_ENABLE with the ``demotion_control`` BL2
request into DEMOTE_1.

No ``+esrc_noise_force``: secure boot is off, so the ROM never drives OTBN.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base


@pyuvm.test()
class sep_firmware_demotion_decision_no_flag_prod_sel_bit_set_test(sep_demotion_prod_base):
    """PROD, selector set, BL1 flag clear: DEMOTE_1 not demoted but locked."""

    # +LC_STATE_PROD +SET_SELECTOR_BIT_17, no +AUTH_FLAG_0 and no +UNAUTH_FLAG_0
    # (bootcode_regression.yaml).
    _SEL = 1
    _AUTH = 0
    _BL2 = 0

    demotion_required = ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED")
    demotion_values = ("BL1_DEMOTE=0", "BL2_DEMOTE_DEC=0")

    # rom_main.c lc_write_demotion(demotion_reg=false, lock=true). DEMOTE_2 is
    # written only, i.e. only at PROD_END.
    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)
