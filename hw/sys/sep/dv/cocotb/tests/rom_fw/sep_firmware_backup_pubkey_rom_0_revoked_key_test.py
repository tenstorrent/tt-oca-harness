# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest selects REVOKED ROM key slot 0 -> terminal.

Member of the six-testcase revoke family. The scenario, the eFuse preconditions
and every assertion live once in ``sep_pubkey_rom_revoked_base``; this module
chooses the slot. Its OTP image is the whole of the rest of the stimulus:
``sep_efuse_lc_prod_pubk_revoke0.toml`` is ``sep_efuse_lc_prod.toml`` plus
exactly ``CHIPLET_PUBK_REVOKE`` bit 0.

WHY SLOT 0 IS THE STRICTEST MEMBER. Slot 0 is the slot the shipped image is
signed against (``configs/secure_boot_test.yaml``), so it is the only member
whose selector already matches the modulus the manifest carries and the digest
``key_digests.c`` holds. The backup manifest here is therefore valid
in every respect -- correct magic, correct TBS hash, a modulus that matches the
ROM's compiled-in digest, and a dev0 signature that still verifies. The stimulus
does not corrupt it at all: it re-writes the selector to the value it already
holds, which the base class detects and turns into a ``verify_sealed()``
assertion. Revocation is therefore the ONLY possible cause of the rejection, and
``RSA_VERIFY_START`` / ``SIG_VALID`` are the load-bearing forbids -- a revocation
check that did nothing would let this image boot.

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
