# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CHIPLET fused key 0 is REVOKED -> both manifests refused -> terminal.

Both slots are re-signed for fused key 0; ``CHIPLET_PUBK_REVOKE`` bit 16 alone refuses both.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_chiplet_pubkey_base import sep_chiplet_pubkey_revoked_base


@pyuvm.test()
class sep_firmware_chiplet_pubkey_0_revoke_test(sep_chiplet_pubkey_revoked_base):
    """CHIPLET fused key 0 revoked -> primary and backup both refused -> terminal."""

    _CHIPLET_KEY = 0
