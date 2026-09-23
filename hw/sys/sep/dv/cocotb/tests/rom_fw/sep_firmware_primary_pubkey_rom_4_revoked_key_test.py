# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest selects REVOKED ROM key slot 4 -> the backup boots.

The OTP preload is production fuses plus ``CHIPLET_PUBK_REVOKE`` bit 4. Revocation
must refuse the primary before the key-digest check, so no ``PUBK_HASH_MISMATCH``.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_pubkey_rom_revoked_primary_base import (
    sep_primary_pubkey_rom_revoked_failover_base,
)


@pyuvm.test()
class sep_firmware_primary_pubkey_rom_4_revoked_key_test(
        sep_primary_pubkey_rom_revoked_failover_base):
    """Primary selects revoked ROM slot 4 -> rejected -> backup boots from slot 0."""

    _REVOKED_SLOT = 4
