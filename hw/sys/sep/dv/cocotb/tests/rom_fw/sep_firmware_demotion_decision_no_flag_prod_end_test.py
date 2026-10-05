# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END with no demotion request at all -> not demoted, both registers locked.

Outcome O1 of the [S25] outcome table in ``sep_demotion_decision_base.py``; the shared PROD_END
stimulus is in ``sep_demotion_prod_end_base.py``. This member adds no ROM coverage: ``rom_main.c``
takes the PROD_END branch before it reads any manifest demotion input, and
``sep_firmware_demotion_decision_auth_flag_0_prod_end_test`` also covers O1. It is the null
stimulus, all three inputs clear, so unlike the ``sel_bit_set`` sibling it is not a control on the
short-circuit order.

Per run it asserts: ``DEMOTE: PROD_END lock`` and ``DEMOTE_LOCKED`` once each after
``MANIFEST_OK``, with every other [S25] token forbidden (``BL1_DEMOTE=`` and ``BL2_DEMOTE_DEC=``
absent show the non-PROD_END arm did not run); DEMOTE_1 = (0, 1) and DEMOTE_2 = (0, 1), and only
``lc_write_demotion_2()`` at PROD_END locks DEMOTE_2; all three inputs clear in the packed image
and in the bytes the flash device served (``CHK-STIMULUS-SERVED``), the only run-time observable
that differs between the PROD_END members; and raw LC 0x8 decoded as PROD_END, because both slots'
``life_cycle_states`` allow PROD_END only.

Needs ``+esrc_noise_force``: PROD_END enforces secure boot (``lifecycle.c``), so a full RSA-3072
modexp runs on OTBN.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base


@pyuvm.test()
class sep_firmware_demotion_decision_no_flag_prod_end_test(sep_demotion_prod_end_base):
    """PROD_END, no manifest demotion request: not demoted, both registers locked."""

    _SEL = 0
    _AUTH = 0
    _BL2 = 0
