# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Both slots' payloads declare zero images; the ROM halts on ``MANIFEST_ALL_FAILED``.

Both slots return the same ``OCA_FAIL_PAYLOAD_TOC``, so each refusal is attributed by
its own attempt. Needs ``+esrc_noise_force`` for both RSA runs.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_no_payload_images_base as npi


@pyuvm.test()
class sep_firmware_primary_and_backup_no_payload_images_test(
    npi.sep_no_payload_images_terminal_base
):
    """Both slots' TOC image_count is 0 -> both refused -> halt."""

    primary_expected_error = npi.ERR_EMPTY_TOC
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"
    primary_absent = npi.PLAINTEXT_PAYLOAD_ABSENT
    primary_field = npi.IMAGE_COUNT_FIELD

    def corrupt_primary(self, buf: bytearray) -> None:
        self._primary_served = npi.plant_empty_image_list(self.logger, buf, "primary")
