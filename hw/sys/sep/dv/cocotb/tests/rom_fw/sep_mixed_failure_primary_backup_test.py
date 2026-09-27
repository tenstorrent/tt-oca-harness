# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary fails integrity, backup fails authentication; the ROM halts.

The primary's ``manifest_hash`` and one bit of the backup's signature are corrupted;
the ROM must refuse both with different codes. Needs ``+sep_crypto_edn_force``.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
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

_HASH_TOKEN = "MANIFEST_HASH_MISMATCH"
_HASH_OK = "MANIFEST_HASH_OK"
# ROM emission order when the modexp runs and the padded digest disagrees.
_RSA_CHAIN = (
    "RSA_VERIFY_START",
    "RSA_EXEC",
    "RSA_CMP1",
    "RSA_CMP2",
    "RSA_PKCS1_FAIL",
    "RSA_VERIFY_FAIL",
)
_ONCE_ONLY = ("RSA_VERIFY_START", "PUBK_SEL=", _HASH_OK)


@pyuvm.test()
class sep_mixed_failure_primary_backup_test(sep_backup_manifest_fail_base):
    """Primary manifest hash mismatch -> backup signature fails RSA -> terminal."""

    efuse_preload = _EFUSE_PRELOAD
    primary_expected_error = MANIFEST_ERR_HASH_MISMATCH
    expected_error = MANIFEST_ERR_SIG_FAILED
    backup_defect_marker = "RSA_VERIFY_FAIL"

    extra_forbidden = (
        "SIG_VALID",
        "CRYPTO_VALIDATE_OK",
        "RSA_VERIFY_OK",
        # OTBN faults also end in RSA_VERIFY_FAIL and would satisfy the defect marker.
        "RSA_OTBN_INIT_FAIL",
        "RSA_OTBN_LOAD_FAIL",
        "RSA_EXEC_FAIL",
        # Other signature-refusal arms and the two verdicts that preempt them.
        "BAD_SIG_TYPE=",
        "BAD_KEY_IDX",
        "BAD_KEY_SEL",
        "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY",
        "PUBK_HASH_MISMATCH",
        "PUBK_HASH_TIMEOUT",
        "KEY_REVOKED idx=",
        "VERSION_ROLLBACK",
        # A SHA engine timeout returns the primary's code without a hash mismatch.
        "MANIFEST_HASH_TIMEOUT",
        "SHA256_CHECKS_DISABLED",
        "STAGED_WIPE=",
        "FLASH_REINIT_FAIL=",
        fd.LC_MARKER,
        fd.CHIPLET_MARKER,
        fd.PACKAGE_MARKER,
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
            "shipped digest and must refuse the slot as %s with "
            "MANIFEST_ERR=0x%08x -- upstream of its own crypto chain",
            before.hex()[:16],
            after.hex()[:16],
            expected.hex()[:16],
            _HASH_TOKEN,
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
            "rsa_3072_verify with MANIFEST_ERR=0x%08x -- a DIFFERENT class from "
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

        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)

        fd.assert_slot_attributed(console, _HASH_TOKEN, after=i_psrc, before=i_backup)

        for marker in _ONCE_ONLY:
            n = fd.count(console, marker)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the backup's): "
                f"the primary must be refused at its manifest hash, upstream of "
                f"the crypto chain. Console: {console}"
            )
        i_hash_ok = fd.first_index(console, _HASH_OK)
        assert i_backup < i_hash_ok, (
            f"{_HASH_OK}@{i_hash_ok} precedes the backup read@{i_backup}, so it is "
            f"the primary's: the primary's hash did not fail. Console: {console}"
        )

        previous = i_hash_ok
        positions = []
        for marker in _RSA_CHAIN:
            i = fd.first_index(console, marker, after=previous)
            assert i > previous, (
                f"{marker} does not appear after the previous stage@{previous}: "
                f"the backup's RSA verification is out of order or absent. Chain "
                f"so far: {list(zip(_RSA_CHAIN, positions))}. Console: {console}"
            )
            positions.append(i)
            previous = i
        self.logger.info(
            "CHK-MIXED-CLASS: primary@%d -> %s (0x%08x, integrity) -> backup@%d -> "
            "%s@%d -> %s (0x%08x, authentication). Two different failure classes, "
            "one crypto chain, terminal on the backup's code",
            i_psrc,
            _HASH_TOKEN,
            MANIFEST_ERR_HASH_MISMATCH,
            i_backup,
            _HASH_OK,
            i_hash_ok,
            " -> ".join(f"{m}@{p}" for m, p in zip(_RSA_CHAIN, positions)),
            MANIFEST_ERR_SIG_FAILED,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        entered = 0x0101_004C  # STATUS_ENCODE(INFO,  SEP_MSG_CHECK_MANIFEST_HASH)
        rejected = 0x0F01_0013  # STATUS_ENCODE(ERROR, SEP_MSG_INVALID_MANIFEST_HASH)
        assert entered in status_seq, (
            f"cold_scratch[1] never held 0x{entered:08x}: the ROM did not enter "
            f"manifest_check_integrity, so the primary's rejection cannot be the "
            f"integrity verdict. Observed {[hex(v) for v in status_seq]}"
        )
        assert rejected in status_seq, (
            f"cold_scratch[1] never held 0x{rejected:08x} "
            f"(SEP_MSG_INVALID_MANIFEST_HASH): the primary was not refused by the "
            f"manifest hash comparison. Observed {[hex(v) for v in status_seq]}"
        )
        self.logger.info(
            "CHK-PRIMARY-STATUS: cold_scratch[1] held 0x%08x then 0x%08x -- the "
            "integrity check was entered and reported its own rejection on the "
            "architected channel",
            entered,
            rejected,
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
