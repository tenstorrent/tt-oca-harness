# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED TOC payload_length disagrees with the manifest; the backup boots.

The decrypted TOC payload_length must sit within one AES block below the manifest's, so 0x2000
must be refused with ``OCA_FAIL_PAYLOAD_TOC``. The library does not compare the
decrypted length with the manifest value, so the slot is accepted; the mismatch
refusal is not implemented. Needs ``+esrc_noise_force``: two RSA-3072 modexps and
AES decryptions.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_toc_payload_size_mismatch_test(sep_primary_toc_fail_base):
    """Encrypted primary TOC payload_length is 0x2000 -> refused -> the backup boots."""

    toc_field = td.TOC_PLEN
    encrypted = True
