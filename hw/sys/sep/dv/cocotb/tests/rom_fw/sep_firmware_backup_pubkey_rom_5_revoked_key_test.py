# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest selects a REVOKED ROM key slot (slot 5) -> terminal.

The primary is corrupted to force failover, then the backup's ``public_key_sel``
is pointed at ROM key slot 5 while ``CHIPLET_PUBK_REVOKE`` bit 5 is blown in the
OTP. Revocation must reject it.

WHY SLOT 5 IS THE INTERESTING ONE, AND WHY THE ORDER IS THE POINT. Slot 5 has no
compiled-in digest (``key_digests.c:23-30`` populates slot 0 only), so it is also
the slot ``sep_firmware_backup_unpopulated_rom_key_slot_test`` uses to prove the
empty-digest arm -- it expects ``ROM_KEY_EMPTY`` from slot 1, the first empty one.
Here the revocation bit changes the verdict, because ``validate_signature``
consults the fuse bitmap BEFORE it looks at the digest table
(``manifest_crypto.c:181`` then ``:190``). ``ROM_KEY_EMPTY`` is therefore
forbidden below: seeing it would mean revocation was evaluated late, or not at
all, and a part could then be persuaded to reason about a revoked key.

THE FUSE BIT IS THE SLOT NUMBER. ``CHIPLET_PUBK_REVOKE.select[7:0]`` is the
ROM-key bitmap (``sep_efuse_map.rdl:721-729``) and the ROM indexes it with the
manifest's key index directly (``manifest_crypto.c:180``). Only bit 5 is blown,
so slot 0 -- what the image is actually signed with -- stays usable, and the
rejection can only be attributed to the slot this manifest selected. Both halves
are echoed by the ROM (``PUBK_SEL=`` and ``PUBK_REVOKE=``) and both are required
below, so the verdict is tied to this stimulus rather than to the fuse image
generally.

No ``+sep_crypto_edn_force``: revocation precedes the signature step, so OTBN is
never driven. ``RSA_VERIFY_START`` is forbidden for the same reason -- a revoked
key must not reach the verifier at all.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_KEY_REVOKED,
    sep_backup_manifest_fail_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"
    / "sep_efuse_lc_prod_pubk_revoke5.toml"
)

# ROM key slot under test, and the CHIPLET_PUBK_REVOKE bit that revokes it.
_REVOKED_SLOT = 5
_REVOKE_BITMAP = 1 << _REVOKED_SLOT
# public_key_sel is {index:4, selection:3}; PUBK_SEL_ROM_KEY is 0.
_PUBK_SEL_VALUE = _REVOKED_SLOT & 0xF

# manifest_crypto.c:112 -- simputshex32("KEY_REVOKED idx=", index).
_REVOKED_MARKER = f"KEY_REVOKED idx=0x{_REVOKED_SLOT:08x}"
# manifest_crypto.c:109 / :167 -- the ROM echoing the fuse word and the selector.
_REVOKE_ECHO = f"PUBK_REVOKE=0x{_REVOKE_BITMAP:08x}"
_PUBK_SEL_ECHO = f"PUBK_SEL=0x{_PUBK_SEL_VALUE:08x}"


@pyuvm.test()
class sep_firmware_backup_pubkey_rom_5_revoked_key_test(sep_backup_manifest_fail_base):
    """Primary fails over -> backup selects revoked ROM slot 5 -> terminal."""

    backup_defect_marker = _REVOKED_MARKER
    expected_error = MANIFEST_ERR_KEY_REVOKED
    efuse_preload = _EFUSE_PRELOAD
    # ROM_KEY_EMPTY is the load-bearing one: slot 5 IS empty, so seeing it would
    # mean the digest table was consulted before the revocation bitmap. The rest
    # are the other arms that would make the verdict mean something else.
    extra_forbidden = ("ROM_KEY_EMPTY", "PUBK_HASH_MISMATCH", "RSA_VERIFY_START",
                       "SIG_VALID", "CRYPTO_VALIDATE_OK", "BAD_KEY_IDX",
                       "BAD_KEY_SEL", "FUSE_KEY_EMPTY", "VERSION_ROLLBACK")

    def corrupt_backup(self, buf: bytearray) -> None:
        mm.set_public_key_sel(buf, "backup", selection=0, index=_REVOKED_SLOT)
        got = mm.get_public_key_sel(buf, "backup")
        assert got == _PUBK_SEL_VALUE, (
            f"public_key_sel encoded as 0x{got:04x}, expected 0x{_PUBK_SEL_VALUE:04x} "
            f"(selection=ROM_KEY, index={_REVOKED_SLOT})"
        )
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-REVOKED-SLOT: backup public_key_sel=0x%04x "
            "(ROM key slot %d, revoked by CHIPLET_PUBK_REVOKE bit %d), TBS re-hashed",
            got, _REVOKED_SLOT, _REVOKED_SLOT,
        )

    def check_efuse(self, image) -> None:
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == _REVOKE_BITMAP, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0x{_REVOKE_BITMAP:x}: "
            f"exactly bit {_REVOKED_SLOT} must be blown -- a wider bitmap could "
            f"reject the manifest through a slot this test did not select"
        )
        # Slot 0 must stay usable: the image binds to it, and revoking it would
        # change what the primary/backup pair is even testing.
        assert not (revoke & 0x1), (
            f"CHIPLET_PUBK_REVOKE bit 0 is set (0x{revoke:x}); the signed image "
            f"binds to ROM slot 0 and this test must not revoke it"
        )
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364) and would terminate the "
            f"run before revocation is reached"
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        # The selector and the fuse word the ROM actually read. Without these the
        # KEY_REVOKED verdict could belong to some other slot or some other
        # bitmap, and the "slot 5, backup side" claim would be unsupported.
        for marker in (_PUBK_SEL_ECHO, _REVOKE_ECHO):
            assert any(marker in line for line in console), (
                f"ROM never printed {marker}: the revocation verdict cannot be "
                f"attributed to ROM slot {_REVOKED_SLOT} under a 0x{_REVOKE_BITMAP:x} "
                f"bitmap. Console: {console}"
            )
        self.logger.info(
            "CHK-REVOKE-ECHO: ROM read %s and %s", _PUBK_SEL_ECHO, _REVOKE_ECHO,
        )
