# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's PLAINTEXT TOC entry 0 starts inside the TOC; the backup boots.

The payload format places every image after the TOC, so the slot must be refused with
``OCA_FAIL_PAYLOAD_TOC``. No check refuses a TOC entry whose image starts inside the TOC, so
the slot is accepted. Needs ``+esrc_noise_force``: two RSA-3072 modexps.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_toc_fail_base import sep_primary_toc_fail_base


@pyuvm.test()
class sep_firmware_primary_non_encrypted_payload_image_exceeds_bound_test(
    sep_primary_toc_fail_base
):
    """Plaintext primary TOC entry 0 starts at offset 240, inside the TOC -> backup boots."""

    toc_field = td.IMAGE_IN_TOC
    encrypted = False
