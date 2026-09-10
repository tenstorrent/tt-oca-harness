# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest selects REVOKED ROM key slot 5 -> the backup boots.

Member of the six-testcase primary-side revoke family. The stimulus, the per-slot
derivations and every revocation assertion live once in
``sep_pubkey_rom_revoked_primary_base``; this module chooses the slot and the
outcome shape. Its OTP image is the whole of the rest of the stimulus:
``sep_efuse_lc_prod_pubk_revoke5.toml`` is ``sep_efuse_lc_prod.toml`` plus exactly
``CHIPLET_PUBK_REVOKE`` bit 5.

The outcome is A Completed boot, NOT A Terminal failure. Only the PRIMARY selects slot
5; the backup keeps the shipped ROM slot 0 (``configs/secure_boot_test.yaml:112-114``),
which bit 5 does not revoke, so the ROM falls over and boots from it. Slot 0 is the
exception and is built on the terminal base instead; the shared base measures which of
the two applies from the image rather than trusting the slot number.

What this member pins. Slot 5 has no compiled-in digest (``key_digests.c`` populates
slot 0 only), so without the revocation bit it would be refused as
``PUBK_SLOT_UNPROVISIONED``. Here the fuse bit changes the verdict, because the
signature path consults the fuse bitmap BEFORE the digest table.
``PUBK_SLOT_UNPROVISIONED`` is therefore the load-bearing forbid: seeing it would mean
revocation was evaluated late, or not at all.

Only ``rsa_private_key.dev0.pem`` ships here, so the selector write leaves the dev0
signature stale and this member proves the weaker property that revocation PREEMPTS the
empty-digest arm. The stale signature is never examined -- ``RSA_EXEC`` must not appear
before the backup read and the total count is pinned to 1 -- so the verdict stays
attributable to revocation. Slot 0 carries the family's strict form.

Needs ``+esrc_noise_force``: the backup is valid, so the full RSA-3072 modexp
runs on OTBN, which parks in UrndRefresh until EDN grants entropy. It grants
OTBN's EDN handshakes only; the RSA assertions are untouched, so ``RSA_VERIFY_OK``
still means the signature really verified.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_pubkey_rom_revoked_primary_base import (
    sep_primary_pubkey_rom_revoked_failover_base,
)


@pyuvm.test()
class sep_firmware_primary_pubkey_rom_5_revoked_key_test(
    sep_primary_pubkey_rom_revoked_failover_base
):
    """Primary selects revoked ROM slot 5 -> rejected -> backup boots from slot 0."""

    _REVOKED_SLOT = 5
