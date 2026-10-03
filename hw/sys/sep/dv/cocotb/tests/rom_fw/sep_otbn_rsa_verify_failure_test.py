# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A corrupted RSA signature in both slots is rejected by the OTBN verify itself.

Each slot must print ``RSA_EXEC`` then ``RSA_PKCS1_FAIL``. Needs ``+esrc_noise_force``: OTBN
stalls without EDN entropy. The plusarg forces the ESRC noise input; the ROM brings up the entropy chain.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_SIG_FAILED,
    sep_backup_manifest_fail_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# RSA_EXEC precedes otbn_execute(); RSA_PKCS1_FAIL marks a modexp result failing PKCS#1.
_RSA_EXEC = "RSA_EXEC"
_PKCS1_FAIL = "RSA_PKCS1_FAIL"

# OTBN engine failures refuse the signature with the same error code.
_OTBN_ENGINE_FAILURES = ("RSA_OTBN_INIT_FAIL", "RSA_OTBN_LOAD_FAIL", "RSA_EXEC_FAIL")

# Key-selection refusals that would preempt or mimic the RSA verdict.
_OTHER_SIG_VERDICTS = (
    "PUBK_ALGO_UNSUPPORTED",
    "PUBK_SLOT_RESERVED",
    "PUBK_SEL_AMBIGUOUS",
    "PUBK_SLOT_UNPROVISIONED",
    "PUBK_OTP_EMPTY",
    "PUBK_HASH_TIMEOUT",
    "PUBK_UNAUTHORIZED",
    "the revocation error code",
)

# One bit per slot at different indices, so each write is independently attributable.
_PRIMARY_FLIP = (0, 0x01)
_BACKUP_FLIP = (383, 0x80)


def _recovered_em(buf, slot: str, n: int, e: int) -> bytes:
    base = mm.slot_base(slot)
    sig = bytes(buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES])
    return pow(int.from_bytes(sig, "big"), e, n).to_bytes(pm.RSA_KEY_BYTES, "big")


@pyuvm.test()
class sep_otbn_rsa_verify_failure_test(sep_backup_manifest_fail_base):
    """Both slots' signatures fail the OTBN verify -> retry -> terminal."""

    backup_defect_marker = _PKCS1_FAIL
    expected_error = MANIFEST_ERR_SIG_FAILED
    primary_expected_error = MANIFEST_ERR_SIG_FAILED
    efuse_preload = _EFUSE_PRELOAD
    extra_forbidden = (
        ("RSA_VERIFY_OK", "RSA_VERIFY_OK", "MANIFEST_OK")
        + _OTBN_ENGINE_FAILURES
        + _OTHER_SIG_VERDICTS
    )

    def _prove_slot(self, buf, slot: str, tag: str, n: int, e: int) -> bytes:
        base = mm.slot_base(slot)
        tbs = bytes(buf[base : base + mm.SIGNED_REGION_END])
        sig = bytes(buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES])
        stored = bytes(buf[base + mm.OFF_MANIFEST_HASH : base + mm.OFF_MANIFEST_HASH + 32])
        em = _recovered_em(buf, slot, n, e)
        extracted = em[-32:]
        self.logger.info(
            "CHK-STIMULUS-OTBN[%s %s]: sig[0:8]=%s manifest_hash=%s "
            "sha256(signed region)=%s OTBN-recovered-hash=%s match=%s pkcs1_valid=%s",
            tag,
            slot,
            sig[:8].hex(),
            stored.hex(),
            hashlib.sha256(tbs).hexdigest(),
            extracted.hex(),
            extracted == stored,
            pm.verify_pkcs1v15_sha256(tbs, sig, n),
        )
        return extracted

    def _corrupt(self, buf: bytearray, slot: str, byte_index: int, mask: int) -> None:
        n, e, _d = pm.slot_signing_key(buf, slot)
        base = mm.slot_base(slot)
        stored = bytes(buf[base + mm.OFF_MANIFEST_HASH : base + mm.OFF_MANIFEST_HASH + 32])
        tbs_before = bytes(buf[base : base + mm.SIGNED_REGION_END])

        pre = self._prove_slot(buf, slot, "pre", n, e)
        assert pre == stored, (
            f"{slot}'s shipped signature does not recover manifest_hash "
            f"(recovered {pre.hex()}, manifest_hash {stored.hex()}); the slot was "
            f"not correctly signed to begin with, so a rejection after the flip "
            f"would not be attributable to the flip"
        )

        sig_before = bytes(buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + 8])
        mm.flip_signature_byte(buf, slot, byte_index=byte_index, xor_mask=mask)

        assert bytes(buf[base : base + mm.SIGNED_REGION_END]) == tbs_before, (
            f"{slot}: the signature flip changed signed region bytes; the slot would be "
            f"rejected as MANIFEST_HASH_MISMATCH in the manifest loop and RSA "
            f"would never run"
        )
        mm.verify_layout(buf, slot)
        post = self._prove_slot(buf, slot, "post", n, e)
        assert post != pre, (
            f"{slot}: signature[{byte_index}] ^= 0x{mask:02x} did not change the "
            f"modexp result; the mutation did not land"
        )
        assert post != stored, (
            f"{slot}: the recovered hash still equals manifest_hash after the "
            f"flip, so the ROM would ACCEPT this signature"
        )
        sig_after = bytes(buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + 8])
        self.logger.info(
            "CHK-STIMULUS-SIG[%s]: signature[%d] ^= 0x%02x (1 bit); sig[0:8] %s -> "
            "%s; signed region hash intact; recovered hash %s -> %s",
            slot,
            byte_index,
            mask,
            sig_before.hex(),
            sig_after.hex(),
            pre.hex()[:16] + "...",
            post.hex()[:16] + "...",
        )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        self._corrupt(buf, "primary", *_PRIMARY_FLIP)
        self._corrupt(buf, "backup", *_BACKUP_FLIP)
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        self.logger.info("CHK-STIMULUS-BACKUP:  %s", mm.describe(buf, "backup"))
        return buf

    def check_efuse(self, image) -> None:
        # Rollback and revocation run before the signature check and would refuse the slot first.
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: revocation runs "
            f"before the signature check, and ROM slot 0 "
            f"must stay usable or the rejection is attributable to revocation"
        )

    @staticmethod
    def _hits(console, marker: str) -> list[int]:
        # Exact match: RSA_EXEC is a prefix of RSA_EXEC_FAIL.
        return [i for i, line in enumerate(console) if line.strip() == marker]

    def check_defect_attribution(self, console, i_backup: int) -> None:
        # The primary fails the same way, so require one verdict on each side of the backup read.
        hits = self._hits(console, _PKCS1_FAIL)
        before = [i for i in hits if i < i_backup]
        after = [i for i in hits if i > i_backup]
        assert len(before) >= 1 and len(after) >= 1, (
            f"{_PKCS1_FAIL} occurrences {hits} do not straddle the backup read at "
            f"line {i_backup}: one must be the primary's verdict and one the "
            f"backup's. Console: {console}"
        )
        self.logger.info(
            "CHK-BACKUP-DEFECT: %s at line(s) %s (primary) and %s (backup, after "
            "the backup read at %d)",
            _PKCS1_FAIL,
            before,
            after,
            i_backup,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        log = self.logger
        i_backup = next(
            (
                i
                for i, line in enumerate(console)
                if f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}" in line
            ),
            -1,
        )
        assert i_backup >= 0, "backup read marker missing"

        execs = self._hits(console, _RSA_EXEC)
        pkcs1 = self._hits(console, _PKCS1_FAIL)

        # RSA_EXEC prints once per rsa_3072_verify() call, however many OTBN passes it makes.
        assert len(execs) == 2, (
            f"{_RSA_EXEC} appeared {len(execs)} time(s) at {execs}, expected "
            f"exactly 2 -- one per slot. Console: {console}"
        )
        assert execs[0] < i_backup < execs[1], (
            f"{_RSA_EXEC} occurrences {execs} do not straddle the backup read at "
            f"line {i_backup}: the two verifications are not one per slot"
        )

        for tag, lo, hi in (("primary", -1, i_backup), ("backup", i_backup, len(console))):
            x = [i for i in execs if lo < i < hi]
            p = [i for i in pkcs1 if lo < i < hi]
            assert x and p, (
                f"{tag}: missing one of {_RSA_EXEC}={x} {_PKCS1_FAIL}={p}. Console: {console}"
            )
            assert x[0] < p[0], (
                f"{tag}: markers out of order -- {_RSA_EXEC}@{x[0]} "
                f"{_PKCS1_FAIL}@{p[0]}. The rejection did not come from the modexp "
                f"result. Console: {console}"
            )
            log.info("CHK-OTBN-%s: %s@%d -> %s@%d", tag.upper(), _RSA_EXEC, x[0], _PKCS1_FAIL, p[0])

        log.info(
            "CHK-OTBN-EXEC-COUNT: %d OTBN execution(s) observed this boot, "
            "one per slot; indices %s",
            len(execs),
            execs,
        )

        # A successful boot_flash_reinit() prints nothing; the backup re-init shows only on SPI.
        txns = self._flash.get_transactions()
        log.info("CHK-SPI-TXNS:\n%s", ev.summarize(txns, self._image_len))
        rds = ev.reads(txns)
        p_hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert p_hit is not None, (
            f"no SPI read covered 0x{mm.PRIMARY_MANIFEST_OFFSET:x}: the primary "
            f"was never fetched, so the run did not fail over FROM it"
        )
        assert b_hit is not None, (
            f"no SPI read covered 0x{mm.BACKUP_MANIFEST_OFFSET:x}: the device was "
            f"never asked for the backup address, so no backup retry occurred"
        )
        p_idx, p_txn = p_hit
        b_idx, b_txn = b_hit
        assert p_idx < b_idx, (
            f"device served the backup address (read[{b_idx}]) before the primary "
            f"(read[{p_idx}]): the transaction order is not a failover"
        )
        for name, addr, txn in (
            ("primary", mm.PRIMARY_MANIFEST_OFFSET, p_txn),
            ("backup", mm.BACKUP_MANIFEST_OFFSET, b_txn),
        ):
            magic = ev.bytes_at(txn, addr, 4)
            assert magic == mm.MANIFEST_MAGIC, (
                f"device returned {magic!r} at 0x{addr:x} for the {name} slot, "
                f"expected {mm.MANIFEST_MAGIC!r}: that slot was not a structurally "
                f"valid manifest, so its rejection is not attributable to the "
                f"signature"
            )
        log.info(
            "CHK-RETRY-ADDR: read[%d] served 0x%06x and read[%d] served 0x%06x, in "
            "that order; both returned a valid %r header and both were rejected",
            p_idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            b_idx,
            mm.BACKUP_MANIFEST_OFFSET,
            mm.MANIFEST_MAGIC,
        )
