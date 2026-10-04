# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary fails integrity, backup fails authentication; the ROM halts.

Corrupts the primary's ``manifest_hash`` and one backup signature bit. Needs
``+esrc_noise_force``: the backup drives an RSA-3072 modexp.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_SIG_FAILED,
    sep_backup_manifest_fail_base,
)

MANIFEST_ERR_HASH_MISMATCH = mm.boot_err("OCA_FAIL_MANIFEST_HASH")

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# ROM emission order in the backup when the modexp runs and the padded digest disagrees.
_BACKUP_ORDERED = (
    "OCA_BODY=",
    "MFST_VER=",
    "PUBK_SEL=",
    "PUBK_AUTHORIZED",
    "PUBK_REVOKE=",
    "FUSE_VER=",
    "RSA_EXEC",
    "RSA_CMP1",
    "RSA_CMP2",
    "RSA_PKCS1_FAIL",
)
# The primary's manifest hash is refused before key selection, so it prints none of these.
_PRIMARY_ABSENT = ("PUBK_SEL=", "PUBK_AUTHORIZED", "PUBK_REVOKE=", "RSA_EXEC", "MANIFEST_OK")
_ONCE_ONLY = ("PUBK_SEL=", "PUBK_AUTHORIZED", "RSA_EXEC")


@pyuvm.test()
class sep_mixed_failure_primary_backup_test(sep_backup_manifest_fail_base):
    """Primary manifest hash mismatch -> backup signature fails RSA -> terminal."""

    efuse_preload = _EFUSE_PRELOAD
    primary_expected_error = MANIFEST_ERR_HASH_MISMATCH
    expected_error = MANIFEST_ERR_SIG_FAILED
    backup_defect_marker = "RSA_PKCS1_FAIL"

    extra_forbidden = (
        "RSA_VERIFY_OK",
        "MANIFEST_OK",
        # OTBN faults also refuse the signature with the same code.
        "RSA_OTBN_INIT_FAIL",
        "RSA_OTBN_LOAD_FAIL",
        "RSA_EXEC_FAIL",
        "OTBN_TIMEOUT",
        # Key-selection refusals that precede the verifier.
        "PUBK_ALGO_UNSUPPORTED",
        "PUBK_ENCODING_UNSUPPORTED",
        "PUBK_FIELD_TOO_SMALL",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_SEL_EMPTY",
        "PUBK_SLOT_RESERVED",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_UNAUTHORIZED",
        "PUBK_HASH_TIMEOUT",
        # A SHA engine fault refuses the primary's hash with a different code.
        "SHA_START_REJECTED",
        "SHA_OP_REJECTED",
        "HMAC_ERR_CODE=",
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        before = mm.manifest_hash(buf, "primary")
        expected = mm.signed_region_hash(buf, "primary")
        assert before == expected, (
            f"primary manifest_hash is {before.hex()} but the signed-region hash is "
            f"{expected.hex()}; the shipped image is not the valid baseline this "
            f"stimulus mutates away from"
        )
        mm.corrupt_manifest_hash(buf, "primary")
        after = mm.manifest_hash(buf, "primary")
        assert after != expected, "manifest_hash corruption was a no-op"
        self._primary_served = after
        self.logger.info(
            "CHK-STIMULUS-HASH: primary manifest_hash %s -> %s while sha256(signed region) "
            "stays %s. The field sits outside the signed region, so the ROM recomputes the "
            "shipped digest and must refuse the slot with "
            "MANIFEST_ERR=0x%08x -- upstream of its own crypto chain",
            before.hex()[:16],
            after.hex()[:16],
            expected.hex()[:16],
            MANIFEST_ERR_HASH_MISMATCH,
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        base = mm.slot_base("backup")
        before = bytes(buf[base + mm.OFF_SIGNATURE :][:8])
        mm.flip_signature_byte(buf, "backup", byte_index=0, xor_mask=0x01)
        after = bytes(buf[base + mm.OFF_SIGNATURE :][:8])
        assert before != after, "signature flip was a no-op"
        self._backup_served = after
        mm.verify_layout(buf, "backup")
        assert mm.manifest_hash(buf, "backup") == mm.signed_region_hash(buf, "backup"), (
            "backup manifest_hash no longer matches the signed region after the "
            "signature flip; the signature is supposed to sit outside that region, so "
            "the layout this stimulus assumes is wrong"
        )
        self.logger.info(
            "CHK-STIMULUS-SIG: backup signature[0:8] %s -> %s (1 bit), signed region hash "
            "intact, so the slot passes integrity and must be refused by "
            "the RSA verifier with MANIFEST_ERR=0x%08x -- a DIFFERENT class from "
            "the primary's",
            before.hex(),
            after.hex(),
            MANIFEST_ERR_SIG_FAILED,
        )

    def check_efuse(self, image) -> None:
        # Rollback and revocation checks run before RSA and would refuse the backup first.
        fd.assert_clean_key_fuses(image)

    def check_defect_attribution(self, console, i_backup: int) -> None:
        super().check_defect_attribution(console, i_backup)

        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [
            mm.PRIMARY_MANIFEST_OFFSET,
            mm.BACKUP_MANIFEST_OFFSET,
        ], f"slot attempts read {[hex(a.src) for a in attempts]}. Console: {console}"
        primary, backup = attempts
        primary_err = f"MANIFEST_ERR=0x{MANIFEST_ERR_HASH_MISMATCH:08x}"
        oc.assert_attempt(
            primary,
            error=MANIFEST_ERR_HASH_MISMATCH,
            stage="manifest",
            ordered=("OCA_BODY=", "MFST_VER=", primary_err),
            absent=_PRIMARY_ABSENT,
        )
        backup_err = f"MANIFEST_ERR=0x{MANIFEST_ERR_SIG_FAILED:08x}"
        oc.assert_attempt(
            backup,
            error=MANIFEST_ERR_SIG_FAILED,
            stage="manifest",
            ordered=_BACKUP_ORDERED + (backup_err,),
            absent=("RSA_VERIFY_OK", "MANIFEST_OK"),
        )
        tail = [line for _, line in backup.markers][-2:]
        assert oc.count(tail[:1], self.backup_defect_marker) == 1, (
            f"{self.backup_defect_marker} is not the line before the backup's error "
            f"(attempt ends {tail}): a later check refused the slot"
        )
        for marker in _ONCE_ONLY:
            n = oc.count(console, marker)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the backup's): "
                f"the primary must be refused at its manifest hash, upstream of "
                f"the crypto chain. Console: {console}"
            )
        self.logger.info(
            "CHK-MIXED-CLASS PASS: primary@%d-%d refused 0x%08x (integrity) before key "
            "selection; backup@%d-%d refused 0x%08x (authentication) after %s",
            primary.first,
            primary.last,
            MANIFEST_ERR_HASH_MISMATCH,
            backup.first,
            backup.last,
            MANIFEST_ERR_SIG_FAILED,
            " -> ".join(_BACKUP_ORDERED),
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        # Stage progress reports INFO; a refusal that fails over reports WARN.
        entered = 0x0101_004C  # STATUS_ENCODE(INFO, SEP_MSG_CHECK_MANIFEST_HASH)
        rejected = 0x0801_0000 | mm.rom_status_for_result(MANIFEST_ERR_HASH_MISMATCH)
        assert rejected in status_seq, (
            f"cold_scratch[1] never held 0x{rejected:08x} "
            f"(SEP_MSG_INVALID_MANIFEST_HASH): the primary was not refused by the "
            f"manifest hash comparison. Observed {[hex(v) for v in status_seq]}"
        )

        fd.assert_served_field(
            self.logger,
            self._flash,
            "primary",
            mm.OFF_MANIFEST_HASH,
            self._primary_served,
            "primary manifest_hash",
        )
        fd.assert_served_field(
            self.logger,
            self._flash,
            "backup",
            mm.OFF_SIGNATURE,
            self._backup_served,
            "backup signature[0:8]",
        )

        assert entered in status_seq, (
            f"cold_scratch[1] never held 0x{entered:08x}: the ROM did not report "
            f"entering the manifest hash check, so the primary's rejection cannot be the "
            f"integrity verdict. Observed {[hex(v) for v in status_seq]}"
        )
        self.logger.info(
            "CHK-PRIMARY-STATUS: cold_scratch[1] held 0x%08x then 0x%08x -- the "
            "integrity check was entered and reported its own rejection on the "
            "architected channel",
            entered,
            rejected,
        )


oc.assert_known(
    sep_mixed_failure_primary_backup_test.extra_forbidden + _BACKUP_ORDERED + _PRIMARY_ABSENT,
    sep_mixed_failure_primary_backup_test.__name__,
)
