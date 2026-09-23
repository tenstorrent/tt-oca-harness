# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest selects REVOKED ROM key slot 0 -> terminal.

The backup is otherwise valid and signed for slot 0, so only fuse
``CHIPLET_PUBK_REVOKE`` bit 0 can refuse it, before RSA verification starts.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_pubkey_rom_revoked_base import sep_pubkey_rom_revoked_base


@pyuvm.test()
class sep_firmware_backup_pubkey_rom_0_revoked_key_test(sep_pubkey_rom_revoked_base):
    """Primary fails over -> backup selects revoked ROM slot 0 -> terminal."""

    _REVOKED_SLOT = 0
