# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, BL1_DEMOTION_VALID set, ENABLE clear -> not demoted, locked.

Outcome **O3a** of the decision table in ``rom_fw/sep_demotion_decision_base.py``; the shared PROD
stimulus is in ``rom_fw/sep_demotion_prod_base.py``. BL1_DEMOTION_VALID is set, so the ROM copies
the clear BL1_DEMOTION_ENABLE bit into ``demotion_reg``, prints ``BL1_DEMOTE=0`` and writes
DEMOTE_1 not demoted but locked. With the O2a member it tests the copy, not the branch:

  ==========================================  ==========  ==========  ==========
  testcase                                    BL1_ENABLE  BL1_DEMOTE  DEMOTE_1
                                                                      (dem, lock)
  ==========================================  ==========  ==========  ==========
  ``..._auth_flag_0_prod_sel_bit_set`` (O2a)  1           1           (1, 1)
  this one (O3a)                              0           0           **(0, 1)**
  ==========================================  ==========  ==========  ==========

``DEMOTE_LOCKED`` echoes a local in ``rom_main.c``, so only ``lcc_demote_lock_1_probe_o`` proves
the lock; the lock bit alone separates this row from O4, where DEMOTE_1 is never written.
``sep_firmware_demotion_bl1_disable_secure_prod_test`` covers O3a with a signed primary, and
``sep_firmware_demotion_bl1_disable_over_bl2_request_prod_test`` covers O3b.

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
