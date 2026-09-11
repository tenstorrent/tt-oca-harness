# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Manifest authenticates against CHIPLET fused key 1, unrevoked -> boots.

The positive member of the chiplet fused-key pair for key 1. Both manifest slots
select ``PUBK_SEL_FUSE_KEY_1`` and are re-signed with dev0, and
``CHIPLET_PUBK_HASH1`` holds SHA-256 of that modulus, so the primary verifies and
the ROM boots without ever reading the backup.

MATCHED PAIR. This testcase and ``sep_firmware_chiplet_pubkey_1_revoke_test`` build
their flash image from the SAME call, ``select_chiplet_fuse_key(buf, 1)``, so the two
run byte-identical images and differ ONLY in ``CHIPLET_PUBK_REVOKE`` bit 17. Fuse
bit clear boots from the primary; bit set refuses BOTH manifests with
``KEY_REVOKED idx=0x00000011`` and never reaches ``RSA_VERIFY_START``.

Everything else -- why the fused-key arm is distinct code, why the revoke bit is 17
and not the reference's 7, why ROM development key 0 is revoked here, why the
other chiplet digest fuse holds a decoy, and which architected status codes are
substituted -- is in the shared base
``rom_fw/sep_chiplet_pubkey_base.py``. Read it before changing anything here.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_chiplet_pubkey_base import sep_chiplet_pubkey_valid_base


@pyuvm.test()
class sep_firmware_chiplet_pubkey_1_test(sep_chiplet_pubkey_valid_base):
    """CHIPLET fused key 1 is programmed and unrevoked -> primary verifies and boots."""

    _CHIPLET_KEY = 1
