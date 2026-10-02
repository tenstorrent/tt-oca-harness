# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest selects REVOKED ROM key slot 0 -> terminal.

The scenario and assertions are in ``sep_pubkey_rom_revoked_base``; this module picks the slot.
``sep_efuse_lc_prod_pubk_revoke0.toml`` is ``sep_efuse_lc_prod.toml`` plus only
``CHIPLET_PUBK_REVOKE`` bit 0. The shipped image is signed for slot 0, so the backup is valid in
every other respect and revocation is the only possible cause of the refusal; the run must not
reach ``RSA_EXEC`` or ``RSA_VERIFY_OK``. ``sep_firmware_backup_rom_key_valid_test`` uses the same
flash image with the fuse clear and must boot.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_pubkey_rom_revoked_base import sep_pubkey_rom_revoked_base


@pyuvm.test()
class sep_firmware_backup_pubkey_rom_0_revoked_key_test(sep_pubkey_rom_revoked_base):
    """Primary fails over -> backup selects revoked ROM slot 0 -> terminal."""

    _REVOKED_SLOT = 0
