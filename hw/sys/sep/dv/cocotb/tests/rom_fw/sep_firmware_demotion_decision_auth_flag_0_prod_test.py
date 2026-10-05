# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, BL1_DEMOTION_VALID clear, ENABLE set -> the flag is IGNORED.

Outcome O5 of the [S25] outcome table in ``sep_demotion_decision_base.py``; the shared PROD
stimulus is in ``sep_demotion_prod_base.py``. This is a negative control. ``+AUTH_FLAG_0`` sets
BL1_DEMOTION_ENABLE while BL1_DEMOTION_VALID stays clear, so ``rom_main.c`` does not take the
BL1_VALID arm and discards the request. BL0 prints ``DEMOTE: BL2 deferred, lock non-demoted`` and
writes DEMOTE_1 not demoted, locked. A ROM that read ENABLE without VALID, or ORed the two, writes
``demote = 1`` and fails on ``expect_demote_1 = (0, 1)``.

The O4 sibling also sets ENABLE with VALID clear. A ROM that routes on ENABLE alone fails there
because the register is written at all, and here because it holds the wrong value.
``sep_firmware_demotion_decision_no_flag_prod_test`` drives (sel, auth, bl2) = (0, 0, 0) with
secure boot enforced and reaches the same O5 outcome; this member differs on the demotion inputs
only in ENABLE, which it asserts from the packed image because the ROM does not echo it.

The registers are read at the end of the run. DEMOTE_1 is written locked,
``sep_lifecycle_ctrl.sv`` gates the DEMOTE write-enable on ``~lock``, and
``sep_lifecycle_ctrl.rdl`` defines ``DEMOTE.lock`` as write-one-to-set. No
``+esrc_noise_force``: secure boot is off and ``RSA_EXEC`` is forbidden.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_base import sep_demotion_prod_base


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_prod_test(sep_demotion_prod_base):
    """PROD, BL1_DEMOTION_VALID clear, ENABLE set: request ignored, DEMOTE_1 (0, 1)."""

    _SEL = 0
    _AUTH = 1
    _BL2 = 0

    demotion_required = (
        "DEMOTE: BL2 deferred, lock non-demoted",
        "BL2_DEMOTE_DEC=",
        "DEMOTE_LOCKED",
    )
    demotion_values = ("BL2_DEMOTE_DEC=0",)

    # rom_main.c calls lc_write_demotion(demotion_reg=false, lock=true):
    # demotion_reg keeps its initialiser because the BL1_VALID arm does not run.
    # DEMOTE_2 is written only at PROD_END, and its lock is write-one-to-set, so
    # lock 0 here means it was never written.
    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)
