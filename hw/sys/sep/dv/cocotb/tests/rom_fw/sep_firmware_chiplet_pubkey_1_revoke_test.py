# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CHIPLET fused key 1 is REVOKED -> both manifests refused -> terminal.

Both slots are re-signed for fused key 1; ``CHIPLET_PUBK_REVOKE`` bit 17 alone refuses both.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_chiplet_pubkey_base import sep_chiplet_pubkey_revoked_base


@pyuvm.test()
class sep_firmware_chiplet_pubkey_1_revoke_test(sep_chiplet_pubkey_revoked_base):
    """CHIPLET fused key 1 revoked -> primary and backup both refused -> terminal."""

    _CHIPLET_KEY = 1
