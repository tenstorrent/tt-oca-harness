# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A corrupted RSA signature is rejected by the OTBN verify itself, on both slots.

Each slot must run the OTBN modexp, fail ``RSA_PKCS1_FAIL`` and fail over; the ROM then
halts. Needs ``+sep_crypto_edn_force``: the ROM starts no EDN entropy chain for OTBN.
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
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_RSA_START = "RSA_VERIFY_START"
_RSA_EXEC = "RSA_EXEC"            # printed immediately before otbn_execute()
_PKCS1_FAIL = "RSA_PKCS1_FAIL"    # printed only when the modexp result mismatches
_RSA_FAIL = "RSA_VERIFY_FAIL"

# Engine faults also end in RSA_VERIFY_FAIL, so forbid them to prove OTBN ran.
_OTBN_ENGINE_FAILURES = ("RSA_OTBN_INIT_FAIL", "RSA_OTBN_LOAD_FAIL", "RSA_EXEC_FAIL")

# Other routes to MANIFEST_ERR_SIG_FAILED, and the two checks before the signature.
_OTHER_SIG_VERDICTS = ("BAD_SIG_TYPE=", "BAD_KEY_IDX", "BAD_KEY_SEL",
                       "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY", "PUBK_HASH_TIMEOUT",
                       "PUBK_HASH_MISMATCH", "KEY_REVOKED idx=", "VERSION_ROLLBACK")

_PRIMARY_FLIP = (0, 0x01)
_BACKUP_FLIP = (383, 0x80)


def _recovered_em(buf, slot: str, n: int, e: int) -> bytes:
    base = mm.slot_base(slot)
    sig = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES])
    return pow(int.from_bytes(sig, "big"), e, n).to_bytes(pm.RSA_KEY_BYTES, "big")


@pyuvm.test()
class sep_otbn_rsa_verify_failure_test(sep_backup_manifest_fail_base):
    """Both slots' signatures fail the OTBN verify -> retry -> terminal."""

    backup_defect_marker = _PKCS1_FAIL
    expected_error = MANIFEST_ERR_SIG_FAILED
    primary_expected_error = MANIFEST_ERR_SIG_FAILED
    efuse_preload = _EFUSE_PRELOAD
    extra_forbidden = (
        ("SIG_VALID", "RSA_VERIFY_OK", "CRYPTO_VALIDATE_OK")
        + _OTBN_ENGINE_FAILURES
        + _OTHER_SIG_VERDICTS
    )

    def _prove_slot(self, buf, slot: str, tag: str, n: int, e: int) -> bytes:
        base = mm.slot_base(slot)
        tbs = bytes(buf[base:base + mm.TBS_LEN])
        sig = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE
                        + pm.RSA_KEY_BYTES])
        stored = bytes(buf[base + mm.OFF_MANIFEST_HASH:base + mm.OFF_MANIFEST_HASH + 32])
        em = _recovered_em(buf, slot, n, e)
        extracted = em[-32:]
        self.logger.info(
            "CHK-STIMULUS-OTBN[%s %s]: sig[0:8]=%s manifest_hash=%s "
            "sha256(TBS)=%s OTBN-recovered-hash=%s match=%s pkcs1_valid=%s",
            tag, slot, sig[:8].hex(), stored.hex(), hashlib.sha256(tbs).hexdigest(),
            extracted.hex(), extracted == stored,
            pm.verify_pkcs1v15_sha256(tbs, sig, n),
        )
        return extracted

    def _corrupt(self, buf: bytearray, slot: str, byte_index: int, mask: int) -> None:
        n, e, _d = pm.load_rsa_private_key()
        base = mm.slot_base(slot)
        stored = bytes(buf[base + mm.OFF_MANIFEST_HASH:base + mm.OFF_MANIFEST_HASH + 32])
        tbs_before = bytes(buf[base:base + mm.TBS_LEN])

        pre = self._prove_slot(buf, slot, "pre", n, e)
        assert pre == stored, (
            f"{slot}'s shipped signature does not recover manifest_hash "
            f"(recovered {pre.hex()}, manifest_hash {stored.hex()}); the slot was "
            f"not correctly signed to begin with, so a rejection after the flip "
            f"would not be attributable to the flip"
        )

        sig_before = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + 8])
        mm.flip_signature_byte(buf, slot, byte_index=byte_index, xor_mask=mask)

        assert bytes(buf[base:base + mm.TBS_LEN]) == tbs_before, (
            f"{slot}: the signature flip changed TBS bytes; the slot would be "
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
        sig_after = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + 8])
        self.logger.info(
            "CHK-STIMULUS-SIG[%s]: signature[%d] ^= 0x%02x (1 bit); sig[0:8] %s -> "
            "%s; TBS hash intact; recovered hash %s -> %s",
            slot, byte_index, mask, sig_before.hex(), sig_after.hex(),
            pre.hex()[:16] + "...", post.hex()[:16] + "...",
        )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        self._corrupt(buf, "primary", *_PRIMARY_FLIP)
        self._corrupt(buf, "backup", *_BACKUP_FLIP)
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        self.logger.info("CHK-STIMULUS-BACKUP:  %s", mm.describe(buf, "backup"))
        return buf

    def check_efuse(self, image) -> None:
        # Rollback and revocation run before the signature check and would pre-empt it.
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before the signature check (manifest_crypto.c:364)"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: revocation runs "
            f"before the signature check (manifest_crypto.c:181), and ROM slot 0 "
            f"must stay usable or the rejection is attributable to revocation"
        )

    @staticmethod
    def _hits(console, marker: str) -> list[int]:
        # Exact match: RSA_EXEC is a prefix of RSA_EXEC_FAIL.
        return [i for i, line in enumerate(console) if line.strip() == marker]

    def check_defect_attribution(self, console, i_backup: int) -> None:
        # The primary has the same defect, so its verdict precedes the backup read.
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
            "the backup read at %d)", _PKCS1_FAIL, before, after, i_backup,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        log = self.logger
        i_backup = next((i for i, line in enumerate(console)
                         if f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}" in line), -1)
        assert i_backup >= 0, "backup read marker missing"

        starts = self._hits(console, _RSA_START)
        execs = self._hits(console, _RSA_EXEC)
        pkcs1 = self._hits(console, _PKCS1_FAIL)
        fails = self._hits(console, _RSA_FAIL)

        # RSA_VERIFY_START prints once per call, however many passes the verify makes.
        assert len(starts) == 2, (
            f"{_RSA_START} appeared {len(starts)} time(s) at {starts}, expected "
            f"exactly 2 -- one per slot. Console: {console}"
        )
        assert starts[0] < i_backup < starts[1], (
            f"{_RSA_START} occurrences {starts} do not straddle the backup read at "
            f"line {i_backup}: the two verifications are not one per slot"
        )

        assert any(i < i_backup for i in execs) and any(i > i_backup for i in execs), (
            f"{_RSA_EXEC} occurrences {execs} do not straddle the backup read at "
            f"line {i_backup}: OTBN was not driven for both slots. Console: {console}"
        )

        for tag, lo, hi in (("primary", -1, i_backup),
                            ("backup", i_backup, len(console))):
            s = [i for i in starts if lo < i < hi]
            x = [i for i in execs if lo < i < hi]
            p = [i for i in pkcs1 if lo < i < hi]
            f = [i for i in fails if lo < i < hi]
            assert s and x and p and f, (
                f"{tag}: missing one of {_RSA_START}={s} {_RSA_EXEC}={x} "
                f"{_PKCS1_FAIL}={p} {_RSA_FAIL}={f}. Console: {console}"
            )
            assert s[0] < x[0] < p[0] < f[0], (
                f"{tag}: markers out of order -- {_RSA_START}@{s[0]} "
                f"{_RSA_EXEC}@{x[0]} {_PKCS1_FAIL}@{p[0]} {_RSA_FAIL}@{f[0]}. The "
                f"rejection did not come from the modexp result. Console: {console}"
            )
            log.info(
                "CHK-OTBN-%s: %s@%d -> %s@%d -> %s@%d -> %s@%d",
                tag.upper(), _RSA_START, s[0], _RSA_EXEC, x[0],
                _PKCS1_FAIL, p[0], _RSA_FAIL, f[0],
            )

        # Not asserted: a double-pass fault-injection mitigation would change the count.
        log.info("CHK-OTBN-EXEC-COUNT: %d OTBN execution(s) observed this boot "
                 "(%d slots verified); indices %s", len(execs), len(starts), execs)

        # A successful flash re-init prints nothing, so check the backup fetch on SPI.
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
        for name, addr, txn in (("primary", mm.PRIMARY_MANIFEST_OFFSET, p_txn),
                                ("backup", mm.BACKUP_MANIFEST_OFFSET, b_txn)):
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
            p_idx, mm.PRIMARY_MANIFEST_OFFSET, b_idx, mm.BACKUP_MANIFEST_OFFSET,
            mm.MANIFEST_MAGIC,
        )
