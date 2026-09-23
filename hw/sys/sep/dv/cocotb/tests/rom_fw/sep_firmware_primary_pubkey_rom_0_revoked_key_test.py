# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest selects REVOKED ROM key slot 0 -> BOTH manifests refused.

The OTP preload is production fuses plus ``CHIPLET_PUBK_REVOKE`` bit 0. Both shipped
manifests select slot 0, so the boot must end in ``MANIFEST_ALL_FAILED``.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_pubkey_rom_revoked_primary_base import (
    sep_primary_pubkey_rom_revoked_terminal_base,
)


@pyuvm.test()
class sep_firmware_primary_pubkey_rom_0_revoked_key_test(
        sep_primary_pubkey_rom_revoked_terminal_base):
    """Primary selects revoked ROM slot 0; the backup selects it too -> terminal."""

    _REVOKED_SLOT = 0
