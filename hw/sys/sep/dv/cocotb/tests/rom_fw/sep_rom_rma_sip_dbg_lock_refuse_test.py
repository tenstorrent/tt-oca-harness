# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A debug-locked RMA_SiP part refuses an unsigned image (PyUVM).

The RMA half of SEP-ROM-SB-025: in ``RMA_SiP``, as in ``TEST_DEV``, secure boot
is enforced once chiplet-scope debug is disabled. ``plat_is_secure_boot_active()``
applies the [S18] debug lock to every lifecycle state
``lc_state_follows_debug_lock()`` names; ``RMA_CHIPLET`` is not one of them (see
``sep_rom_rma_chiplet_dbg_lock_boot_test``).

Stimulus is ``sep_rom_dbg_lock_sys_dis_refuse_test``'s with the lifecycle moved to
``RMA_SiP`` (raw ``0x2``): ``CHIPLET_DBG`` set in ``SYS_DIS``, ``SIP_DIS`` clear,
``SBOOT_DIS`` clear, and both slots' ``secure_boot_control`` cleared. ``RMA_SiP``
does not apply ``SYS_DIS`` to feature control, so this is the vector only the
fuse shadow still records. Both slots are refused with
``OCA_FAIL_SIGNATURE_CLASS_CONTROL`` and [S18] reports ``SBOOT_DBG_LOCK``.

``sep_rom_rma_dbg_open_boot_test`` is the negative control: the same lifecycle
with debug open boots an unsigned image.
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
