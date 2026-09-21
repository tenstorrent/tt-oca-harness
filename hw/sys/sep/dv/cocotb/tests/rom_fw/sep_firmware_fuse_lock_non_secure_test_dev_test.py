# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fuse lock in TEST_DEV with the chicken bit blown: device control wins.

THE CELL. LC_STATE raw 0x0 (TEST_DEV), SBOOT_DIS 1. ``secure_boot_enabled()``
short-circuits on ``sboot_dis`` before it looks at the manifest or the lifecycle
(``manifest_load.c``), so this cell boots unauthenticated even though the signed
manifest asks for secure boot -- a flag the base asserts is set, which is what
makes the outcome attributable to the fuse rather than to a permissive image.

WHAT SEPARATES IT FROM ITS PROD SIBLING, which reaches the same non-secure
outcome. Only the ``LC=`` echo: this row requires ``LC=TEST_DEV`` and forbids
``LC=PROD``, and the sibling does the reverse. And what separates it from
``sep_firmware_device_cntl_non_secure_boot_flow_test``, which is the PROD half of
the same fuse: that test exists to show the fuse beats the lifecycle, and its
docstring says TEST_DEV would prove nothing there because the manifest flag
alone could explain a non-secure boot. Here the flag is SET, so it cannot: the
fuse is the only input asking to skip authentication, and this row is the fuse
against a manifest that disagrees.

THE HASH STILL RUNS. With secure boot off, ``sha256_checks_enabled()`` keeps the
manifest and payload hash checks unless the manifest sets ``SKIP_SHA256``, and
TEST_DEV is the only lifecycle where that opt-out is even consulted. The base
asserts the bit is clear, requires ``MANIFEST_HASH_OK`` and forbids
``SHA256_CHECKS_DISABLED``, so this row also establishes that an unauthenticated
TEST_DEV boot is still integrity-checked.

Cheapest of the four -- no RSA, so no ``+sep_crypto_edn_force`` and a much
shorter run -- which is why it was the first of the group to be run end to end.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_fuse_lock_base import EFUSE_DIR, LC_RAW_TEST_DEV, sep_fuse_lock_base


@pyuvm.test()
class sep_firmware_fuse_lock_non_secure_test_dev_test(sep_fuse_lock_base):
    """TEST_DEV + SBOOT_DIS=1 -> unauthenticated boot -> secrets still locked."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_test_dev_sboot_dis.toml"
    expected_lc_raw = LC_RAW_TEST_DEV
    expected_sboot_dis = 1
