# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Manifest authenticates against CHIPLET fused key 1, unrevoked -> boots.

The positive member of the chiplet fused-key pair for key 1. Both manifest slots select
``PUBK_SEL_FUSE_KEY_1`` and are re-signed with dev0, and ``CHIPLET_PUBK_HASH1`` holds SHA-256 of
that modulus, so the primary verifies and the ROM boots without reading the backup.

Matched pair with ``sep_firmware_chiplet_pubkey_1_revoke_test``: both build the flash image from
``select_chiplet_fuse_key(buf, 1)`` and differ only in ``CHIPLET_PUBK_REVOKE`` bit 17. Bit clear
boots from the primary; bit set refuses both manifests with ``MANIFEST_ERR_KEY_REVOKED`` before
``RSA_EXEC``. The scenario and assertions are in ``sep_chiplet_pubkey_base``.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_chiplet_pubkey_base import sep_chiplet_pubkey_valid_base


@pyuvm.test()
class sep_firmware_chiplet_pubkey_1_test(sep_chiplet_pubkey_valid_base):
    """CHIPLET fused key 1 is programmed and unrevoked -> primary verifies and boots."""

    _CHIPLET_KEY = 1
