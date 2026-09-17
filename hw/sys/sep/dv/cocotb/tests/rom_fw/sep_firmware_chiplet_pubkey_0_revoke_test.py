# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CHIPLET fused key 0 is REVOKED -> both manifests refused -> terminal.

The revoking member of the chiplet fused-key pair for key 0.
``CHIPLET_PUBK_REVOKE`` bit 16 refuses ``CHIPLET_PUBK_HASH0``
(``manifest_crypto.c`` selects that index and tests it), and because BOTH
manifest slots select the same fused key the retry loop exhausts and the run ends in
``MANIFEST_ALL_FAILED``.

THE STRICT FORM OF THE PROPERTY. Both slots are re-signed with dev0 and re-checked
with ``verify_sealed`` before the run, so each is a fully valid, provably bootable
manifest bound to fused key 0. One fuse bit refuses two good images, and revocation
is the sole possible cause -- ``ROM_KEY_EMPTY``, ``FUSE_KEY_EMPTY``,
``PUBK_HASH_MISMATCH``, ``RSA_VERIFY_START`` and ``SIG_VALID`` are all forbidden.
The ROM-slot revoke families reach this strict form only at slot 0; here both
members reach it.

MATCHED PAIR with ``sep_firmware_chiplet_pubkey_0_test``: same image bytes, one fuse
bit apart.

Everything else -- why the fused-key arm is distinct code, why the revoke bit is 16
and not the reference's 6, why ROM development key 0 is revoked here too, and
which architected status codes are substituted -- is in the shared base
``rom_fw/sep_chiplet_pubkey_base.py``. Read it before changing anything here.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_chiplet_pubkey_base import sep_chiplet_pubkey_revoked_base


@pyuvm.test()
class sep_firmware_chiplet_pubkey_0_revoke_test(sep_chiplet_pubkey_revoked_base):
    """CHIPLET fused key 0 revoked -> primary and backup both refused -> terminal."""

    _CHIPLET_KEY = 0
