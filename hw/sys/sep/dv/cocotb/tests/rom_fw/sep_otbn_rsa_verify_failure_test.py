# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""TP061E -- a corrupted RSA signature is rejected by the OTBN verify itself.

PROCEDURE (``TP061E``): generate a primary
manifest with a corrupted RSA signature (single bit flip), boot BL0, watch it
complete the OTBN RSA verify, watch the hash OTBN recovers from the signature
disagree with ``manifest_hash``, watch it fail over to the backup, and require a
terminal error once the backup -- also corrupted -- fails the same way.

WHY THIS IS NOT ``sep_firmware_backup_invalid_signature_test`` WEARING A NEW NAME.
That sibling puts ``BAD_MAGIC`` on the primary and the signature defect on the
BACKUP only, so it covers exactly one leg: a backup whose signature is bad. Two
things it cannot show, and this testcase exists for both.

1. **The retry is triggered BY an invalid signature.** The procedure's step 5 is
   "BL0 routes through ``INVALID_SIGNATURE`` -> backup retry". In the sibling the
   retry is triggered by a broken magic word, which is rejected by
   the manifest header check before any crypto runs, so nothing there says a
   signature failure is a retryable class at all. Here the PRIMARY carries the
   signature defect, so the failover is the signature verdict's own consequence.
2. **OTBN really ran, and the rejection came from its RESULT.** The sibling
   requires ``RSA_PKCS1_FAIL``, which the signature path prints for ANY non-zero return from
   ``rsa_3072_verify`` -- including ``RSA_OTBN_INIT_FAIL``,
   ``RSA_OTBN_LOAD_FAIL`` and ``RSA_EXEC_FAIL``, none of which involve the
   signature. A dead OTBN would satisfy it. This testcase requires
   ``RSA_EXEC`` (``rsa_verify.c:161``, immediately before ``otbn_execute()``)
   followed by ``RSA_PKCS1_FAIL`` (``rsa_verify.c:175``), which is printed only
   when ``verify_pkcs1_v15()`` has compared the modexp result OTBN wrote back
   against ``manifest_hash`` and the padding constants, and found a difference --
   and it FORBIDS the three engine-error markers. That pair is the
   "OTBN-extracted hash mismatch" coverage item, and it is what the sibling
   cannot claim.

STIMULUS, AND THE PROOF THAT IT MEANS WHAT IT SAYS. One bit is flipped in each
slot's signature, at a DIFFERENT byte index per slot so the two mutations cannot
be one write landing twice. Before flipping anything, :meth:`mutate_flash_image`
verifies each slot's SHIPPED signature against the dev0 modulus and shows that
the value OTBN recovers from it is bit-for-bit ``manifest_hash``; after flipping
it shows the recovered value is a different 32 bytes and the PKCS#1 header,
padding and DigestInfo have all collapsed. So "the extracted hash stopped
matching" cannot be satisfied by an image that never matched, and the rejection
is caused by this mutation rather than by anything the packer did. The same
arithmetic the ROM performs -- ``sig^e mod n`` -- is run here in Python, which is
why this is a proof and not a restatement of the offsets.

The signature field is at manifest offset 744, OUTSIDE the 744-byte signed region region
``manifest_hash`` covers, so no re-hash and no re-sign is needed and
``mm.verify_layout`` still passes afterwards. That matters: had the mutation
disturbed the signed region, both slots would be thrown out as ``MANIFEST_HASH_MISMATCH``
in the manifest loop and RSA would never run.

WHY THE ERROR CODE ALONE WOULD BE A WEAK CHECK. ``MANIFEST_ERR_SIG_FAILED``
is returned from SEVEN places on the signature path -- six in
the signature path and one in the helper it calls. In :
a bad signature type (:164), a bad ROM key index (:176), an unpopulated ROM slot
(:193), a bad fuse key selector (:224), an empty fuse key (:234), the RSA verdict
itself (:246), and a SHA-256 timeout inside the key-authorization check (:128). The
terminal status word cannot say which one fired, which is why every other route
is in ``extra_forbidden`` and the marker ordering below is asserted per slot.

``+esrc_noise_force`` IS REQUIRED, and this entry is tagged ``dv_shortcut``.
OTBN parks in ``UrndRefresh`` until EDN grants entropy and the ROM brings up no
entropy chain, so without it both verifies stall at ``RSA_EXEC`` until the
timeout. The plusarg grants the crypto blocks' EDN handshakes only
(``tb_top.sv``, ``+esrc_noise_force``); it touches no RSA input, no
signature, and no assertion here, so a rejection still means the modexp really
ran on the real OTBN and its result really disagreed with ``manifest_hash``. The
entropy_source/CSRNG/EDN chain is NOT exercised by this testcase.

RUNTIME. Both slots run a full RSA-3072 modular exponentiation on OTBN
(~5 ms of simulated time each), which makes this one of the longest tests in
``rom_fw``. See the ``[[tests]]`` entry in ``testlists/rom_fw.toml``.

NOTE ON PASS COUNT, for anyone reading this next to TP061G. The OTBN execution
count observed per boot is LOGGED here but NOT asserted to be one
per slot. The ROM as built performs a single pass (``rsa_verify.c:162`` is the
only ``otbn_execute()`` call site in the linked image), and pinning that number
would turn this testcase into a guard against the double-pass FI mitigation
TP061G asks for. What is asserted is per-slot: at least one ``RSA_EXEC`` and at
least one ``RSA_PKCS1_FAIL`` on each side of the backup read.
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

# The verifier prints one marker on entry and one on the verdict, both in
# rsa_verify.c: RSA_EXEC immediately before otbn_execute(), then RSA_PKCS1_FAIL
# when the modexp result does not reconstruct the expected padding.
_RSA_EXEC = "RSA_EXEC"
_PKCS1_FAIL = "RSA_PKCS1_FAIL"

# The OTBN engine's own failure markers (rsa_verify.c:135,142,164). Each of these
# also ends in RSA_PKCS1_FAIL, so without forbidding them a broken OTBN would be
# indistinguishable from a rejected signature.
_OTBN_ENGINE_FAILURES = ("RSA_OTBN_INIT_FAIL", "RSA_OTBN_LOAD_FAIL", "RSA_EXEC_FAIL")

# Every other route to MANIFEST_ERR_SIG_FAILED
# 224,234 and 128), plus the two checks that precede the signature entirely.
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

# Signature byte flipped per slot. Different indices so the two writes are
# independently attributable, and one bit each because a manifest correct in
# every other respect must still fail authentication.
_PRIMARY_FLIP = (0, 0x01)
_BACKUP_FLIP = (383, 0x80)


def _recovered_em(buf, slot: str, n: int, e: int) -> bytes:
    """What OTBN computes and writes back: ``sig^e mod n``, 384 big-endian bytes.

    ``rsa_3072_verify`` loads the signature and the modulus into OTBN DMEM, runs
    the modexp, reads the result back and hands it to ``verify_pkcs1_v15``
    (``rsa_verify.c:149-173``). Reproducing it here is what lets this testcase
    say "the hash OTBN extracts is X" rather than "the ROM printed a failure".
    """
    base = mm.slot_base(slot)
    sig = bytes(buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES])
    return pow(int.from_bytes(sig, "big"), e, n).to_bytes(pm.RSA_KEY_BYTES, "big")


@pyuvm.test()
class sep_otbn_rsa_verify_failure_test(sep_backup_manifest_fail_base):
    """Both slots' signatures fail the OTBN verify -> retry -> terminal."""

    # The BACKUP's verdict must be the modexp-result mismatch, not merely
    # "RSA reported a failure" -- see the docstring.
    backup_defect_marker = _PKCS1_FAIL
    expected_error = MANIFEST_ERR_SIG_FAILED
    # The primary carries the defect under test as well; the base's default
    # BAD_MAGIC trigger is replaced so the failover is the signature's own
    # consequence, which is the procedure's step 5.
    primary_expected_error = MANIFEST_ERR_SIG_FAILED
    efuse_preload = _EFUSE_PRELOAD
    extra_forbidden = (
        ("RSA_VERIFY_OK", "RSA_VERIFY_OK", "MANIFEST_OK")
        + _OTBN_ENGINE_FAILURES
        + _OTHER_SIG_VERDICTS
    )

    # --- stimulus ----------------------------------------------------------
    def _prove_slot(self, buf, slot: str, tag: str, n: int, e: int) -> bytes:
        """Log the recovered hash for ``slot`` and return it."""
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

        # BEFORE. The shipped slot must verify, and the value OTBN recovers must
        # BE manifest_hash. Without this the run could be rejecting an image that
        # never authenticated, and the mutation would prove nothing.
        pre = self._prove_slot(buf, slot, "pre", n, e)
        assert pre == stored, (
            f"{slot}'s shipped signature does not recover manifest_hash "
            f"(recovered {pre.hex()}, manifest_hash {stored.hex()}); the slot was "
            f"not correctly signed to begin with, so a rejection after the flip "
            f"would not be attributable to the flip"
        )

        sig_before = bytes(buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + 8])
        mm.flip_signature_byte(buf, slot, byte_index=byte_index, xor_mask=mask)

        # AFTER. The write landed, the signed region is untouched, and the recovered value
        # is no longer manifest_hash -- which is exactly what verify_pkcs1_v15()
        # compares (rsa_verify.c:100-105).
        assert bytes(buf[base : base + mm.SIGNED_REGION_END]) == tbs_before, (
            f"{slot}: the signature flip changed signed region bytes; the slot would be "
            f"rejected as MANIFEST_HASH_MISMATCH in the manifest loop and RSA "
            f"would never run"
        )
        mm.verify_layout(buf, slot)  # manifest_hash still matches sha256(signed region)
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
        # Both run BEFORE the signature ( ->
        # :181/:228), so either being non-zero would end the run with a different
        # verdict and the OTBN path under test would never be reached.
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

    # --- checks ------------------------------------------------------------
    @staticmethod
    def _hits(console, marker: str) -> list[int]:
        """Indices of console lines that are EXACTLY ``marker``.

        Exact, not substring: ``RSA_EXEC`` is a prefix of ``RSA_EXEC_FAIL``, and a
        substring match would let an engine failure satisfy the "OTBN ran" check.
        """
        return [i for i, line in enumerate(console) if line.strip() == marker]

    def check_defect_attribution(self, console, i_backup: int) -> None:
        """``RSA_PKCS1_FAIL`` is each slot's own verdict, one on each side.

        The base's default rule -- first occurrence must follow the backup read --
        is wrong here, because the primary carries the same defect and its verdict
        legitimately comes first. Requiring one occurrence on EACH side of the
        backup read is what stops a run that rejected the primary and then never
        evaluated the backup from looking identical.
        """
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
        # Failover ordering, terminal status, quiescence and the no-boot list.
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
        assert i_backup >= 0, "backup read marker missing"  # super() proved it exists

        execs = self._hits(console, _RSA_EXEC)
        pkcs1 = self._hits(console, _PKCS1_FAIL)

        # CHK-OTBN-PER-SLOT: OTBN was driven exactly once per slot. RSA_EXEC is
        # printed once per rsa_3072_verify() call regardless of how many passes it
        # makes internally, so this counts slots rather than passes.
        assert len(execs) == 2, (
            f"{_RSA_EXEC} appeared {len(execs)} time(s) at {execs}, expected "
            f"exactly 2 -- one per slot. Console: {console}"
        )
        assert execs[0] < i_backup < execs[1], (
            f"{_RSA_EXEC} occurrences {execs} do not straddle the backup read at "
            f"line {i_backup}: the two verifications are not one per slot"
        )

        # CHK-OTBN-RESULT-MISMATCH: per slot, OTBN ran and THEN the result was
        # rejected. Ordering is the substance -- the same two markers in the other
        # order would be a run that failed before the engine was driven, which is
        # what the forbidden engine-failure markers also exclude. Together they
        # separate "the signature was rejected" from "OTBN never produced one".
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

        # Recorded, not asserted -- see the docstring's note on pass count.
        log.info(
            "CHK-OTBN-EXEC-COUNT: %d OTBN execution(s) observed this boot, "
            "one per slot; indices %s",
            len(execs),
            execs,
        )

        # --- device evidence --------------------------------------------------
        # The successful half of boot_flash_reinit() prints
        # nothing, so "SPI re-init to the backup address" -- the procedure's second
        # expected result -- can only be observed on the wire.
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
        # Both slots really were well-formed manifests on the wire, so neither
        # rejection is a blank or garbled slot wearing the signature verdict.
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
