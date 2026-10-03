# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A debug-locked RMA_SiP part boots a validly signed image (PyUVM).

The positive half of the RMA_SiP debug-lock rule (SEP-ROM-SB-025): enforcement
does not make the part unbootable, and the full RSA-3072 chain still admits signed
code. ``sep_rom_dbg_lock_secure_boot_test`` with the OTP moved to ``RMA_SiP`` plus
``SIP_DIS.CHIPLET_DBG``, so with ``sep_rom_rma_sip_dbg_lock_refuse_test`` (``SYS_DIS``)
both vectors are exercised in ``RMA_SiP``.

As there, the shipped image sets ``secure_boot_control``, so the verified boot is
not itself evidence of the lock; the refusal members are. What this adds is that
the RMA lifecycle reaches BL1 through the verified path and that [S18] reports the
lock on a boot that succeeds.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_dbg_lock_secure_boot_test import sep_rom_dbg_lock_secure_boot_test
from rom_fw.sep_rom_dbg_lock_sip_dis_refuse_test import (
    _EFUSE_DIR,
    DBG_LOCK_MARKER,
    DBG_LOCK_VALUE,
)
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_LC_MARKER = "LC=RMA_SIP"


@pyuvm.test()
class sep_rom_rma_dbg_lock_secure_boot_test(sep_rom_dbg_lock_secure_boot_test):
    """RMA_SiP + SIP_DIS.CHIPLET_DBG + signed image: RSA-3072 verifies, BL1 entered."""

    efuse_preload = _EFUSE_DIR / "sep_efuse_lc_rma_sip_chiplet_dbg_sip.toml"
    expected_lc_raw = 0x2
    lc_marker = _LC_MARKER
    required_markers = sep_rom_ot_secure_boot_test.required_markers + (
        _LC_MARKER,
        DBG_LOCK_VALUE,
        DBG_LOCK_MARKER,
    )
