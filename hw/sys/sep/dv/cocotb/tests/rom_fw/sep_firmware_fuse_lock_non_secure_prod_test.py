# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fuse lock in PROD with the chicken bit blown: device control beats the lifecycle."""

from __future__ import annotations

import pyuvm

from rom_fw.sep_fuse_lock_base import EFUSE_DIR, LC_RAW_PROD, sep_fuse_lock_base


@pyuvm.test()
class sep_firmware_fuse_lock_non_secure_prod_test(sep_fuse_lock_base):
    """PROD + SBOOT_DIS=1 -> unauthenticated boot -> secrets still locked."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_prod_sboot_dis.toml"
    expected_lc_raw = LC_RAW_PROD
    expected_sboot_dis = 1
