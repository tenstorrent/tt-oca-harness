# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A debug-locked RMA_SiP part refuses an unsigned image.

The RMA half of SEP-ROM-SB-025: in ``RMA_SiP``, as in ``TEST_DEV``, secure boot is enforced
once chiplet-scope debug is disabled. ``plat_is_secure_boot_active()`` applies the [S18]
lock to every state ``lc_state_follows_debug_lock()`` names; ``RMA_CHIPLET`` is not one
(``sep_rom_rma_chiplet_dbg_lock_boot_test``). The stimulus is that of
``sep_rom_dbg_lock_sys_dis_refuse_test`` at raw LC ``0x2``: ``CHIPLET_DBG`` set in
``SYS_DIS``, ``SIP_DIS`` and ``SBOOT_DIS`` clear, ``secure_boot_control`` cleared on both
slots. Both slots must be refused with ``OCA_FAIL_SIGNATURE_CLASS_CONTROL`` and [S18] must
report ``SBOOT_DBG_LOCK``. ``sep_rom_rma_dbg_open_boot_test`` is the negative control.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_rom_dbg_lock_sip_dis_refuse_test import _EFUSE_DIR
from rom_fw.sep_rom_dbg_lock_sys_dis_refuse_test import sep_rom_dbg_lock_sys_dis_refuse_test


@pyuvm.test()
class sep_rom_rma_sip_dbg_lock_refuse_test(sep_rom_dbg_lock_sys_dis_refuse_test):
    """RMA_SiP + SYS_DIS.CHIPLET_DBG + manifest secure_boot=0 -> both slots refused."""

    efuse_preload = _EFUSE_DIR / "sep_efuse_lc_rma_sip_chiplet_dbg_sys.toml"
    expected_lc_raw = 0x2
    lc_marker = "LC=RMA_SIP"
