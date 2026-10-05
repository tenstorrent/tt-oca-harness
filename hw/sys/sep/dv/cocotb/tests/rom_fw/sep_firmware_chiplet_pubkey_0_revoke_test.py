# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CHIPLET fused key 0 is REVOKED -> both manifests refused -> terminal.

The revoking member of the chiplet fused-key pair for key 0. ``CHIPLET_PUBK_REVOKE`` bit 16
refuses ``CHIPLET_PUBK_HASH0``. Both manifest slots select the same fused key, so the retry loop
exhausts and the run ends in ``MANIFEST_ALL_FAILED``.

Both slots are re-signed with dev0 and pass ``verify_sealed`` before the run, so each is a valid
manifest bound to fused key 0. One fuse bit refuses two good images, and revocation is the only
possible cause: ``PUBK_SLOT_UNPROVISIONED``, ``PUBK_OTP_EMPTY``, ``PUBK_UNAUTHORIZED``,
``RSA_EXEC`` and ``RSA_VERIFY_OK`` are forbidden. The ROM-slot revoke tests reach this strict form
only at slot 0; here both members reach it.

Matched pair with ``sep_firmware_chiplet_pubkey_0_test``: same image bytes, one fuse bit apart.
The scenario and assertions are in ``sep_chiplet_pubkey_base``.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_chiplet_pubkey_base import sep_chiplet_pubkey_revoked_base


@pyuvm.test()
class sep_firmware_chiplet_pubkey_0_revoke_test(sep_chiplet_pubkey_revoked_base):
    """CHIPLET fused key 0 revoked -> primary and backup both refused -> terminal."""

    _CHIPLET_KEY = 0
