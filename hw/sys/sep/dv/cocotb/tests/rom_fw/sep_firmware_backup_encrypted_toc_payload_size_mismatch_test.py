# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's ENCRYPTED TOC payload_length disagrees with the manifest; the ROM halts.

The decrypted TOC payload_length must sit within one AES block below the manifest's, so 0x2000
must be refused with ``OCA_FAIL_PAYLOAD_TOC``. Needs ``+esrc_noise_force``: an RSA-3072 modexp
and an AES decryption.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_toc_fail_base import sep_backup_toc_fail_base


@pyuvm.test()
class sep_firmware_backup_encrypted_toc_payload_size_mismatch_test(sep_backup_toc_fail_base):
    """Encrypted backup TOC payload_length is 0x2000 -> both slots refused -> halt."""

    toc_field = td.TOC_PLEN
    encrypted = True
