# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The backup's payload declares no images at all; the ROM halts.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) requires
``0 < image_count <= 256`` and returns ``MANIFEST_ERR_TOC_COUNT`` (0x00030010)
otherwise. This row plants the ZERO half in the BACKUP. With the primary already
refused, the backup's rejection exhausts the retry loop and the run ends terminal
on ``MANIFEST_ALL_FAILED``.

THE FAILOVER TRIGGER IS THE REFERENCE'S OWN, not this repository's usual
``BAD_MAGIC``. The reference reaches its backup through a primary VERSION failure,
so the primary here declares TOC ``major_version = 99`` -- the reference's value --
and is refused with ``MANIFEST_ERR_BAD_TOC_VERSION`` (0x00030006). The trigger and
the arm under test are different rules with different codes, so the two rejections
stay individually countable, and both sit downstream of their own slot's crypto
chain, which the base asserts one slot at a time.

That choice costs one thing and buys another. ``sep_backup_payload_fail_base``
cannot grade it -- it requires each crypto marker exactly ONCE on the grounds that
its members' primaries die before the verifier, and here both slots reach it -- so
``sep_no_payload_images_base`` supplies a stricter replacement that pins each
marker to two occurrences, one inside each attempt. What it buys is that the run
reproduces the reference's stimulus ordering rather than substituting a
convenient trigger for it.

SECURE BOOT STAYS ON, AND THE REFERENCE'S ``secure_boot: 0`` IS NOT INERT -- it is
UNREACHABLE at the fuse image this family requires. The reference runs at TEST_DEV,
where its ``secure_boot_enabled()`` does consult the manifest flag, so its primary
genuinely skipped signature verification and its second ``primary.*`` key
(``encrypted_payload: 0``) exists only to keep that legal. This design's
``secure_boot_enabled()`` has the identical policy, but every member of this
failover family asserts LC=PROD, where the flag is never consulted; honouring
``secure_boot: 0`` would need a TEST_DEV/RMA fuse image or the ``SBOOT_DIS``
chicken bit, and this row uses neither. The consequence is that the primary here
runs a full RSA-3072 verification the reference's skipped -- MORE of the secure
path, not less -- and it is why the base grades both slots' crypto chains rather
than one. ``SBOOT_OFF`` and ``CRYPTO_FAIL=`` are both forbidden, so the row cannot
drift onto that arm. The encryption half of the pair IS reproduced: the loaded
image carries ``encrypted_payload = 0`` in both slots and the base asserts it.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the four ``*_invalid_payload_image_count_test`` cells -- the planted value,
    0 against 257, with the device shown to have served eight ZERO bytes at the
    BACKUP slot's ``image_count``;
  * from the ENCRYPTED stimulus -- ``DECRYPT_START`` must never appear;
  * from the PRIMARY row -- the run is terminal: ``MANIFEST_ALL_FAILED``, the
    ``STATUS_ENCODE(ERROR, 0x0010)`` word, no boot-progress marker, and a quiescent
    ROM afterwards;
  * from the PRIMARY_AND_BACKUP row -- the primary's code is the version one, so
    ``MANIFEST_ERR=0x00030010`` appears EXACTLY once and it is the backup's.

Needs ``+sep_crypto_edn_force``: both slots run a full RSA-3072 modexp on OTBN.
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
        """The reference's trigger: an invalid primary TOC major_version."""
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
