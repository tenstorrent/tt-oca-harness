# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario for the BL1-image-validity testcases (TP053-S, TP053-E).

Both testcases plant a defect in the SEP BL1 entry of the payload TOC -- one in
its size, one in its entry point -- in BOTH manifest slots, and require the ROM to
reject each slot before any BL1 copy or jump and then terminate. Only the
mutation and the console marker differ, so everything else lives here.

WHY BOTH SLOTS. The procedures say so: TP053-S step 1 plants the defect in the
primary and step 4 requires "backup also has invalid BL1 size -> terminal";
TP053-E is worded the same way. A defect in the primary alone would fail over to a
healthy backup and boot, which proves the failover works but says nothing about
the terminal outcome the procedure asks for.

WHY THIS SUBCLASSES ``sep_backup_manifest_fail_base`` BUT REPLACES ITS VERDICT.
The run machinery -- flash BFM, console capture, the PROD/secure-boot eFuse
assertions, the post-terminal quiescence window -- is exactly what is wanted and is
inherited unchanged. The CHECKS are not: that base is written for defects the
CRYPTO chain rejects, so it requires a ``MANIFEST_ERR=`` line and forbids
``MANIFEST_OK``. These defects are the opposite. They sit in the payload,
which ``try_manifest_slot`` validates AFTER the crypto chain has PASSED, so a correct run here must show
``MANIFEST_OK`` -- twice, once per slot -- and then fail. Overriding
:meth:`_check` rather than adding hooks to the shared base keeps six passing
testcases untouched.

THE CRYPTO CHAIN IS LEFT ON, AND THAT IS THE POINT. Because the payload is
mutated, ``payload_hash`` (inside the TBS) changes, so the slot must be re-hashed
and re-signed with the dev0 key -- see ``env/sep_payload_mutate.py``. The
alternative, running with secure boot disabled, would reach the same BL1 check
through a path production never takes. ``CHK-CRYPTO-RAN`` below is what turns
"the signature still verified" from an assumption into an observation.
"""

from __future__ import annotations

from pathlib import Path

from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import sep_backup_manifest_fail_base

_EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"
_EFUSE_LC_PROD = _EFUSE_DIR / "sep_efuse_lc_prod.toml"

#  -- the ROM labels the slot and then prints its offset.
_PRIMARY_SRC = "MANIFEST_SRC=0x00001000"
_BACKUP_SRC = "MANIFEST_SRC=0x00041000"

#  -- printed once per slot whose crypto chain passed.
# the ROM -- both slots were tried and both failed.
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_SBOOT_OFF = "SBOOT_OFF"

# rom_handoff.c -- anything from here on means BL1 was copied or entered. The
# procedures' "BL0 does NOT attempt to copy BL1 into IRAM" / "does NOT jump to the
# invalid entry address" is exactly the absence of these.
# "LOAD=" and "LEN=" are deliberately NOT used:  prints
# "PAYLOAD=", which contains "LOAD=" as a substring, so a marker check would
# false-positive on an ordinary payload report.
_BL1_PROGRESS = (
    "BL1_TYPE=",
    "COPY_SRC=",
    "COPY_DST=",
    "COPY_LEN=",
    "BL1_COPIED",
    "PRE_JUMP",
    "BL1_JUMP=",
)

# Every OTHER rejection the payload validator can emit. A negative test is only
# worth its verdict if the image failed for the reason it planted and for no
# other, and each of these would be a different reason -- most of them the
# signature that a re-seal went wrong (a stale image digest, a stale payload
# hash, a payload length left inconsistent with the TOC).
_OTHER_REJECTIONS = (
    "PLD_HASH_TIMEOUT",
    "RSA_PKCS1_FAIL",
    "RSA_PKCS1_FAIL",
    "RSA_VERIFY_OK_FAIL",
    "TOC_PLEN_MISMATCH",
    "TOC_REGION_OOB",
    "IMAGE_ORDER_BAD",
    "IMAGE_HASH_MISMATCH",
    "IMAGE_HASH_TIMEOUT",
    "NO_BL1_IMAGE",
    "FLASH_REINIT_FAIL",
)

# MANIFEST_OK, not PAYLOAD_OK: the claim is that the defect is caught downstream
# of the crypto chain, and one member's defect is caught BY the payload validator
# rather than after it, so PAYLOAD_OK does not appear for it at all.
_CRYPTO_OK = "MANIFEST_OK"


class sep_bl1_image_invalid_base(sep_backup_manifest_fail_base):
    """Same BL1 defect in both slots; reject before handoff, then terminate."""

    efuse_preload = _EFUSE_LC_PROD

    # --- subclass contract ---------------------------------------------------
    # ``backup_defect_marker`` is inherited: the console marker the BL1 placement check /
    # validate_manifest_payload must print. Here it applies to both slots, so
    # check_defect_attribution() below requires it twice rather than once.
    # Rejections this scenario's own defect must NOT produce, on top of the
    # shared list -- used to separate the two BL1 arms from one another.
    sibling_markers: tuple[str, ...] = ()

    def mutate_bl1(self, buf: bytearray, slot: str) -> None:
        raise NotImplementedError

    # --- stimulus ------------------------------------------------------------
    # Both slots carry the defect, so the base's default BAD_MAGIC primary
    # trigger is replaced and primary_expected_error follows expected_error.
    def corrupt_primary(self, buf: bytearray) -> None:
        self.mutate_bl1(buf, "primary")

    def corrupt_backup(self, buf: bytearray) -> None:
        self.mutate_bl1(buf, "backup")

    # --- checks --------------------------------------------------------------
    def check_defect_attribution(self, console, i_backup: int) -> None:
        """The marker must appear for BOTH slots, not once.

        The inherited default asserts the marker's FIRST occurrence follows the
        backup read, which is right when only the backup is defective. Here the
        primary carries the same defect, so the first occurrence is legitimately
        the primary's -- and accepting that alone would let a run in which the
        backup was never evaluated look identical to a correct one. Requiring one
        occurrence on each side of the backup read is what distinguishes them.
        """
        hits = [i for i, line in enumerate(console) if self.backup_defect_marker in line]
        assert len(hits) >= 2, (
            f"{self.backup_defect_marker} appeared {len(hits)} time(s) at {hits}; both "
            f"slots carry this defect, so it must be printed once for each. "
            f"Console: {console}"
        )
        assert hits[0] < i_backup, (
            f"first {self.backup_defect_marker} at line {hits[0]} did not precede the "
            f"backup read at line {i_backup}: the primary's own defect was not "
            f"reported, so the primary may have been rejected for another reason"
        )
        assert any(i > i_backup for i in hits), (
            f"{self.backup_defect_marker} never appeared after the backup read at line "
            f"{i_backup} (occurrences {hits}): the backup slot's BL1 entry was "
            f"never evaluated"
        )
        self.logger.info(
            "CHK-BL1-DEFECT: %s reported for both slots (lines %s, backup read at %d)",
            self.backup_defect_marker,
            hits,
            i_backup,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        log = self.logger
        status_hex = [hex(v) for v in status_seq]
        log.info("cold_scratch[1] sequence: %s", status_hex)
        log.info("ROM console: %s", console)

        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        def count_of(marker: str) -> int:
            return sum(1 for line in console if marker in line)

        # Guard the guards: with a dead core or a dark console every marker check
        # below is vacuously true.
        assert retired, "core retired no instructions; the ROM never ran"
        assert console, (
            "ROM console is empty, so no marker check below means anything (the "
            "virt console is DEBUG-build only -- check the ROM build)"
        )

        err_marker = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_primary = index_of(_PRIMARY_SRC)
        i_backup = index_of(_BACKUP_SRC)

        # CHK-FAILOVER: both slots were read, in order. Ordering is the substance
        # of the retry half of the procedure; two markers in any order would also
        # be satisfied by a ROM that read the backup first.
        assert i_primary >= 0, (
            f"ROM never read the primary slot ({_PRIMARY_SRC}). Console: {console}"
        )
        assert i_backup >= 0, (
            f"ROM never fell over to the backup slot ({_BACKUP_SRC}); the procedure "
            f"requires the backup to be attempted and to fail too. Console: {console}"
        )
        assert i_primary < i_backup, (
            f"backup slot was read at line {i_backup}, before the primary at line "
            f"{i_primary}: this is not a primary-then-backup retry"
        )
        log.info(
            "CHK-FAILOVER: primary at %s (line %d), then backup at %s (line %d)",
            _PRIMARY_SRC,
            i_primary,
            _BACKUP_SRC,
            i_backup,
        )

        # CHK-CRYPTO-RAN: secure boot was enforced and the signature verified, for
        # BOTH slots. This is what proves the defect is being caught by the payload
        # validator rather than by the crypto chain -- and it is the check that
        # would fail first if the re-seal in sep_payload_mutate were wrong, which
        # is precisely the failure mode that would otherwise masquerade as a
        # correct negative result.
        assert not any(_SBOOT_OFF in line for line in console), (
            f"ROM printed {_SBOOT_OFF}: secure boot was skipped, so this run "
            f"reached the BL1 check by a path production does not take. "
            f"Console: {console}"
        )
        n_crypto = count_of(_CRYPTO_OK)
        assert n_crypto >= 2, (
            f"{_CRYPTO_OK} appeared {n_crypto} time(s); both slots must clear the "
            f"manifest crypto chain (security version, root key, RSA signature) "
            f"before their payload is examined, so a count below two means a slot "
            f"was rejected earlier and the verdict below is not what stopped it. "
            f"Console: {console}"
        )
        log.info(
            "CHK-CRYPTO-RAN: %s seen %d times; the manifest chain cleared on both slots",
            _CRYPTO_OK,
            n_crypto,
        )

        # CHK-BL1-DEFECT: the planted defect was reported, for each slot.
        self.check_defect_attribution(console, i_backup)

        # CHK-REJECT-REASON: each slot was rejected with the error the defect
        # produces, and the run converged on it.
        n_err = count_of(err_marker)
        assert n_err >= 2, (
            f"{err_marker} appeared {n_err} time(s); each slot must be rejected "
            f"with the error this defect produces. Console: {console}"
        )
        assert any(_ALL_FAILED in line for line in console), (
            f"ROM never printed {_ALL_FAILED}; the retry loop did not exhaust both "
            f"slots. Console: {console}"
        )
        # The ring carries STATUS_ENCODE(type, SEP_MSG_*), which is a different
        # space from the console's OCA_BOOT_ERR_BASE | oca_result_t. Translated
        # through the ROM's own status_for_result() rather than by masking the
        # console code, whose low half is the result number and not a status.
        status_msg = mm.rom_status_for_result(self.expected_error)
        expected_status = 0x0F01_0000 | status_msg
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x} "
            f"(STATUS_ENCODE(ERROR, 0x{status_msg:04x})); observed {status_hex}"
        )
        log.info(
            "CHK-REJECT-REASON: %s on both slots, %s, cold_scratch[1]=0x%08x",
            err_marker,
            _ALL_FAILED,
            expected_status,
        )

        # CHK-ONLY-REASON: nothing else rejected the image. Without this, a
        # re-seal mistake that happened to also trip the planted marker would read
        # as a clean result.
        for marker in _OTHER_REJECTIONS + tuple(self.sibling_markers):
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}: the image is wrong in a way this testcase "
                f"did not plant, so the verdict cannot be attributed to the defect "
                f"under test. Console: {console}"
            )
        log.info("CHK-ONLY-REASON: no other rejection reason appeared")

        # CHK-TERMINAL: it stopped, and it stopped as a failure.
        assert fw_done, (
            f"ROM never signalled completion; a manifest that fails every slot must "
            f"converge on a mailbox FAIL. cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, "ROM signalled PASS: it booted an image it was supposed to reject"
        log.info("CHK-TERMINAL PASS: mailbox FAIL (fw_pass=0)")

        # CHK-NO-HANDOFF: the procedures' central claim -- BL0 rejected the image
        # BEFORE attempting to copy or enter BL1.
        for marker in _BL1_PROGRESS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which rom_handoff.c emits while loading or "
                f"entering BL1: the image was rejected too late, after BL0 had "
                f"already begun the handoff. Console: {console}"
            )
        log.info(
            "CHK-NO-HANDOFF: none of %s reached, so BL1 was never copied or entered",
            ", ".join(_BL1_PROGRESS),
        )
