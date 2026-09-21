# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fuse lock in PROD with the chicken bit blown: device control beats the lifecycle.

THE CELL. LC_STATE raw 0x1 (PROD), SBOOT_DIS 1 -- the highest-precedence input of
``secure_boot_enabled()`` against the second (``manifest_load.c``). PROD on its
own forces authentication and the signed manifest also asks for it, so the fuse
is the only one of the three inputs asking to skip it, and the unauthenticated
boot this row observes is attributable to nothing else.

WHAT SEPARATES IT FROM ITS TEST_DEV SIBLING, which reaches the same non-secure
outcome: the ``LC=`` echo alone, and both rows forbid the other's decode. What
separates it from ``sep_firmware_device_cntl_non_secure_boot_flow_test``, which
stages the SAME preload and the same image: that test grades the override and
stops there -- it does not look at the fuse lock, the manifest hash, or the
lifecycle usage constraint, and it does not forbid the other lifecycles. This row
adds the fuse-lock evidence (the console marker, its position between
``MANIFEST_OK`` and the BL1 handoff, and the DUT-side read of the shadow LOCKS
register), requires ``MANIFEST_HASH_OK``, and closes the lifecycle down to PROD
by forbidding every other decode.

THE HASH IS NOT OPTIONAL HERE. ``sha256_checks_enabled()`` consults the
manifest's ``SKIP_SHA256`` bit only in TEST_DEV, so under PROD the hash checks
run whatever the manifest asks. That is why ``MANIFEST_HASH_OK`` is required on
this row for a structural reason rather than because the base asserted the flag
clear, and it is the one property this cell has that its TEST_DEV sibling gets
only by assertion.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_fuse_lock_base import EFUSE_DIR, LC_RAW_PROD, sep_fuse_lock_base


@pyuvm.test()
class sep_firmware_fuse_lock_non_secure_prod_test(sep_fuse_lock_base):
    """PROD + SBOOT_DIS=1 -> unauthenticated boot -> secrets still locked."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_prod_sboot_dis.toml"
    expected_lc_raw = LC_RAW_PROD
    expected_sboot_dis = 1
