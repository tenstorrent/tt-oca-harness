# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest selects REVOKED ROM key slot 4 -> the backup boots.

Member of the six-testcase primary-side revoke family. The stimulus, the per-slot
derivations and every revocation assertion live once in
``sep_pubkey_rom_revoked_primary_base``; this module chooses the slot and the
outcome shape. Its OTP image is the whole of the rest of the stimulus:
``sep_efuse_lc_prod_pubk_revoke4.toml`` is ``sep_efuse_lc_prod.toml`` plus exactly
``CHIPLET_PUBK_REVOKE`` bit 4.

THE OUTCOME IS A COMPLETED BOOT, NOT A TERMINAL FAILURE. Only the PRIMARY selects
slot 4; the backup keeps the shipped ROM slot 0
(``configs/secure_boot_test.yaml``), which bit 4 does not revoke, so the
ROM falls over and boots from it. The run must
grade the primary rejection and end in
``COPY_AND_EXEC_IMAGE / EXEC_IMAGE``. Slot 0 is the exception and is built on the
terminal base instead; the shared base measures which of the two applies from the
image rather than trusting the slot number.

WHAT THIS MEMBER PINS. Slot 4's digest is another key's under ``TEST_BUILD``, not
the dev0 modulus this manifest carries, so without the revocation bit it
would be refused as ``PUBK_HASH_MISMATCH``. Here the fuse bit changes the verdict,
because ``validate_signature`` consults the fuse bitmap
(``manifest_crypto.c``) BEFORE the digest table.
``PUBK_HASH_MISMATCH`` is therefore the load-bearing forbid: seeing it would mean
revocation was evaluated late, or not at all.

A NARROWING. A stronger stimulus would re-sign the primary with slot 4's own
private key from ``bootrom/prod/tools/test_signing_keys/``, so that the primary
is a fully valid manifest bound to slot 4 and its test proves "revocation refuses
a provably good image". This member only writes the selector, which leaves
the dev0 signature stale, so it proves the weaker property that
revocation PREEMPTS the digest bind;
``sep_firmware_primary_rom_key_slot1_valid_test`` carries the re-signing the
stronger form needs. The stale signature is never examined --
``RSA_VERIFY_START`` must not appear before the backup read and the total count is
pinned to 1 -- so the verdict stays attributable to revocation. Slot 0 carries the
family's strict form.

Needs ``+sep_crypto_edn_force``: the backup is valid, so the full RSA-3072 modexp
runs on OTBN, which parks in UrndRefresh until EDN grants entropy. It grants
OTBN's EDN handshakes only; the RSA assertions are untouched, so ``SIG_VALID``
still means the signature really verified.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_pubkey_rom_revoked_primary_base import (
    sep_primary_pubkey_rom_revoked_failover_base,
)


@pyuvm.test()
class sep_firmware_primary_pubkey_rom_4_revoked_key_test(
        sep_primary_pubkey_rom_revoked_failover_base):
    """Primary selects revoked ROM slot 4 -> rejected -> backup boots from slot 0."""

    _REVOKED_SLOT = 4
