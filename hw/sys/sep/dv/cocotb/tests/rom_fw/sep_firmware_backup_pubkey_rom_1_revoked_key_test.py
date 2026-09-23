# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest selects REVOKED ROM key slot 1 -> terminal.

Fuse image ``sep_efuse_lc_prod_pubk_revoke1.toml`` sets ``CHIPLET_PUBK_REVOKE`` bit 1.
Slot 1's test digest is another key's, so ``PUBK_HASH_MISMATCH`` means revocation ran late.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_pubkey_rom_revoked_base import sep_pubkey_rom_revoked_base


@pyuvm.test()
class sep_firmware_backup_pubkey_rom_1_revoked_key_test(sep_pubkey_rom_revoked_base):
    """Primary fails over -> backup selects revoked ROM slot 1 -> terminal."""

    _REVOKED_SLOT = 1
