# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest selects REVOKED ROM key slot 0 -> BOTH manifests refused.

Member of the six-testcase primary-side revoke family. The stimulus, the per-slot
derivations and every revocation assertion live once in
``sep_pubkey_rom_revoked_primary_base``; this module chooses the slot and the
outcome shape. Its OTP image is the whole of the rest of the stimulus:
``sep_efuse_lc_prod_pubk_revoke0.toml`` is ``sep_efuse_lc_prod.toml`` plus exactly
``CHIPLET_PUBK_REVOKE`` bit 0.

THIS IS THE ONLY TERMINAL MEMBER OF THE FAMILY, and the reason is structural. The
shipped image gives BOTH slots ``rom_key_index: 0``
(``configs/secure_boot_test.yaml:43-45`` primary, backup), so bit 0
refuses the primary AND the backup, the retry loop exhausts, and the run ends in
``MANIFEST_ALL_FAILED`` (``manifest_load.c``). Slots 1-5 fail over and boot.
The reference expects exactly this split -- ``PRIMARY_PUBKEY_ROM_0_REVOKED_KEY``
ends at ``ERROR: REVOKED_KEY``
with no ``COPY_AND_EXEC_IMAGE``, while ``PRIMARY_PUBKEY_ROM_1_REVOKED_KEY`` ends in
``COPY_AND_EXEC_IMAGE / EXEC_IMAGE``.

IT IS ALSO THE STRICTEST MEMBER, not the awkward one. Slot 0 is the only populated
digest (``key_digests.c``) and the slot the image is signed against, so the
selector write is a NO-OP: the flash image this testcase runs is byte-identical to
the shipped ``bootrom/prod/build/secure_boot.bin``, and the base proves both slots
still pass ``verify_sealed`` and ``verify_public_key`` before the run starts. Two
provably valid, correctly signed, independently bootable manifests are refused by
ONE fuse bit, and revocation is the only possible cause.

MATCHED PAIR. ``sep_firmware_primary_rom_key_valid_test`` applies the IDENTICAL
stimulus -- ``select_primary_rom_slot(buf, 0)`` and nothing else -- and differs
only in leaving ``CHIPLET_PUBK_REVOKE`` clear. Same bytes, same signature, one fuse
bit, opposite verdicts.

PLATFORM ADAPTATION -- MARKER. The reference asserts the architected
``ERROR: REVOKED_KEY``. This ROM *defines* ``SEP_MSG_REVOKED_KEY``
(``bootrom/prod/include/status_values.h:13``) but never emits it -- there is no
``report_status`` call for it anywhere under ``bootrom/prod/src`` -- so the
architected ring carries only the generic terminal code. The dedicated error code
``MANIFEST_ERR_KEY_REVOKED`` (0x00030015, ``manifest.h``) is unshared, and the
console token ``KEY_REVOKED idx=0x00000000`` is the per-reason evidence; both are
required, once per slot for the token.

No ``+sep_crypto_edn_force``: revocation precedes the signature step, so OTBN is
never driven and ``RSA_VERIFY_START`` is forbidden.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_pubkey_rom_revoked_primary_base import (
    sep_primary_pubkey_rom_revoked_terminal_base,
)


@pyuvm.test()
class sep_firmware_primary_pubkey_rom_0_revoked_key_test(
    sep_primary_pubkey_rom_revoked_terminal_base
):
    """Primary selects revoked ROM slot 0; the backup selects it too -> terminal."""

    _REVOKED_SLOT = 0
