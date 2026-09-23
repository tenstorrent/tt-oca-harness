# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END with no demotion request at all -> not demoted, both registers locked.

All three manifest demotion inputs are clear. Needs ``+sep_crypto_edn_force``:
PROD_END enforces secure boot, so a full RSA-3072 modexp runs on OTBN.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_demotion_prod_end_base import sep_demotion_prod_end_base


@pyuvm.test()
class sep_firmware_demotion_decision_no_flag_prod_end_test(
        sep_demotion_prod_end_base):
    """PROD_END, no manifest demotion request: not demoted, both registers locked."""

    _SEL = 0
    _AUTH = 0
    _BL2 = 0
