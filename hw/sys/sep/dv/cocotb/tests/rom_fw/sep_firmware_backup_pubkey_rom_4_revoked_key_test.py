# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest selects REVOKED ROM key slot 4 -> terminal.

Member of the six-testcase revoke family. The scenario, the eFuse preconditions
and every assertion live once in ``sep_pubkey_rom_revoked_base``; this module
chooses the slot. Its OTP image is the whole of the rest of the stimulus:
``sep_efuse_lc_prod_pubk_revoke4.toml`` is ``sep_efuse_lc_prod.toml`` plus
exactly ``CHIPLET_PUBK_REVOKE`` bit 4.

WHAT THIS MEMBER PINS. The backup slot is grafted from
``oca_rom_key4_boot.bin``, so the manifest the ROM falls back to is one slot 4
genuinely authorizes: its modulus hashes to the digest ``key_digests.c`` holds for
slot 4, and its signature verifies under that key. The fuse bit is the only thing
refusing it, which is what makes the terminal verdict attributable by construction.

``PUBK_UNAUTHORIZED`` is therefore a load-bearing forbid: seeing it would mean the
graft did not land and the refusal was about the key rather than about revocation.
The ROM authorizes before it consults the revocation bitmap -- a passing boot logs
``PUBK_SEL``, ``PUBK_AUTHORIZED``, ``PUBK_REVOKE`` in that order -- so an
unauthorized slot never reaches the check under test. ``PUBK_SLOT_UNPROVISIONED``
is forbidden alongside it, and remains the arm
``sep_firmware_backup_unpopulated_rom_key_slot_test`` covers: that test selects
``KEY_SLOT_FIRST_ROM_RESERVED``, which is past the six slots the table holds.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_pubkey_rom_revoked_base import sep_pubkey_rom_revoked_base


@pyuvm.test()
class sep_firmware_backup_pubkey_rom_4_revoked_key_test(sep_pubkey_rom_revoked_base):
    """Primary fails over -> backup selects revoked ROM slot 4 -> terminal."""

    _REVOKED_SLOT = 4
