# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CHIPLET fused key 1 is REVOKED -> both manifests refused -> terminal.

The revoking member of the chiplet fused-key pair for key 1.
``CHIPLET_PUBK_REVOKE`` bit 17 refuses ``CHIPLET_PUBK_HASH1``
( selects that index, tests it), and because BOTH
manifest slots select the same fused key the retry loop exhausts and the run ends in
``MANIFEST_ALL_FAILED``.

The strict form of the property. Both slots are re-signed with dev0 and re-checked with
``verify_sealed`` before the run, so each is a fully valid, provably bootable manifest
bound to fused key 1. One fuse bit refuses two good images, and revocation is the sole
possible cause -- ``PUBK_SLOT_UNPROVISIONED``, ``PUBK_OTP_EMPTY``,
``PUBK_UNAUTHORIZED``, ``RSA_EXEC`` and ``RSA_VERIFY_OK`` are all forbidden. The ROM-
slot revoke families of batches R1 and R2 could only reach this strict form at slot 0;
here both members reach it.

Matched pair with ``sep_firmware_chiplet_pubkey_1_test``: same image bytes, one fuse bit
apart.

Read it before changing anything here.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_chiplet_pubkey_base import sep_chiplet_pubkey_revoked_base


@pyuvm.test()
class sep_firmware_chiplet_pubkey_1_revoke_test(sep_chiplet_pubkey_revoked_base):
    """CHIPLET fused key 1 revoked -> primary and backup both refused -> terminal."""

    _CHIPLET_KEY = 1
