# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED TOC claims more payload than the manifest; the ROM halts.

The backup TOC declares 0x2000 bytes against a manifest payload length of 5952.
Needs ``+sep_crypto_edn_force``: the backup runs an RSA-3072 modexp and an AES decryption.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_backup_toc_bound_fail_base import sep_backup_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_toc_payload_size_mismatch_test(
        sep_backup_toc_bound_fail_base):
    """Encrypted backup TOC claims 0x2000 against a 5952-byte payload -> halt."""

    bound_defect = tbd.PLEN
    encrypted = True
