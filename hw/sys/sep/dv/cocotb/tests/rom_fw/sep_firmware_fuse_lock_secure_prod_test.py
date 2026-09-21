# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fuse lock in PROD with the chicken bit clear: the lifecycle enforces secure boot.

THE CELL. LC_STATE raw 0x1 (PROD), SBOOT_DIS 0. ``secure_boot_enabled()``
(``manifest_load.c``) returns true without consulting the manifest at all here --
the flag is honoured only in TEST_DEV and RMA -- so this cell and its TEST_DEV
sibling reach the same authenticated path for DIFFERENT reasons, and the
``LC=PROD`` echo is what separates them.

The base forbids ``LC=TEST_DEV`` and ``FUSE: SBOOT_DIS: 1``, so a preload that
failed to stage cannot be mistaken for this cell: it would land on TEST_DEV and
fail on the forbidden decode rather than pass on a shared outcome.

This row does NOT re-establish the PROD override itself -- that is
``sep_firmware_cntl_secure_boot_flow_test``, which clears the manifest flag under
PROD and requires the ROM to authenticate anyway. Here the flag is left set, the
lifecycle and the manifest agree, and what the row adds is the fuse lock under
PROD: the console marker, its position between ``MANIFEST_OK`` and the BL1
handoff, and the DUT-side read of the shadow LOCKS register.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_fuse_lock_base import EFUSE_DIR, LC_RAW_PROD, sep_fuse_lock_base


@pyuvm.test()
class sep_firmware_fuse_lock_secure_prod_test(sep_fuse_lock_base):
    """PROD + SBOOT_DIS=0 -> lifecycle-enforced secure boot -> secrets locked."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_prod.toml"
    expected_lc_raw = LC_RAW_PROD
    expected_sboot_dis = 0
