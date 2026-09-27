# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest names a reserved key slot; the backup boots.

The PRIMARY's ``public_key_select`` names slot 26. The format reserves
``[31:26]``, so the platform refuses it with ``PUBK_SLOT_RESERVED`` before looking
for an anchor, returning ``MANIFEST_ERR_KEY_UNAUTHORIZED`` -- the one code every
arm of ``plat_is_key_authorized()`` returns.

THE PRIMARY MUST NOT BE BROKEN ANY OTHER WAY. Only ``public_key_select`` is
written, and deliberately NOT the primary's ``manifest_identifier`` the way its
backup-side sibling does, because the primary has to REACH the check
under test. So there is no BAD_MAGIC failover trigger here.

The expected outcome is A Completed boot. Its backup-side sibling is the terminal one,
grading the same rejection ``ERROR:``.

WHY 26 AND NOT 31. Twenty-six is ``OCA_KEY_SLOT_MAX + 1`` exactly -- the
smallest slot the bound must refuse. A larger value would pass just as well
against a ROM that had written ``>=`` instead of ``>``, so only the boundary pins
the comparison. Slot 25 is a fuse-held chiplet key and would be accepted, which
is what makes this the boundary rather than merely a large number.

This is A DIFFERENT ARM FROM ``sep_firmware_primary_invalid_public_key_selection_test``.
That testcase names TWO slots and is refused for ambiguity, before any slot number is
resolved. This one names exactly one slot, which is resolved and echoed, and then
refused for being reserved. Both return ``MANIFEST_ERR_KEY_UNAUTHORIZED``, so
``PUBK_SEL_AMBIGUOUS`` is forbidden here and ``PUBK_SLOT_RESERVED`` required -- the
console token is the only discriminator.

**THE LOAD-BEARING CHECK IS THE ``PUBK_REVOKE=`` COUNT, AND IT CANNOT BE A PLAIN
FORBID.** The reserved-range check runs inside ``is_key_authorized``, which the
validator calls BEFORE the revocation check, and that ordering is a security
property rather than a detail: revocation indexes its bitmap by slot number, so a
reserved slot the bound let through would consult a bit belonging to no key. The
backup-side sibling can forbid the fuse echo outright because nothing in its run
reaches the revocation check; here the BACKUP boots and legitimately prints
``PUBK_REVOKE=0x00000000``. So the assertion is that the token occurs exactly ONCE
and only AFTER the backup read -- which says the same thing about the primary
without weakening into "the token may appear". ``PUBK_SLOT_UNPROVISIONED`` is
forbidden for the same reason one step later: a reserved slot must never reach
the anchor lookup.

Platform adaptation -- MARKER, AND THE GAP IS WIDER THAN THE ERROR TOKEN. So the
substitution is not confined to the rejection reason: the architected ring carries only
the generic terminal code plus ``MANIFEST_VALIDATED`` / ``COPY_AND_EXEC_IMAGE`` /
``EXEC_IMAGE``, and the debug console supplies everything else.

A Second narrowing, DISCLOSED. The mechanism is pinned rather than assumed --
``primary_expected_rsa_starts = 0`` requires the primary never to reach
``rsa_3072_verify`` -- but the narrowing is real and slot 0 of the revoke family is
where this group's strict form lives instead.

``public_key_sel`` is at manifest offset 166, inside the signed region, so the helper
re-hashes. No re-sign: the index is rejected before ``rsa_3072_verify``, so the now-stale signature is never examined, and the
base's ``primary_expected_rsa_starts = 0`` is what checks that rather than assuming
it.

Needs ``+esrc_noise_force``: the backup is valid, so the full RSA-3072 modexp
runs on OTBN, which parks in UrndRefresh until EDN grants entropy. The RSA
assertions are untouched, so ``RSA_VERIFY_OK`` still means the signature verified.
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
# (configs/secure_boot_test.yaml:112-114).
_BACKUP_SEL_ECHO = "PUBK_SEL=0x00000000"
_REVOKE_ECHO = "PUBK_REVOKE="


@pyuvm.test()
class sep_firmware_primary_rom_key_index_invalid_test(sep_primary_fail_backup_boot_base):
    """Primary names ROM key index 6 -> rejected at the bound -> backup boots."""

    primary_defect_marker = "PUBK_SLOT_RESERVED"
    primary_expected_error = MANIFEST_ERR_KEY_UNAUTHORIZED
    # The index bound precedes rsa_3072_verify, so the primary never drives it.
    primary_expected_rsa_starts = 0
    efuse_preload = _EFUSE_PRELOAD
    # Both selectors must be echoed: the primary's out-of-range one and the
    # backup's good one. Without the second, "the backup booted" is not tied to a
    # slot.
    extra_required = (_PRIMARY_SEL_ECHO, _BACKUP_SEL_ECHO)
    # PUBK_SEL_AMBIGUOUS is the discriminator against the unassigned-SOURCE arm, which
    # shares this error code. PUBK_SLOT_UNPROVISIONED must not appear at all: reaching the
    # digest table with index 6 would be a read past a six-entry array. The rest
    # are the later arms, none of which either slot may reach.
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
        # Exactly one bit, or this would be the PUBK_SEL_AMBIGUOUS testcase
        # wearing this one's name. get_public_key_sel raises on any other count,
        # so reaching here at all is the assertion.
        # The re-hash must have restored a valid signed region hash, or the primary is thrown
        # out in the manifest loop before key selection and this testcase would be
        # asserting on the wrong rejection.
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

        # CHK-BOUND-PREEMPTS-REVOKE: the ordering security property. The revocation
        # bitmap is consulted, four statements after the
        # bound, so the primary must NOT have reached it -- the single
        # occurrence in the run belongs to the booting backup and must follow the
        # backup read. An out-of-range index reaching `1u << index`
        # would consult a bit belonging to no ROM slot.
        n_revoke = sum(1 for line in console if _REVOKE_ECHO in line)
        assert n_revoke == 1, (
            f"{_REVOKE_ECHO} appeared {n_revoke} times, expected exactly 1 (the "
            f"backup's). More than one means the primary reached "
            f"the revocation check, so the index bound at "
            f":174-177 did not preempt it. Console: {console}"
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
