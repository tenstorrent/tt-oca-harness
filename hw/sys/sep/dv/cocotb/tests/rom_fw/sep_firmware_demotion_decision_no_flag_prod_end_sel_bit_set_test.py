# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END + BL1_DEMOTION_VALID set -> the selector is PREEMPTED, both locked.

Outcome O1 of the [S25] outcome table in ``sep_demotion_decision_base.py``; the shared PROD_END
stimulus is in ``sep_demotion_prod_end_base.py``. ``rom_main.c`` takes the PROD_END branch before
it reads any manifest demotion input, so every input combination gives the O1 outcome, which
``sep_firmware_demotion_decision_auth_flag_0_prod_end_test`` also covers. This member adds no ROM
path. It is a negative control on the short-circuit order.

BL1_DEMOTION_VALID is set. If PROD_END did not preempt it, the ROM would take the BL1_VALID arm
and produce O3a: ``BL1_DEMOTE=0`` and ``BL2_DEMOTE_DEC=0`` present, ``DEMOTE: PROD_END lock``
absent, DEMOTE_2 unlocked. All four are checked: the base forbids the two tokens, ``DEMOTE:
PROD_END lock`` is required once after ``MANIFEST_OK``, and ``expect_demote_2 = (0, 1)`` requires
the ``lc_write_demotion_2()`` write. BL1_DEMOTION_VALID is asserted on the packed image and on the
bytes the flash device served (``CHK-STIMULUS-SERVED``), because the three PROD_END consoles are
identical. BL1_DEMOTION_VALID is the one input that changes the non-PROD_END outcome on its own,
so only this PROD_END member tests the order.

The console tokens and the register channel carry the evidence. Needs ``+esrc_noise_force``:
PROD_END enforces secure boot (``lifecycle.c``), so a full RSA-3072 modexp runs on OTBN.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base


@pyuvm.test()
class sep_firmware_demotion_decision_no_flag_prod_end_sel_bit_set_test(sep_demotion_prod_end_base):
    """PROD_END with BL1_DEMOTION_VALID set: the request is never consulted."""

    # OCAH plusargs: +LC_STATE_END_PROD +SET_SELECTOR_BIT_17, no +AUTH_FLAG_0 and
    # no +UNAUTH_FLAG_0.
    _SEL = 1
    _AUTH = 0
    _BL2 = 0
