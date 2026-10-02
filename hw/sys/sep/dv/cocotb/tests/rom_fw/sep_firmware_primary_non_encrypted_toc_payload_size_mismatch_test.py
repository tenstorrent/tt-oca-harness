# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's PLAINTEXT TOC payload_length disagrees with the manifest; the backup boots.

A cleartext TOC payload_length must equal the manifest's, else ``OCA_FAIL_PAYLOAD_TOC``.
Needs ``+esrc_noise_force``: two RSA-3072 modexps.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_non_encrypted_toc_payload_size_mismatch_test(sep_primary_toc_fail_base):
    """Plaintext primary TOC payload_length is 0x2000 -> refused -> the backup boots."""

    toc_field = td.TOC_PLEN
    encrypted = False
