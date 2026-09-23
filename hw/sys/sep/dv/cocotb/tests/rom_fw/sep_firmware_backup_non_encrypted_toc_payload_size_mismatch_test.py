# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup's PLAINTEXT TOC disagrees with the manifest on payload length; the ROM halts.

The backup TOC ``payload_length`` is 0x2000 against 5936 plaintext bytes and is refused
with ``TOC_PLEN_MISMATCH=`` after its crypto chain passes; the primary fails as BAD_MAGIC.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_backup_toc_bound_fail_base import sep_backup_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_backup_non_encrypted_toc_payload_size_mismatch_test(
        sep_backup_toc_bound_fail_base):
    """Plaintext backup TOC claims 0x2000 against a 5936-byte payload -> halt."""

    bound_defect = tbd.PLEN
    encrypted = False
