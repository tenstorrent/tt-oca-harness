# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary fails integrity, backup fails authentication; the ROM halts.

The mixed-fault failover. The procedure corrupts the primary's manifest SHA-256
and the backup's RSA signature, and requires the ROM to reject both and
terminate. The point is not that two slots failed -- several rows already show
that -- but that the backup-retry path runs its FULL check sequence when the
primary's failure signature is a DIFFERENT CLASS from the backup's.

WHY THE TWO CLASSES CANNOT MASK EACH OTHER, which is what makes the row
gradeable. ``try_manifest_slot`` (``bootrom/prod/src/manifest_load.c``) checks
the manifest hash inside the slot attempt and enters the crypto chain only much
later, after the usage constraints, the extension load, the payload-source bounds
and the staging transfer. So:

  * the primary's only defect is ``manifest_hash``, which sits OUTSIDE the TBS.
    ``manifest_check_integrity`` recomputes SHA-256 over the untouched TBS, finds
    it disagrees with the stored copy, announces ``MANIFEST_HASH_MISMATCH`` and
    returns ``MANIFEST_ERR_HASH_MISMATCH`` (0x0003000B). That slot NEVER reaches
    ``validate_signature`` -- no ``PUBK_SEL=``, no ``RSA_VERIFY_START``, no
    staging -- so the signature check cannot be what refused it.
  * the backup's only defect is one bit of the signature, which also sits outside
    the TBS. Its manifest hash therefore still verifies (``MANIFEST_HASH_OK``),
    the whole structural half passes, the payload stages, and the slot is refused
    by ``rsa_3072_verify`` with ``RSA_VERIFY_FAIL`` and
    ``MANIFEST_ERR_SIG_FAILED`` (0x0003000C). The hash check cannot be what
    refused it.

The two codes differ, so ``last_err`` converging on the BACKUP's is a real
observation rather than an assumption, and ``rom_err_fail`` encodes it as
``STATUS_ENCODE(ERROR, 0x000C)`` in cold_scratch[1]. ``sep_backup_manifest_fail_base``
asserts that word independently of the console.

WHAT THIS ROW ADDS OVER ITS TWO NEIGHBOURS. Each of them covers one half and
neither can cover the cross:

  * ``sep_firmware_bad_manifest_hash_test`` plants the same primary defect but
    derives from the failover-and-boot base, which forbids
    ``MANIFEST_ALL_FAILED``. It cannot be terminal.
  * ``sep_firmware_backup_invalid_signature_test`` plants the same backup defect
    but leaves the primary on the family's default ``BAD_MAGIC`` trigger -- a
    STRUCTURAL rejection, refused before the hash is even computed.

So no existing run has a primary that got as far as its own integrity check and
failed there, followed by a backup that got all the way to the verifier and
failed there. That ordering is the coverage, and the counts below are what prove
it happened rather than something that merely ends the same way.

EXACTLY ONE CRYPTO CHAIN, AND IT IS THE BACKUP'S. ``RSA_VERIFY_START`` and
``PUBK_SEL=`` must each appear ONCE. A second occurrence would mean the primary
also reached the verifier, which would mean the hash mutation did not land -- and
the run would still terminate on 0x0003000C and still look green. Presence alone
cannot catch that; the count can. ``MANIFEST_HASH_OK`` must likewise appear once,
the backup's, and after the backup read.

``RSA_PKCS1_FAIL`` IS REQUIRED, not just ``RSA_VERIFY_FAIL``. ``rsa_verify.c``
emits the engine faults -- ``RSA_OTBN_INIT_FAIL``, ``RSA_OTBN_LOAD_FAIL``,
``RSA_EXEC_FAIL`` -- on the same return path as the PKCS#1 comparison failure, so
``RSA_VERIFY_FAIL`` on its own does not say the modexp ran. Requiring the
``RSA_EXEC`` -> ``RSA_CMP1`` -> ``RSA_CMP2`` -> ``RSA_PKCS1_FAIL`` sequence, and
forbidding the three engine faults, is what says OTBN executed the verification
and the padded digest genuinely disagreed.

The primary stages nothing, so ``STAGED_WIPE=`` must not appear: that marker is
emitted in the retry cleanup only when a staged payload landed outside SEP SRAM,
and the primary is refused long before any payload is fetched.

NAMING. The procedure writes the two verdicts as ``WARNING: BAD_MANIFEST_HASH``
and ``WARNING: INVALID_SIGNATURE``. This ROM's own vocabulary for them is the
console token ``MANIFEST_HASH_MISMATCH`` with architected status
``SEP_MSG_INVALID_MANIFEST_HASH``, and the console token ``RSA_VERIFY_FAIL`` --
``SEP_MSG_INVALID_SIGNATURE`` is defined in ``status_values.h`` and emitted by
nothing, so the signature half has no architected status to assert and the token
carries it. Both are slot errors that permit the retry the procedure requires, so
the mapping is vocabulary, not behaviour.

PROD lifecycle with ``SBOOT_DIS`` clear, enforced by the base: with secure boot
off the backup's signature would never be examined and the run would become a
failover-and-boot. Needs ``+sep_crypto_edn_force`` for the one OTBN modexp the
backup runs.
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

# manifest.h
MANIFEST_ERR_HASH_MISMATCH = 0x0003_000B

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_HASH_TOKEN = "MANIFEST_HASH_MISMATCH"
_HASH_OK = "MANIFEST_HASH_OK"
# rsa_verify.c, in emission order on a padded-digest disagreement. The modexp ran
# and the comparison is what refused the slot.
_RSA_CHAIN = ("RSA_VERIFY_START", "RSA_EXEC", "RSA_CMP1", "RSA_CMP2",
              "RSA_PKCS1_FAIL", "RSA_VERIFY_FAIL")
# Markers that must appear exactly once, because a second one would mean the
# PRIMARY also reached the verifier and the primary's defect did not land.
_ONCE_ONLY = ("RSA_VERIFY_START", "PUBK_SEL=", _HASH_OK)


@pyuvm.test()
class sep_mixed_failure_primary_backup_test(sep_backup_manifest_fail_base):
    """Primary manifest hash mismatch -> backup signature fails RSA -> terminal."""

    efuse_preload = _EFUSE_PRELOAD
    primary_expected_error = MANIFEST_ERR_HASH_MISMATCH
    expected_error = MANIFEST_ERR_SIG_FAILED
    backup_defect_marker = "RSA_VERIFY_FAIL"

    extra_forbidden = (
        # The signature was checked and REJECTED; neither slot may have passed it.
        "SIG_VALID", "CRYPTO_VALIDATE_OK", "RSA_VERIFY_OK",
        # OTBN faults reach RSA_VERIFY_FAIL by the same return path, so a run that
        # died in the engine would otherwise satisfy this row's defect marker.
        "RSA_OTBN_INIT_FAIL", "RSA_OTBN_LOAD_FAIL", "RSA_EXEC_FAIL",
        # The five other arms of validate_signature that return 0x0003000C, plus
        # the two codes that preempt it. Any of them would converge the boot on a
        # verdict this row's name does not describe.
        "BAD_SIG_TYPE=", "BAD_KEY_IDX", "BAD_KEY_SEL", "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH", "PUBK_HASH_TIMEOUT",
        "KEY_REVOKED idx=", "VERSION_ROLLBACK",
        # A SHA engine timeout returns the primary's code without the mismatch
        # being what produced it.
        "MANIFEST_HASH_TIMEOUT",
        # The hash gate must not have been skipped, and the crypto chain must not
        # have been bypassed.
        "SHA256_CHECKS_DISABLED",
        # The primary is refused upstream of any payload fetch, so the retry
        # cleanup has nothing staged to wipe, and the reinit must have succeeded.
        "STAGED_WIPE=", "FLASH_REINIT_FAIL=",
        # No usage-constraint arm may claim either slot.
        fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER,
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        base = mm.slot_base("primary")
        before = mm.manifest_hash(buf, "primary")
        expected = mm.tbs_hash(buf, base)
        assert before == expected, (
            f"primary manifest_hash is {before.hex()} but sha256(TBS) is "
            f"{expected.hex()}; the shipped image is not the valid baseline this "
            f"stimulus mutates away from"
        )
        mm.corrupt_manifest_hash(buf, "primary")
        after = mm.manifest_hash(buf, "primary")
        assert after != expected, "manifest_hash corruption was a no-op"
        self._primary_served = after
        self.logger.info(
            "CHK-STIMULUS-HASH: primary manifest_hash %s -> %s while sha256(TBS) "
            "stays %s. The field sits outside the TBS, so the ROM recomputes the "
            "shipped digest and must refuse the slot as %s with "
            "MANIFEST_ERR=0x%08x -- upstream of its own crypto chain",
            before.hex()[:16], after.hex()[:16], expected.hex()[:16],
            _HASH_TOKEN, MANIFEST_ERR_HASH_MISMATCH,
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        base = mm.slot_base("backup")
        before = bytes(buf[base + mm.OFF_SIGNATURE:][:8])
        mm.flip_signature_byte(buf, "backup", byte_index=0, xor_mask=0x01)
        after = bytes(buf[base + mm.OFF_SIGNATURE:][:8])
        assert before != after, "signature flip was a no-op"
        self._backup_served = after
        # The backup's manifest hash must STILL verify. If the flip had disturbed
        # the TBS the backup would be refused as HASH_MISMATCH in the manifest
        # loop, both slots would carry one code, and nothing would attribute the
        # terminal verdict -- the base refuses to run in that state.
        mm.verify_layout(buf, "backup")
        assert mm.manifest_hash(buf, "backup") == mm.tbs_hash(buf, base), (
            "backup manifest_hash no longer matches sha256(TBS) after the "
            "signature flip; the signature is supposed to sit outside the TBS, so "
            "the layout this stimulus assumes is wrong"
        )
        self.logger.info(
            "CHK-STIMULUS-SIG: backup signature[0:8] %s -> %s (1 bit), TBS hash "
            "intact, so the slot passes integrity and must be refused by "
            "rsa_3072_verify with MANIFEST_ERR=0x%08x -- a DIFFERENT class from "
            "the primary's", before.hex(), after.hex(), MANIFEST_ERR_SIG_FAILED,
        )

    def check_efuse(self, image) -> None:
        # check_security_version and check_pubkey_revoked both run BEFORE
        # rsa_3072_verify, so either fuse being non-zero would refuse the backup
        # earlier with a different code and the signature would never be reached.
        fd.assert_clean_key_fuses(image)

    def check_defect_attribution(self, console, i_backup: int) -> None:
        super().check_defect_attribution(console, i_backup)

        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)

        # CHK-PRIMARY-INTEGRITY: the primary failed at its OWN integrity check --
        # the token inside the primary's window, exactly once. This is the half
        # that separates this row from the sibling whose primary fails
        # structurally, before a hash is ever computed.
        fd.assert_slot_attributed(console, _HASH_TOKEN, after=i_psrc,
                                  before=i_backup)

        # CHK-ONE-CRYPTO-CHAIN: only one slot reached the verifier. A second
        # occurrence of any of these would mean the primary got past its integrity
        # check, so the mixed-class ordering this row is named for did not happen
        # -- and the run would still terminate on the same code.
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

        # CHK-RSA-RAN: the backup's verifier really executed and the padded digest
        # really disagreed, in the order rsa_verify.c emits the stages and inside
        # the backup's own attempt. Without the ordering an engine fault or a
        # stray marker would satisfy the defect marker alone.
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
            i_psrc, _HASH_TOKEN, MANIFEST_ERR_HASH_MISMATCH, i_backup,
            _HASH_OK, i_hash_ok,
            " -> ".join(f"{m}@{p}" for m, p in zip(_RSA_CHAIN, positions)),
            MANIFEST_ERR_SIG_FAILED,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        # CHK-PRIMARY-STATUS: the primary's rejection is also on the architected
        # channel, independently of the console. manifest_check_integrity reports
        # SEP_MSG_INVALID_MANIFEST_HASH, which is one of the few manifest checks
        # with a live status emitter, so the integrity half does not rest on the
        # console alone.
        entered = 0x0101_004C   # STATUS_ENCODE(INFO,  SEP_MSG_CHECK_MANIFEST_HASH)
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
            "architected channel", entered, rejected,
        )

        # CHK-STIMULUS-SERVED: the device returned both mutated fields, so the DUT
        # was given this row's mixed stimulus rather than the shipped image.
        fd.assert_served_field(self.logger, self._flash, "primary",
                               mm.OFF_MANIFEST_HASH, self._primary_served,
                               "primary manifest_hash")
        fd.assert_served_field(self.logger, self._flash, "backup",
                               mm.OFF_SIGNATURE, self._backup_served,
                               "backup signature[0:8]")
