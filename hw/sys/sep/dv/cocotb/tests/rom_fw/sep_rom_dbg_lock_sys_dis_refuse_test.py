# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A TEST_DEV part with CHIPLET_DBG disabled by SYS_DIS refuses an unsigned image (PyUVM).

The SYS_DIS half of SEP-ROM-SB-025: either disable vector alone locks debug.
Same stimulus and checks as ``sep_rom_dbg_lock_sip_dis_refuse_test``, with
``CHIPLET_DBG`` set in ``SYS_DIS`` and ``SIP_DIS`` clear.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_dbg_lock_sip_dis_refuse_test import (
    _CHIPLET_DBG_BIT,
    _EFUSE_DIR,
    _SIP_DIS_READ_LOCK_BIT,
    _SYS_DIS_READ_LOCK_BIT,
    sep_rom_dbg_lock_sip_dis_refuse_test,
)


@pyuvm.test()
class sep_rom_dbg_lock_sys_dis_refuse_test(sep_rom_dbg_lock_sip_dis_refuse_test):
    """TEST_DEV + SYS_DIS.CHIPLET_DBG + manifest secure_boot=0 -> both slots refused."""

    efuse_preload = _EFUSE_DIR / "sep_efuse_lc_test_dev_chiplet_dbg_sys.toml"

    def check_disable_vectors(self, sip_dis: int, sys_dis: int, locks: int) -> None:
        assert sys_dis & _CHIPLET_DBG_BIT, (
            f"SYS_DIS is 0x{sys_dis:x}: CHIPLET_DBG (bit 1) is clear, so debug is open"
        )
        assert not sip_dis & _CHIPLET_DBG_BIT, (
            f"SIP_DIS is 0x{sip_dis:x}: CHIPLET_DBG is set there too, so this run "
            f"would not isolate SYS_DIS"
        )
        assert not locks & (_SIP_DIS_READ_LOCK_BIT | _SYS_DIS_READ_LOCK_BIT), (
            f"LOCKS is 0x{locks:x}: a disable vector is read-locked, which enforces "
            f"on its own and would hide whether CHIPLET_DBG was read"
        )
