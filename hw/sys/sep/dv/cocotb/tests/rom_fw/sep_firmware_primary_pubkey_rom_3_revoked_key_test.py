# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest selects REVOKED ROM key slot 3 -> the backup boots.

Member of the six-testcase primary-side revoke family. The stimulus, the per-slot
derivations and every revocation assertion live once in
``sep_pubkey_rom_revoked_primary_base``; this module chooses the slot and the
outcome shape. Its OTP image is the whole of the rest of the stimulus:
``sep_efuse_lc_prod_pubk_revoke3.toml`` is ``sep_efuse_lc_prod.toml`` plus exactly
``CHIPLET_PUBK_REVOKE`` bit 3.

The outcome is A Completed boot, NOT A Terminal failure. Only the PRIMARY selects slot
3; the backup keeps the shipped ROM slot 0 (``configs/secure_boot_test.yaml:112-114``),
which bit 3 does not revoke, so the ROM falls over and boots from it. Slot 0 is the
exception and is built on the terminal base instead; the shared base measures which of
the two applies from the image rather than trusting the slot number.

What this member pins. The primary slot is grafted from ``oca_rom_key3_boot.bin``,
so the manifest the ROM reads is one slot 3 genuinely authorizes: its modulus hashes
to the digest ``key_digests.c`` holds for slot 3, and its signature verifies under
that key. The fuse bit is the only thing standing between it and a boot, which is what
makes the verdict attributable by construction rather than by argument.

``PUBK_UNAUTHORIZED`` is therefore a load-bearing forbid: seeing it would mean the
graft did not land and the refusal was about the key rather than about revocation. The
ROM authorizes before it consults the revocation bitmap -- a passing boot logs
``PUBK_SEL``, ``PUBK_AUTHORIZED``, ``PUBK_REVOKE`` in that order -- so an unauthorized
slot never reaches the check under test. ``PUBK_SLOT_UNPROVISIONED`` is forbidden
alongside it to catch the digest table shrinking back under this member.

``RSA_EXEC`` must not appear before the backup read, and the total count is pinned to
1, so the ROM is shown to refuse the slot before spending a modexp on it.

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
class sep_firmware_primary_pubkey_rom_3_revoked_key_test(
    sep_primary_pubkey_rom_revoked_failover_base
):
    """Primary selects revoked ROM slot 3 -> rejected -> backup boots from slot 0."""

    _REVOKED_SLOT = 3
