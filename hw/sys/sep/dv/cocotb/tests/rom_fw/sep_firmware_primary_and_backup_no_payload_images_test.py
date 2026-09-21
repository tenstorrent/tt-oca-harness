# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Both slots' payloads declare no images at all; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires
``0 < image_count <= 256`` and returns ``MANIFEST_ERR_TOC_COUNT`` (0x00030010)
otherwise. Both slots plant the ZERO half, so the primary is refused, the backup is
refused for the SAME reason, the retry loop is exhausted and the run ends terminal
on ``MANIFEST_ALL_FAILED``.

THE TWO CODES COINCIDE, AND THAT IS THE SCENARIO rather than a weakness to route
around. It does mean the error code alone cannot say which slot a rejection belongs
to, so ``sep_no_payload_images_base`` attributes them by COUNT and by BRACKET
instead: ``MANIFEST_ERR=`` must appear exactly twice in the run,
``MANIFEST_ERR=0x00030010`` exactly twice, the first occurrence between the primary
read and the backup read, and the second between the backup read and
``MANIFEST_ALL_FAILED``. Each is additionally required to sit after its own slot's
``CRYPTO_VALIDATE_OK``, so neither can be a refusal from somewhere upstream that
happens to carry the right code. This is also why
``sep_backup_payload_fail_base`` cannot grade this row: it explicitly REFUSES equal
primary and backup codes, and relaxing that would have weakened its existing
dependants.

THE REFERENCE DISTINGUISHES THE TWO BY SEVERITY; THIS DESIGN CANNOT. The reference
expects ``WARNING: INVALID_PAYLOAD_LENGTH`` for the primary and
``ERROR: INVALID_PAYLOAD_LENGTH`` for the backup -- one rule, two severities. This
ROM prints one ``MANIFEST_ERR=`` line per slot with no severity distinction
(``manifest_load.c``), so position and count carry what severity carried there. The
sequence asserted is the same sequence: recoverable slot failure, then terminal
failure.

SECURE BOOT STAYS ON. Under LC=PROD, ``secure_boot_enabled()`` enforces the chain
regardless of the manifest flag, and both slots therefore run a full crypto chain
whose four markers are required twice each, inside their own attempts. That is the
positive evidence placing each rejection downstream of a VERIFIED signature.
``SBOOT_OFF`` and ``CRYPTO_FAIL=`` are forbidden.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the four ``*_invalid_payload_image_count_test`` cells -- the planted value,
    0 against 257, with the device shown to have served eight ZERO bytes at BOTH
    slots' ``image_count``;
  * from the ENCRYPTED stimulus -- ``DECRYPT_START`` must never appear;
  * from the PRIMARY row -- the run is terminal rather than a recovered boot;
  * from the BACKUP row -- the primary carries the SAME defect, so
    ``MANIFEST_ERR=0x00030010`` appears twice and the version code 0x00030006 is
    forbidden outright.

Needs ``+sep_crypto_edn_force``: both slots run a full RSA-3072 modexp on OTBN.
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
