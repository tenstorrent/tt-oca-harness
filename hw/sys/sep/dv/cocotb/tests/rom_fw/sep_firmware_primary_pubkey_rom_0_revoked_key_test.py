# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest selects REVOKED ROM key slot 0 -> BOTH manifests refused.

The stimulus and assertions are in ``sep_pubkey_rom_revoked_primary_base``; this module picks
the slot and the outcome. ``sep_efuse_lc_prod_pubk_revoke0.toml`` is ``sep_efuse_lc_prod.toml``
plus only ``CHIPLET_PUBK_REVOKE`` bit 0. The shipped image selects ROM slot 0 in both slots
(``configs/oca_secure_boot_test.yaml``, ``public_key_select_classic``), so bit 0 refuses both
and the run ends in ``MANIFEST_ALL_FAILED``. This is the only terminal member.

Slot 0 is the slot the shipped image is signed against, so the selector write is a no-op and
both slots pass ``verify_sealed`` and ``verify_public_key`` before the run. One fuse bit
refuses two valid manifests. ``sep_firmware_primary_rom_key_valid_test`` applies the same
stimulus with the fuse clear and must boot. The per-slot ``MANIFEST_ERR=`` code
(``MANIFEST_ERR_KEY_REVOKED``) is the evidence. No ``+esrc_noise_force``: revocation precedes
the signature step, so ``RSA_EXEC`` is forbidden.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_pubkey_rom_revoked_primary_base import (
    sep_primary_pubkey_rom_revoked_terminal_base,
)


@pyuvm.test()
class sep_firmware_primary_pubkey_rom_0_revoked_key_test(
    sep_primary_pubkey_rom_revoked_terminal_base
):
    """Primary selects revoked ROM slot 0; the backup selects it too -> terminal."""

    _REVOKED_SLOT = 0
