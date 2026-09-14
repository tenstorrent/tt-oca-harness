# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest names a ROM key index outside the table; the backup boots.

The PRIMARY's ``public_key_sel`` keeps ``selection = PUBK_SEL_ROM_KEY`` and sets
``index = 6``. ``validate_signature`` rejects ``index >= PUBK_SEL_NUM_ROM_KEYS``
(6, ``manifest.h``) with ``BAD_KEY_IDX`` at ``manifest_crypto.c``,
returning ``MANIFEST_ERR_SIG_FAILED``.

THE PRIMARY MUST NOT BE BROKEN ANY OTHER WAY. The reference modifies ONLY
``primary.manifest.public_key_sel.rom_key_index``
and does NOT corrupt the primary's ``manifest_identifier`` the way its
backup-side sibling does, because the primary has to REACH the check
under test. So there is no BAD_MAGIC failover trigger here.

THE EXPECTED OUTCOME IS A COMPLETED BOOT. The reference's ``expected_patterns``
(``sep_firmware_secure_boot_test.py``) grade the primary rejection
``WARNING: INVALID_KEY_INDEX`` and end in ``BACKUP_BL1_LOADED /
COPY_AND_EXEC_IMAGE / EXEC_IMAGE``. Its backup-side sibling is the terminal one,
grading the same rejection ``ERROR:``.

WHY 6 AND NOT 15. Six is ``PUBK_SEL_NUM_ROM_KEYS`` exactly -- the smallest index
the bound must refuse, and the boundary of the reference's own draw
``range(6, 16)`` (``sep_firmware_secure_boot_test.py``). A larger value would
pass just as well against a ROM that had written ``>`` instead of ``>=``, so only
the boundary pins the comparison. The field is four bits wide
(``{index:4, selection:3}``, ``manifest.h``), so 6 is representable and no
other field is disturbed.

THIS IS A DIFFERENT ARM FROM
``sep_firmware_primary_invalid_public_key_selection_test``. That testcase makes
``selection`` name no key SOURCE (3, 6 or 7) and lands in the ``default:`` arm
printing ``BAD_KEY_SEL`` (``manifest_crypto.c``). This one keeps a valid
source and makes the INDEX out of range. Both return ``MANIFEST_ERR_SIG_FAILED``,
so ``BAD_KEY_SEL`` is forbidden here and ``BAD_KEY_IDX`` required -- the console
token is the only discriminator.

**THE LOAD-BEARING CHECK IS THE ``PUBK_REVOKE=`` COUNT, AND IT CANNOT BE A PLAIN
FORBID.** The index bound runs BEFORE ``check_pubkey_revoked``
(``manifest_crypto.c``), and that ordering is a security
property rather than a detail: the ROM indexes the revocation bitmap with
``1u << index`` (``manifest_crypto.c``), so an index the bound let through
would shift by 6 or more and consult a bit belonging to no ROM slot. The
backup-side sibling can forbid the fuse echo outright because nothing in its run
reaches the revocation check; here the BACKUP boots and legitimately prints
``PUBK_REVOKE=0x00000000``. So the assertion is that the token occurs exactly ONCE
and only AFTER the backup read -- which says the same thing about the primary
without weakening into "the token may appear". ``ROM_KEY_EMPTY`` is forbidden for
the same reason one step later: an out-of-range index must never reach
``public_key_digests[index]``, which would read past the six-entry table.

PLATFORM ADAPTATION -- MARKER, AND THE GAP IS WIDER THAN THE ERROR TOKEN. The
reference's pattern list for this scenario has ELEVEN entries and SIX of the codes
they name have no ``report_status`` call anywhere under ``bootrom/prod/src``:
``WARNING: INVALID_KEY_INDEX`` (``status_values.h``), ``STATUS: USING_ROM_KEY``,
``STATUS: START_MANIFEST_VALIDATION`` (asserted twice),
``STATUS: START_PAYLOAD_VALIDATION``, ``STATUS: PAYLOAD_VALIDATED``
and ``STATUS: BACKUP_BL1_LOADED``. So the substitution is not
confined to the rejection reason: the architected ring carries only the generic
terminal code plus ``MANIFEST_VALIDATED`` / ``COPY_AND_EXEC_IMAGE`` / ``EXEC_IMAGE``,
and the debug console supplies everything else.

A SECOND NARROWING, DISCLOSED. The reference regenerates and RE-SIGNS its image
(``sep_firmware_secure_boot_test.py`` drives ``run_manifest_generator``
and ``build_firmware``), so its primary is legal in every respect except the
index. Here
the selector write re-hashes the TBS and leaves the dev0 signature stale, so this
testcase proves "the bound runs BEFORE the revocation check and before the
verifier", not the reference's stronger "the bound refuses an otherwise fully valid
manifest". The mechanism is pinned rather than assumed --
``primary_expected_rsa_starts = 0`` requires the primary never to reach
``rsa_3072_verify`` -- but the narrowing is real and slot 0 of the revoke family is
where this group's strict form lives instead.

``public_key_sel`` is at manifest offset 166, inside the TBS, so the helper
re-hashes. No re-sign: the index is rejected before ``rsa_3072_verify``
(``manifest_crypto.c``), so the now-stale signature is never examined, and the
base's ``primary_expected_rsa_starts = 0`` is what checks that rather than assuming
it.

Needs ``+sep_crypto_edn_force``: the backup is valid, so the full RSA-3072 modexp
runs on OTBN, which parks in UrndRefresh until EDN grants entropy. The RSA
assertions are untouched, so ``SIG_VALID`` still means the signature verified.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_fail_backup_boot_base import (
    MANIFEST_ERR_SIG_FAILED,
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# The boundary: the smallest index the ROM key table does not contain.
_BAD_INDEX = mm.PUBK_SEL_NUM_ROM_KEYS
# public_key_sel is {index:4, selection:3}; PUBK_SEL_ROM_KEY is 0 (manifest.h).
_BAD_PUBK_SEL_VALUE = _BAD_INDEX & 0xF
_PRIMARY_SEL_ECHO = f"PUBK_SEL=0x{_BAD_PUBK_SEL_VALUE:08x}"
# The backup keeps the shipped selector: ROM key slot 0
# (configs/secure_boot_test.yaml:112-114).
_BACKUP_SEL_ECHO = "PUBK_SEL=0x00000000"
_REVOKE_ECHO = "PUBK_REVOKE="


@pyuvm.test()
class sep_firmware_primary_rom_key_index_invalid_test(sep_primary_fail_backup_boot_base):
    """Primary names ROM key index 6 -> rejected at the bound -> backup boots."""

    primary_defect_marker = "BAD_KEY_IDX"
    primary_expected_error = MANIFEST_ERR_SIG_FAILED
    # The index bound precedes rsa_3072_verify, so the primary never drives it.
    primary_expected_rsa_starts = 0
    efuse_preload = _EFUSE_PRELOAD
    # Both selectors must be echoed: the primary's out-of-range one and the
    # backup's good one. Without the second, "the backup booted" is not tied to a
    # slot.
    extra_required = (_PRIMARY_SEL_ECHO, _BACKUP_SEL_ECHO)
    # BAD_KEY_SEL is the discriminator against the unassigned-SOURCE arm, which
    # shares this error code. ROM_KEY_EMPTY must not appear at all: reaching the
    # digest table with index 6 would be a read past a six-entry array. The rest
    # are the later arms, none of which either slot may reach.
    extra_forbidden = (
        "BAD_KEY_SEL",
        "ROM_KEY_EMPTY",
        "PUBK_HASH_MISMATCH",
        "KEY_REVOKED",
        "FUSE_KEY_EMPTY",
        "VERSION_ROLLBACK",
        "BAD_SIG_TYPE=",
        "RSA_VERIFY_FAIL",
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        # No manifest_identifier corruption: the primary must reach the bound.
        mm.set_public_key_sel(buf, "primary", selection=0, index=_BAD_INDEX)
        got = mm.get_public_key_sel(buf, "primary")
        assert got == _BAD_PUBK_SEL_VALUE, (
            f"primary public_key_sel encoded as 0x{got:04x}, expected "
            f"0x{_BAD_PUBK_SEL_VALUE:04x} (selection=PUBK_SEL_ROM_KEY, "
            f"index={_BAD_INDEX})"
        )
        # The selection half must still name the ROM-key source, or this would be
        # the BAD_KEY_SEL testcase wearing this one's name.
        selection = (got >> 4) & 0x7
        assert selection == 0, (
            f"public_key_sel.selection is {selection}, expected 0 "
            f"(PUBK_SEL_ROM_KEY): the index bound is only reached on the ROM-key "
            f"arm (manifest_crypto.c:170)"
        )
        # The re-hash must have restored a valid TBS hash, or the primary is thrown
        # out in the manifest loop before key selection and this testcase would be
        # asserting on the wrong rejection.
        mm.verify_layout(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-KEY-INDEX: primary public_key_sel=0x%04x (ROM key source, "
            "index %d == PUBK_SEL_NUM_ROM_KEYS, the smallest out-of-range value), "
            "TBS re-hashed, magic intact so the slot still reaches "
            "validate_signature",
            got,
            _BAD_INDEX,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364 then :369) and would "
            f"reject the primary for a different reason"
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
        i_bad = index_of("BAD_KEY_IDX")
        i_bsrc = index_of(f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}")
        i_bsel = index_of(_BACKUP_SEL_ECHO)
        i_revoke = index_of(_REVOKE_ECHO)

        # CHK-KEY-INDEX-ATTRIBUTION: the ROM read THIS testcase's index out of the
        # primary and complained about it immediately, before falling over. Without
        # the echo, BAD_KEY_IDX could belong to any out-of-range index, including
        # one this stimulus did not plant.
        assert 0 <= i_psel < i_bad < i_bsrc, (
            f"the BAD_KEY_IDX verdict is not attributable to the primary's planted "
            f"index: {_PRIMARY_SEL_ECHO}@{i_psel} -> BAD_KEY_IDX@{i_bad} -> "
            f"backup@{i_bsrc}. Console: {console}"
        )
        n_bad = sum(1 for line in console if "BAD_KEY_IDX" in line)
        assert n_bad == 1, (
            f"BAD_KEY_IDX appeared {n_bad} times, expected exactly 1 (the "
            f"primary's); the backup must not carry this defect. Console: {console}"
        )

        # CHK-BOUND-PREEMPTS-REVOKE: the ordering security property. The revocation
        # bitmap is consulted at manifest_crypto.c, four statements after the
        # bound, so the primary must NOT have reached it -- the single
        # occurrence in the run belongs to the booting backup and must follow the
        # backup read. An out-of-range index reaching `1u << index`
        # (manifest_crypto.c) would consult a bit belonging to no ROM slot.
        n_revoke = sum(1 for line in console if _REVOKE_ECHO in line)
        assert n_revoke == 1, (
            f"{_REVOKE_ECHO} appeared {n_revoke} times, expected exactly 1 (the "
            f"backup's). More than one means the primary reached "
            f"check_pubkey_revoked (manifest_crypto.c:181), so the index bound at "
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
            "CHK-BOUND-PREEMPTS-REVOKE: primary %s@%d -> BAD_KEY_IDX@%d with no "
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
