# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest's stored hash disagrees with its TBS; the backup boots.

``manifest_check_integrity`` recomputes SHA-256 over the TBS region -- offset 0 up
to the signature field -- and compares it against the ``manifest_hash`` field with
a constant-time comparison, printing ``MANIFEST_HASH_MISMATCH`` and returning
``MANIFEST_ERR_HASH_MISMATCH`` on disagreement
(``bootrom/prod/src/manifest_load.c``). It runs on every slot regardless of
secure-boot state. The expected outcome is that verdict on the primary and a
completed boot from the backup, including the payload validation and copy stages.

WHY THE STORED FIELD MOVES AND THE TBS DOES NOT. ``manifest_hash`` sits at offset
1128, OUTSIDE the TBS, so flipping a byte there changes only the stored copy: the
digest the ROM computes is still the shipped image's, and the mismatch is the
sole defect. Corrupting a TBS field instead would produce the same rejection for
a different reason -- the mutated field would also be the reason the digest
differs -- and the testcase could no longer say which of the two the ROM caught.
:func:`sep_manifest_mutate.corrupt_manifest_hash` therefore does NOT re-hash, and
that is the whole point of it.

WHAT THE ROM DOES AND DOES NOT REPORT. Unlike the other structural checks in this
group, this one has real architected evidence: ``SEP_MSG_CHECK_MANIFEST_HASH`` and
``SEP_MSG_INVALID_MANIFEST_HASH`` both have live ``report_status`` emitters
(``manifest_load.c``), so unlike the other structural checks these codes are
actually emitted rather than defined-but-never-emitted. Those go to the status ring; the console carries
the matching ``MANIFEST_HASH_MISMATCH`` / ``MANIFEST_HASH_OK`` pair, which is what
this testcase asserts because it is per-slot and ordered.

**HOW THIS IS TOLD APART FROM ``sep_firmware_primary_manifest_identifier_test``.**
Both plant a defect in the primary and both end in a backup boot, so the failover
alone would accept either run. The hash tokens separate them in both directions:
here ``MANIFEST_HASH_MISMATCH`` is required and pinned to the primary's attempt
while ``MANIFEST_HASH_OK`` is pinned to exactly one occurrence (the backup's);
there ``MANIFEST_HASH_MISMATCH`` is forbidden outright, because the identifier
check returns before the hash is ever computed. The error codes differ as well
(0x0003000b against 0x00030002).
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import (
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

# manifest.h
_MANIFEST_ERR_HASH_MISMATCH = 0x0003_000B

_HASH_MISMATCH = "MANIFEST_HASH_MISMATCH"
_HASH_OK = "MANIFEST_HASH_OK"


@pyuvm.test()
class sep_firmware_bad_manifest_hash_test(sep_primary_fail_backup_boot_base):
    """Primary's manifest_hash does not match its TBS -> the backup boots."""

    # The arm prints its own token but no CRYPTO_FAIL=, so the base's
    # crypto-shaped defect-marker path is not used.
    primary_defect_marker = ""
    primary_expected_error = _MANIFEST_ERR_HASH_MISMATCH
    primary_expected_rsa_starts = 0
    efuse_preload = _EFUSE_PRELOAD
    extra_required = (_HASH_MISMATCH, "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    # The primary is refused before the usage-constraint block and before the
    # crypto chain, and the backup is valid.
    extra_forbidden = ("MANIFEST_HASH_TIMEOUT", "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
                       "PLD_HASH_MISMATCH", fd.LC_MARKER, fd.CHIPLET_MARKER,
                       fd.PACKAGE_MARKER)

    def corrupt_primary(self, buf: bytearray) -> None:
        before = mm.manifest_hash(buf, "primary")
        computed = mm.tbs_hash(buf, mm.PRIMARY_MANIFEST_OFFSET)
        assert before == computed, (
            f"primary manifest_hash {before.hex()} already disagrees with "
            f"sha256(TBS) {computed.hex()}: the shipped image is not the valid "
            f"baseline this testcase mutates away from"
        )
        mm.corrupt_manifest_hash(buf, "primary")
        after = mm.manifest_hash(buf, "primary")
        assert after != before, "the manifest_hash write did not land"
        assert mm.tbs_hash(buf, mm.PRIMARY_MANIFEST_OFFSET) == computed, (
            "the TBS digest changed, so the mutation reached inside the signed "
            "region: the rejection would no longer be attributable to the stored "
            "hash alone"
        )
        self.logger.info(
            "CHK-STIMULUS-HASH: primary manifest_hash %s -> %s while sha256(TBS) "
            "stays %s, so the stored copy is the only defect",
            before.hex(), after.hex(), computed.hex(),
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-HASH-ATTRIBUTION: the mismatch and its error code both sit inside the
        # primary's attempt and each occurs once. A second mismatch would mean the
        # backup's hash was broken too, which is a terminal scenario rather than
        # this one.
        i_bad = fd.assert_slot_attributed(console, _HASH_MISMATCH, after=i_psrc,
                                          before=i_bsrc)
        fd.assert_slot_attributed(console, slot_err, after=i_bad - 1, before=i_bsrc)

        # CHK-HASH-RECOVERED: exactly one slot's hash verified, and it is the
        # backup's. Pinning the count is what stops a run where the primary also
        # verified -- i.e. where the mutation never landed -- from looking the same.
        n_ok = fd.count(console, _HASH_OK)
        assert n_ok == 1, (
            f"{_HASH_OK} appeared {n_ok} times, expected exactly 1 (the backup's). "
            f"Console: {console}"
        )
        i_ok = fd.first_index(console, _HASH_OK)
        assert i_bsrc < i_ok, (
            f"{_HASH_OK}@{i_ok} did not follow the backup read@{i_bsrc}: the one "
            f"hash that verified is not the backup's. Console: {console}"
        )
        self.logger.info(
            "CHK-MANIFEST-HASH: %s@%d and %s inside the primary attempt (read@%d, "
            "backup read@%d), and %s appears exactly once at %d -- the backup's",
            _HASH_MISMATCH, i_bad, slot_err, i_psrc, i_bsrc, _HASH_OK, i_ok,
        )
