# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED TOC claims more payload than the manifest; the backup boots.

Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps and two AES decryptions.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_primary_toc_bound_fail_base import sep_primary_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_toc_payload_size_mismatch_test(
    sep_primary_toc_bound_fail_base
):
    """Encrypted primary TOC claims 0x2000 against a 5952-byte payload -> backup boots."""

    bound_defect = tbd.PLEN
    encrypted = True
