# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary's ENCRYPTED TOC claims more payload than the manifest; the backup boots.

``validate_manifest_payload`` (``bootrom/prod/src/manifest_load.c``) cross-checks the
TOC's copy of the payload length against the manifest's before reading any entry,
echoes the offending value as ``TOC_PLEN_MISMATCH=`` and returns
``MANIFEST_ERR_BAD_LENGTH`` (0x00030004). For an ENCRYPTED payload the two are not
required to be equal -- the manifest counts ciphertext and the TOC counts plaintext,
so the manifest may legitimately run up to one AES block ahead -- but the TOC may
never claim MORE than was loaded. The primary's rejection returns into
``rom_manifest_boot``'s retry loop, so the required outcome is a completed boot from
the untouched backup.

THE PLANTED VALUE. ``primary.toc.payload_length = 0x2000``. The encrypted arm
requires the manifest's length to equal the TOC's rounded up to the next AES block,
which for this artefact's 5936 plaintext bytes is 5952. 8192 is neither, so the
agreement is violated.

A TOC DECLARING LESS THAN THE MANIFEST IS NOT COVERED. 0x2000 is above the
manifest's length; no row plants one below it. See
``sep_toc_bound_defect.BAD_TOC_PAYLOAD_LENGTH``.

THE PAYLOAD IS GENUINELY ENCRYPTED. This row loads ``encrypted_boot.bin``, whose
slots both carry ``encrypted_payload = 1``, and the base asserts that flag on the
loaded image. The recovering backup is encrypted too and decrypts in turn, which is
why this row requires the decryption markers twice rather than once.

WHY THIS ROW'S BAD_LENGTH IS THE TOC'S AND NOT THE MANIFEST'S.
``validate_manifest_header`` can return the same 0x00030004 from far upstream. Two
things rule that out: the base asserts the primary's ``manifest_length`` is still
``MANIFEST_SIZE`` before planting anything, and it requires the primary's
``RSA_VERIFY_START``, ``SIG_VALID``, ``DECRYPT_START`` and ``DECRYPT_OK`` to precede
the token -- an ordering only a slot that cleared the header check in full can
produce.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from the IMAGE-EXCEEDS-BOUND cell -- the token, ``TOC_PLEN_MISMATCH=`` against
    ``IMAGE_ORDER_BAD idx=0x00000000``, each forbidding the other, and the error
    code, 0x00030004 against 0x0003000f, with the sibling code forbidden too. The two
    stimuli are mutually unreachable: this arm sits ABOVE the per-image loop, so on
    this row the loop is never entered and no image bound can be evaluated;
  * from the NON-ENCRYPTED cell -- ``DECRYPT_START`` and ``DECRYPT_OK`` must each
    appear exactly TWICE, with the primary's pair inside its own attempt. The two
    compare against different lengths: the plaintext row against the manifest's
    own, this one against the PKCS#7-padded length derived from the TOC's;
  * from the BACKUP cell -- the rejection sits between the primary read and the
    backup read, the run ends in a completed boot, and the served bytes are required
    at the PRIMARY slot's address (0x002008, not 0x042008). That address is the only
    discriminator available on an encrypted row: the TOC's payload_length lives in
    AES block 0, and the two slots' payloads are byte-identical until block 8, so
    both slots serve IDENTICAL ciphertext for the same planted value.

Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps and two AES decryptions.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_primary_toc_bound_fail_base import sep_primary_toc_bound_fail_base


@pyuvm.test()
class sep_firmware_primary_encrypted_toc_payload_size_mismatch_test(
        sep_primary_toc_bound_fail_base):
    """Encrypted primary TOC claims 0x2000 against a 5952-byte payload -> backup boots."""

    bound_defect = tbd.PLEN
    encrypted = True
