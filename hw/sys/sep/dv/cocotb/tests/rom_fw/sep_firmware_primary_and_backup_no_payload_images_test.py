# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Both slots' payloads declare zero images; the ROM halts on ``MANIFEST_ALL_FAILED``.

Both slots return the same ``MANIFEST_ERR_TOC_COUNT``, so the base attributes each
refusal by count and position. Needs ``+sep_crypto_edn_force`` for both RSA runs.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_defect as td
from rom_fw import sep_no_payload_images_base as npi


@pyuvm.test()
class sep_firmware_primary_and_backup_no_payload_images_test(
        npi.sep_no_payload_images_terminal_base):
    """Both slots' TOC image_count is 0 -> both refused -> halt."""

    primary_expected_error = npi.ERR_TOC_COUNT
    primary_field = npi.IMAGE_COUNT_FIELD
    extra_forbidden = tuple(
        npi.forbidden_errors(npi.ERR_TOC_COUNT)
        + [td.DECRYPT_START]
        + list(td.OTHER_PAYLOAD_TOKENS)
        + list(td.DECRYPT_FAILURE_TOKENS)
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        self._primary_served = npi.plant_empty_image_list(
            self.logger, buf, "primary")
