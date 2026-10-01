# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Manifest authenticates against CHIPLET fused key 0, unrevoked -> boots.

The positive member of the chiplet fused-key pair for key 0. Both manifest slots
select ``PUBK_SEL_FUSE_KEY_0`` and are re-signed with dev0, and
``CHIPLET_PUBK_HASH0`` holds SHA-256 of that modulus, so the primary verifies and
the ROM boots without ever reading the backup.

Matched pair. This testcase and ``sep_firmware_chiplet_pubkey_0_revoke_test`` build
their flash image from the SAME call, ``select_chiplet_fuse_key(buf, 0)``, so the two
run byte-identical images and differ ONLY in ``CHIPLET_PUBK_REVOKE`` bit 16. Fuse bit
clear boots from the primary; bit set refuses BOTH manifests with the revocation error
code and never reaches ``RSA_EXEC``.

Read it before changing anything here.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_chiplet_pubkey_base import sep_chiplet_pubkey_valid_base


@pyuvm.test()
class sep_firmware_chiplet_pubkey_0_test(sep_chiplet_pubkey_valid_base):
    """CHIPLET fused key 0 is programmed and unrevoked -> primary verifies and boots."""

    _CHIPLET_KEY = 0
