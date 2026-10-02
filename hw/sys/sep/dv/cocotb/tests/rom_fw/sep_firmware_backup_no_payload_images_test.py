# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The backup's payload declares no images at all; the ROM halts.

Primary: stale ``payload_hash``, ``OCA_FAIL_PAYLOAD_HASH``. Backup: ``image_count == 0``,
``OCA_FAIL_PAYLOAD_TOC``. Both refusals are silent, so the two codes tell the slots apart.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_no_payload_images_base as npi


@pyuvm.test()
class sep_firmware_backup_no_payload_images_test(npi.sep_no_payload_images_terminal_base):
    """Plaintext backup TOC image_count is 0 -> both slots refused -> halt."""

    primary_expected_error = npi.ERR_PAYLOAD_HASH
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"
    primary_absent = npi.PLAINTEXT_PAYLOAD_ABSENT
    primary_field = npi.ENTRY0_DIGEST_FIELD

    def corrupt_primary(self, buf: bytearray) -> None:
        self._primary_served = npi.plant_stale_payload_hash(self.logger, buf, "primary")
