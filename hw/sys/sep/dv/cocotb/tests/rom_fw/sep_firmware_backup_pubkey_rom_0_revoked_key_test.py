# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest selects REVOKED ROM key slot 0 -> terminal.

Member of the six-testcase revoke family. The scenario, the eFuse preconditions
and every assertion live once in ``sep_pubkey_rom_revoked_base``; this module
chooses the slot. Its OTP image is the whole of the rest of the stimulus:
``sep_efuse_lc_prod_pubk_revoke0.toml`` is ``sep_efuse_lc_prod.toml`` plus
exactly ``CHIPLET_PUBK_REVOKE`` bit 0.

WHAT THIS MEMBER PINS. Slot 0 is the slot the shipped image is already signed
against, so this member needs no graft at all: the backup manifest is the shipped
bytes, valid in every respect -- correct magic, correct TBS hash, a modulus that
matches the ROM's compiled-in slot 0 digest, and a signature that verifies. Every
other member reaches the same standing by grafting in the slot signed by the key it
names, so slot 0 is the one that gets there for free rather than the only one that
gets there. Revocation is the ONLY possible cause of the rejection, and ``RSA_EXEC``
/ ``RSA_VERIFY_OK`` are the load-bearing forbids -- a revocation check that did
nothing would let this image boot.

It is the matched partner of ``sep_firmware_backup_rom_key_valid_test``, which
applies the identical flash stimulus and clears the fuse instead: same bytes,
opposite verdict, one bit apart.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_pubkey_rom_revoked_base import sep_pubkey_rom_revoked_base


@pyuvm.test()
class sep_firmware_backup_pubkey_rom_0_revoked_key_test(sep_pubkey_rom_revoked_base):
    """Primary fails over -> backup selects revoked ROM slot 0 -> terminal."""

    _REVOKED_SLOT = 0
