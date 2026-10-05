# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A TEST_DEV part with SIP_DIS read-locked refuses an unsigned image.

A read-locked efuse field returns a sentinel instead of its value, so the ROM
cannot see whether chiplet debug is open. SEP-ROM-SB-025 counts the lock as debug
disabled: failing closed means a lock can only add verification.

Both disable vectors are clear here, so only the lock can explain the refusal.
Same stimulus and checks as ``sep_rom_dbg_lock_sip_dis_refuse_test`` otherwise.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_dbg_lock_sip_dis_refuse_test import (
    _CHIPLET_DBG_BIT,
    _EFUSE_DIR,
    _SIP_DIS_READ_LOCK_BIT,
    sep_rom_dbg_lock_sip_dis_refuse_test,
)


@pyuvm.test()
class sep_rom_dbg_lock_read_locked_refuse_test(sep_rom_dbg_lock_sip_dis_refuse_test):
    """TEST_DEV + SIP_DIS read-locked + manifest secure_boot=0 -> both slots refused."""

    efuse_preload = _EFUSE_DIR / "sep_efuse_lc_test_dev_sip_dis_read_locked.toml"

    def check_disable_vectors(self, sip_dis: int, sys_dis: int, locks: int) -> None:
        assert locks & _SIP_DIS_READ_LOCK_BIT, (
            f"LOCKS is 0x{locks:x}: SIP_DIS_READ_LOCK (bit 7) is clear, so nothing here locks debug"
        )
        assert not (sip_dis | sys_dis) & _CHIPLET_DBG_BIT, (
            f"CHIPLET_DBG is set (SIP_DIS=0x{sip_dis:x}, SYS_DIS=0x{sys_dis:x}), so "
            f"the refusal would not be attributable to the read lock"
        )
