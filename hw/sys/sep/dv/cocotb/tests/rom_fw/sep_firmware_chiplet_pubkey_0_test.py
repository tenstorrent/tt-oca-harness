# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Manifest authenticates against CHIPLET fused key 0, unrevoked -> boots.

Both slots select ``PUBK_SEL_FUSE_KEY_0``; ``CHIPLET_PUBK_HASH0`` holds the dev0 modulus digest.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_chiplet_pubkey_base import sep_chiplet_pubkey_valid_base


@pyuvm.test()
class sep_firmware_chiplet_pubkey_0_test(sep_chiplet_pubkey_valid_base):
    """CHIPLET fused key 0 is programmed and unrevoked -> primary verifies and boots."""

    _CHIPLET_KEY = 0
