# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest names a reserved key slot; the backup boots.

The primary's ``public_key_select`` names slot 26 (``OCA_KEY_SLOT_MAX + 1``), the smallest
reserved slot, so only this value tells a ``>`` bound from a ``>=`` one. The ROM refuses it
with ``PUBK_SLOT_RESERVED`` and ``MANIFEST_ERR_KEY_UNAUTHORIZED`` before the anchor lookup, the
revocation read and ``rsa_3072_verify``. Only the selector changes, and the re-hash keeps the
signed region hash valid, so the primary reaches key authorization; the stale signature is
never examined.

``sep_firmware_primary_invalid_public_key_selection_test`` gets the same code for two selected
slots, so ``PUBK_SLOT_RESERVED`` is required and ``PUBK_SEL_AMBIGUOUS`` is forbidden. The
backup boots and prints ``PUBK_REVOKE=``, so that token must occur once, after the backup read.

Needs ``+esrc_noise_force``: the backup runs a full RSA-3072 modexp.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_fail_backup_boot_base import (
    MANIFEST_ERR_KEY_UNAUTHORIZED,
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# The boundary: the smallest slot the format reserves. One less is a fuse-held
# chiplet key and one more is equally reserved, so only this value distinguishes
# a `>` bound from a `>=` one.
_BAD_INDEX = mm.KEY_SLOT_FIRST_RESERVED
_BAD_PUBK_SEL_VALUE = _BAD_INDEX
_PRIMARY_SEL_ECHO = f"PUBK_SEL=0x{_BAD_PUBK_SEL_VALUE:08x}"
# The backup keeps the shipped selector: ROM key slot 0
# (configs/oca_secure_boot_test.yaml, public_key_select_classic).
_BACKUP_SEL_ECHO = "PUBK_SEL=0x00000000"
_REVOKE_ECHO = "PUBK_REVOKE="


@pyuvm.test()
class sep_firmware_primary_rom_key_index_invalid_test(sep_primary_fail_backup_boot_base):
    """Primary names reserved slot 26 -> rejected at the bound -> backup boots."""

    primary_defect_marker = "PUBK_SLOT_RESERVED"
    primary_expected_error = MANIFEST_ERR_KEY_UNAUTHORIZED
    # The index bound precedes rsa_3072_verify, so the primary never drives it.
    primary_expected_rsa_starts = 0
    efuse_preload = _EFUSE_PRELOAD
    # Both selectors must be echoed: the primary's out-of-range one and the
    # backup's good one. Without the second, "the backup booted" is not tied to a
    # slot.
    extra_required = (_PRIMARY_SEL_ECHO, _BACKUP_SEL_ECHO)
    # PUBK_SEL_AMBIGUOUS is the discriminator against the unassigned-SOURCE arm,
    # which shares this error code. PUBK_SLOT_UNPROVISIONED must not appear:
    # slot 26 is rejected by the global reserved bound before any anchor lookup.
    # The rest are later arms, none of which either slot may reach.
    extra_forbidden = (
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_UNAUTHORIZED",
        "PUBK_OTP_EMPTY",
        "PUBK_ALGO_UNSUPPORTED",
        "RSA_PKCS1_FAIL",
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        # No manifest_identifier corruption: the primary must reach the bound.
        mm.set_public_key_sel(buf, "primary", selection=0, index=_BAD_INDEX)
        got = mm.get_public_key_sel(buf, "primary")
        assert got == _BAD_PUBK_SEL_VALUE, (
            f"primary public_key_sel names slot {got}, expected "
            f"{_BAD_PUBK_SEL_VALUE} (the first reserved slot)"
        )
        # get_public_key_sel raises unless exactly one bit is set. verify_layout confirms the
        # re-hash, so the primary reaches key selection instead of failing in the manifest loop.
        mm.verify_layout(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-KEY-INDEX: primary public_key_sel names slot %d "
            "(== OCA_KEY_SLOT_MAX + 1, the smallest reserved slot), re-hashed, "
            "magic intact so the slot still reaches key authorization",
            got,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: this testcase pins "
            f"the fuse echo to the BACKUP's single occurrence to prove the index "
            f"bound ran first, so the bitmap must be clear -- and the backup "
            f"selects ROM slot 0 and must be able to use it or nothing would boot"
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        i_psel = index_of(_PRIMARY_SEL_ECHO)
        i_bad = index_of("PUBK_SLOT_RESERVED")
        i_bsrc = index_of(f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}")
        i_bsel = index_of(_BACKUP_SEL_ECHO)
        i_revoke = index_of(_REVOKE_ECHO)

        # CHK-KEY-INDEX-ATTRIBUTION: the ROM read THIS testcase's index out of the
        # primary and complained about it immediately, before falling over. Without
        # the echo, PUBK_SLOT_RESERVED could belong to any out-of-range index, including
        # one this stimulus did not plant.
        assert 0 <= i_psel < i_bad < i_bsrc, (
            f"the PUBK_SLOT_RESERVED verdict is not attributable to the primary's planted "
            f"index: {_PRIMARY_SEL_ECHO}@{i_psel} -> PUBK_SLOT_RESERVED@{i_bad} -> "
            f"backup@{i_bsrc}. Console: {console}"
        )
        n_bad = sum(1 for line in console if "PUBK_SLOT_RESERVED" in line)
        assert n_bad == 1, (
            f"PUBK_SLOT_RESERVED appeared {n_bad} times, expected exactly 1 (the "
            f"primary's); the backup must not carry this defect. Console: {console}"
        )

        # CHK-BOUND-PREEMPTS-REVOKE: the revocation bitmap is consulted after the
        # bound. The primary must not reach it; the single occurrence belongs to
        # the booting backup and follows the backup read. An out-of-range index
        # reaching `1u << index` would consult a bit belonging to no ROM slot.
        n_revoke = sum(1 for line in console if _REVOKE_ECHO in line)
        assert n_revoke == 1, (
            f"{_REVOKE_ECHO} appeared {n_revoke} times, expected exactly 1 (the "
            f"backup's). More than one means the primary reached "
            f"the revocation check, so the key-slot bound in "
            f"plat_is_key_authorized() did not preempt it. Console: {console}"
        )
        assert i_bsrc < i_revoke, (
            f"{_REVOKE_ECHO}@{i_revoke} did not follow the backup read@{i_bsrc}: "
            f"the single fuse echo is the primary's, so the bound did not stop it. "
            f"Console: {console}"
        )
        # CHK-BACKUP-SELECTOR: the recovering slot used the valid ROM-key selector,
        # so the boot is attributable to slot 0 rather than to an unread selection.
        assert i_bsrc < i_bsel < i_revoke, (
            f"the booting slot's key selection is unattributed: backup@{i_bsrc} -> "
            f"{_BACKUP_SEL_ECHO}@{i_bsel} -> {_REVOKE_ECHO}@{i_revoke}. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-BOUND-PREEMPTS-REVOKE: primary %s@%d -> PUBK_SLOT_RESERVED@%d with no "
            "fuse echo, then backup@%d -> %s@%d -> %s@%d -> boot",
            _PRIMARY_SEL_ECHO,
            i_psel,
            i_bad,
            i_bsrc,
            _BACKUP_SEL_ECHO,
            i_bsel,
            _REVOKE_ECHO,
            i_revoke,
        )
