# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest selects REVOKED ROM key slot 4 -> terminal.

Fuse image ``sep_efuse_lc_prod_pubk_revoke4.toml`` sets ``CHIPLET_PUBK_REVOKE`` bit 4.
Slot 4's test digest is another key's, so ``PUBK_HASH_MISMATCH`` means revocation ran late.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_pubkey_rom_revoked_base import sep_pubkey_rom_revoked_base


@pyuvm.test()
class sep_firmware_backup_pubkey_rom_4_revoked_key_test(sep_pubkey_rom_revoked_base):
    """Primary fails over -> backup selects revoked ROM slot 4 -> terminal."""

    _REVOKED_SLOT = 4
