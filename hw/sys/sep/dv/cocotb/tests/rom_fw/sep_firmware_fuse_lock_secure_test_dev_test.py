# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fuse lock in TEST_DEV with the chicken bit clear: the manifest selects secure boot.

The preload senses the same as a blank OTP, so the run cannot show that it was staged.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_fuse_lock_base import EFUSE_DIR, LC_RAW_TEST_DEV, sep_fuse_lock_base


@pyuvm.test()
class sep_firmware_fuse_lock_secure_test_dev_test(sep_fuse_lock_base):
    """TEST_DEV + SBOOT_DIS=0 -> manifest-selected secure boot -> secrets locked."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_test_dev.toml"
    expected_lc_raw = LC_RAW_TEST_DEV
    expected_sboot_dis = 0
