# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest selects REVOKED ROM key slot 3 -> terminal.

Member of the six-testcase revoke family. The scenario, the eFuse preconditions
and every assertion live once in ``sep_pubkey_rom_revoked_base``; this module
chooses the slot. Its OTP image is the whole of the rest of the stimulus:
``sep_efuse_lc_prod_pubk_revoke3.toml`` is ``sep_efuse_lc_prod.toml`` plus
exactly ``CHIPLET_PUBK_REVOKE`` bit 3.

WHAT THIS MEMBER PINS. Slot 3 has no compiled-in digest (``key_digests.c``
populates slot 0 only), so without the revocation bit it would be refused as
``ROM_KEY_EMPTY`` -- the arm ``sep_firmware_backup_unpopulated_rom_key_slot_test``
covers. Here the fuse bit changes the verdict, because ``validate_signature``
consults the fuse bitmap (``manifest_crypto.c``) BEFORE the digest table.
``ROM_KEY_EMPTY`` is therefore the load-bearing forbid: seeing it
would mean revocation was evaluated late, or not at all, and a part could then be
persuaded to reason about a revoked key.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_pubkey_rom_revoked_base import sep_pubkey_rom_revoked_base


@pyuvm.test()
class sep_firmware_backup_pubkey_rom_3_revoked_key_test(sep_pubkey_rom_revoked_base):
    """Primary fails over -> backup selects revoked ROM slot 3 -> terminal."""

    _REVOKED_SLOT = 3
