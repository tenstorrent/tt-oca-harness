# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The backup's payload declares no images at all; the ROM halts.

The primary passes its crypto chain and is refused on TOC ``major_version``; the
backup is refused on ``image_count == 0`` with ``MANIFEST_ERR_TOC_COUNT``.
"""

from __future__ import annotations

import pyuvm

from env import sep_payload_mutate as pm
from rom_fw import sep_toc_defect as td
from rom_fw import sep_no_payload_images_base as npi


@pyuvm.test()
class sep_firmware_backup_no_payload_images_test(
        npi.sep_no_payload_images_terminal_base):
    """Plaintext backup TOC image_count is 0 -> both slots refused -> halt."""

    primary_expected_error = npi.ERR_BAD_TOC_VERSION
    primary_field = npi.TOC_VERSION_FIELD
    extra_forbidden = tuple(
        npi.forbidden_errors(npi.ERR_BAD_TOC_VERSION, npi.ERR_TOC_COUNT)
        + [td.DECRYPT_START]
        + list(td.OTHER_PAYLOAD_TOKENS)
        + list(td.DECRYPT_FAILURE_TOKENS)
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        off, size = npi.TOC_VERSION_FIELD
        was = pm.set_toc_version_major(buf, "primary", npi.TRIGGER_TOC_VERSION)
        p = pm.payload_base(buf, "primary")
        self._primary_served = bytes(buf[p + off:p + off + size])
        now = int.from_bytes(
            bytes(pm.toc_plaintext(buf, "primary")[off:off + size]), "little")
        assert now == npi.TRIGGER_TOC_VERSION, (
            f"primary TOC major_version reads {now} after the write, expected "
            f"{npi.TRIGGER_TOC_VERSION}; the failover trigger did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-FAILOVER-TRIGGER: primary TOC major_version %d -> %d, "
            "which validate_manifest_payload refuses with "
            "MANIFEST_ERR_BAD_TOC_VERSION -- a code distinct from the empty image "
            "list planted in the backup, reached through the primary's own verified "
            "crypto chain. The device must serve %s at flash 0x%06x",
            was, now, self._primary_served.hex(), p + off,
        )
