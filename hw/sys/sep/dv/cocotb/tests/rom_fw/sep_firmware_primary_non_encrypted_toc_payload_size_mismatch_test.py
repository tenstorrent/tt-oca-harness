# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's PLAINTEXT TOC disagrees with the manifest on payload length; the backup boots.

For a plaintext payload the TOC length must equal the manifest's. The ROM must refuse
0x2000 with ``TOC_PLEN_MISMATCH=`` and ``MANIFEST_ERR_BAD_LENGTH``, then fail over.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_primary_toc_bound_fail_base import sep_primary_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_primary_non_encrypted_toc_payload_size_mismatch_test(
    sep_primary_toc_bound_fail_base
):
    """Plaintext primary TOC claims 0x2000 against a 5936-byte payload -> backup boots."""

    bound_defect = tbd.PLEN
    encrypted = False
