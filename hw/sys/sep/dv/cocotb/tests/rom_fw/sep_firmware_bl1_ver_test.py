# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""BL1 security version EQUALS the BL1_VERSION fuse floor -> accepted, boots.

``check_security_version`` rejects only when ``manifest_ver < fuse_ver``
(``bootrom/prod/src/), so equality is the ACCEPT BOUNDARY
of the rollback check -- the last value that must be allowed through. This testcase
runs that boundary on the PRIMARY and requires a completed boot.

WHY THE ACCEPT CASE, WHEN THE REFERENCE RUNS THE REJECT CASE. Stated plainly, because
the two are different cases and the choice has to be justified rather than assumed.
``sep_firmware_base_test.sv`` burns ``bl_ver_value = 256'hFF`` -- popcount 8 --
into ``efuse_bl1_ver``, while the packer default leaves the manifest at
``security_version: 5``,
so ``5 < 8`` and the ROM must reject. It is a self-consistent REJECT test; the earlier
claim that it contradicts itself was investigated on the VP half and WITHDRAWN
(``batch_runs_0904_vp/FINDINGS.md`` F11 item 3), and is not repeated here.

**BUT THE REFERENCE DOES NOT ENFORCE THAT REJECTION, AND THAT CHANGES WHAT THIS PORT
IS REPLACING.** Its two checks are ``log.info`` calls, not assertions: they call
``search_string``, which returns a (possibly empty) match list and never raises, and
then print ``PASSED`` or an ``ASSERTING_RED_FLAG:`` string accordingly. It ends with
no ``assert`` anywhere, and the preloader it awaits runs
with ``cold_scratch_check=False``. So the reference **cannot fail on either
outcome**. This port is therefore not replacing a strong REJECT check with a weak
ACCEPT one; it is replacing a REJECT-INTENT test that enforces nothing with an
ACCEPT test that enforces 14 required markers, 16 forbidden markers, an ordering
chain, four exactly-once counts and two device-side properties.

The reference's own stated intent, moreover, is the equality case: writes
the fuse's BL1 version into ``primary.manifest.version`` and
``backup.manifest.version``, i.e. "make the manifest version equal the fuse version".
Two latent defects in the reference defeat that intent -- reads field
``'BL1_Version'`` while the parser names it ``BL1_VER``, so the
lookup returns ``None`` and the test falls back to 0; and
``manifest.version`` is not a packer key at all, the field the ROM reads being
``security_version`` (``bootrom/prod/include/). Both were recorded on
the VP half as ``batch_runs_0904_vp/FINDINGS.md`` F06 / F10 item 3, whose instruction
to this batch -- set ``security_version`` directly and assert ``MFST_VER=`` as an
exact value, do not port ``manifest.version`` -- is what this testcase does.

Implementing the intent rather than the accident is defensible here for a second,
independent reason: **the REJECT side is already covered TWICE in this testlist**, by
``sep_firmware_backup_invalid_security_version_test`` (fuse floor 8, both slots below
it) and by ``sep_firmware_primary_invalid_security_version_test`` (fuse floor 1,
primary below it and the backup re-signed at the boundary). Neither covers the
primary-side ACCEPT boundary, and no testcase covered it before this one. This is a
DELIBERATELY DIFFERENT CASE, not a correction of a broken reference, and it is
recorded that way in the row's ``flow_deviation``.

**THE COVERAGE THIS ADDS BEYOND THE BOUNDARY: ALL EIGHT THERMOMETER WORDS, EACH
DISTINGUISHABLE.** ``get_security_version_from_fuse``
loops over EIGHT 32-bit words of ``BL1_VERSION`` and sums their popcounts. Every
existing preload in this tree puts its bits in word 0 --
``sep_efuse_lc_prod_secver1.toml`` uses ``0x1`` and
``sep_efuse_lc_prod_secver8.toml`` uses ``0xff`` -- so a ROM that read only the first
word would decode all of them correctly. Batch R1 recorded that gap deliberately
(``batch_runs_0904_rtl/RUN_JOURNAL.md``, "Known gaps left open"). This testcase closes
it: ``sep_efuse_lc_prod_bl1ver36_spread.toml`` gives word ``i`` exactly ``i+1`` set
bits, so the total is 1+2+...+8 = 36 and **no plausible truncated, repeated or
mis-indexed decode of those eight words reaches 36**.

Stated that way on purpose. A literal "no other multiset sums to 36" would be false --
8+8+8+8+1+1+1+1 also sums to 36 -- but no decode DEFECT produces that multiset. What
the spread does catch is every systematic misread: read only word 0 (1), read word 0
eight times (8), stop at seven words (29), read one word twice and skip another (any
value but 36), or index with a wrong stride (a different subset sum). The load-bearing
check is not the total alone but ``sorted(per_word) == list(range(1, 9))`` at
:meth:`_check_efuse` plus the exact ``FUSE_VER=0x00000024`` echo.

An earlier draft used one bit per word (total 8). A reviewer correctly showed that was
weaker: eight reads of the SAME word also sum to 8, so it caught a wrong loop bound
but not a wrong index expression. This is also why the floor is 36 rather
than the reference's 8 -- eight non-zero words with distinct popcounts need at least
36 bits, so matching the reference's VALUE and distinguishing the eight words cannot
both be done. The boundary itself is preserved because the manifest is raised to match.

The accept boundary ALONE cannot catch a truncated decode -- a smaller floor is still
satisfied by the same manifest, so the run would still boot. What catches it is the
EXACT console echo: ``FUSE_VER=0x00000024`` is a required marker. Worked examples of
what a broken decode would print instead: word 0 only -> ``0x00000001``; word 0 read
eight times -> ``0x00000008``; the first four words -> ``0x0000000a``; the last word
only -> ``0x00000008``. That marker, not the boot, is where this testcase's
thermometer coverage lives.

WHAT ELSE THE RUN MUST SHOW, because "it booted" is not a result:

  * ``FUSE_VER=0x00000024`` then ``MFST_VER=0x00000024``, each EXACTLY ONCE and in
    that order. One slot is attempted, so a second
    occurrence would mean a failover this testcase forbids;
  * ``VERSION_ROLLBACK``  absent -- the rejecting arm did not fire;
  * the rollback check ran BEFORE key selection: ``FUSE_VER`` precedes ``PUBK_SEL=``
    because ``manifest_crypto_validate`` calls ``check_security_version``
     before ``validate_signature``. This is the ordering the key
    testcases of batches R1/R2 rely on to keep their verdicts attributable, and this
    is the one testcase whose stimulus IS the version field, so it is asserted here
    rather than assumed. Be honest about its weight: on an ACCEPT path both stages
    run, so this shows SEQUENCE only. The stronger property -- that a rejected
    version PREEMPTS key selection entirely -- is already proven by
    ``sep_firmware_primary_invalid_security_version_test``, which requires the
    primary's ``PUBK_SEL=`` to come after the BACKUP read;
  * ``RSA_EXEC`` -> ``RSA_VERIFY_OK`` -> ``MANIFEST_OK``, after the
    version echoes: the manifest really verified, so acceptance is a completed
    validation and not a skipped one;
  * the DEVICE side: not one read inside the backup slot's span. A silent failover
    also reaches ``MANIFEST_OK``.

PLATFORM ADAPTATION -- MARKERS. The reference asserts
``STATUS: MANIFEST_VALIDATED``, which this ROM DOES emit
(``SEP_MSG_MANIFEST_VALIDATED``, ), and
``ERROR: INVALID_SECURITY_VERSION``, whose code ``SEP_MSG_INVALID_SECURITY_VERSION``
(``bootrom/prod/include/status_values.h:9``) is defined and never emitted -- the
wider gap is ``batch_runs_0904_rtl/FINDINGS.md`` R04, and it does not bite here
because this port runs the ACCEPT case and needs no rejection code. The version
values themselves have no architected code on either ROM, so ``FUSE_VER=`` /
``MFST_VER=`` are console echoes in both.

WHAT THIS TESTCASE CANNOT PROVE, AND WHERE THAT IS PROVED INSTEAD. An ACCEPT-only
test cannot exclude a ROM in which the comparison has been
deleted while the two ``simputshex32`` echoes remain: printing both
operands does not show the ``<`` executed, and the absence of ``VERSION_ROLLBACK``
plus continuation to ``RSA_EXEC`` is equally consistent with "compared and
accepted" and with "never compared". The ordering assertion above does not close that
either -- order is sequence, not comparison. **The comparison's EXISTENCE is proven by
the two REJECT siblings named earlier**, which is exactly why keeping them matters and
why removing either would have been a weakening rather than a tidy-up.

BOTH SLOTS ARE RE-SIGNED. ``security_version`` sits inside the TBS
(``bootrom/prod/include/, offset 162), so raising it invalidates the
manifest hash and the
shipped dev0 signature. ``env/sep_oca_payload.reseal`` re-hashes and re-signs with
the same dev0 key, and ``verify_signing_key`` proves beforehand that the local signer
reproduces the packer's shipped signature byte for byte -- so the re-seal is sound by
construction rather than by assertion. The DUT's own OTBN then verifies the result
(``RSA_VERIFY_OK`` / ``RSA_VERIFY_OK``), so the signature check stays fully ENABLED; this
is not a bypass.

Needs ``+esrc_noise_force``: the primary is valid, so a full RSA-3072 modexp runs
on OTBN, which parks in UrndRefresh until EDN grants entropy. The shortcut grants
OTBN's EDN handshakes only; the RSA assertions are untouched, so ``RSA_VERIFY_OK`` still
means the signature really verified.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_oca_mutate as mm
from env import sep_oca_payload as pm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod_bl1ver36_spread.toml"
)

# The device flag word the preload burns, and the value this testcase writes into
# both manifests. Equal on purpose: under the superset rule
# ``(device & ~manifest) == 0``, equality IS the accept boundary -- one flag fewer
# and the slot is refused.
#
# The platform reads the LOW 16 BYTES of the 32-byte BL1_VERSION bank, so only
# these four words of the preload participate. They carry distinct flags, so a
# manifest omitting any one of them rejects -- which is what makes a truncated
# read observable through the verdict even though the echo shows 32 bits.
_DEVICE_FLAGS = 0x0000000F_00000007_00000003_00000001
_FUSE_VER_ECHO = f"FUSE_VER=0x{_DEVICE_FLAGS & 0xFFFF_FFFF:08x}"
_MFST_VER_ECHO = f"MFST_VER=0x{_DEVICE_FLAGS & 0xFFFF_FFFF:08x}"

_LC_PROD = "LC=PROD"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_PUBK_SEL = "PUBK_SEL="  #
_RSA_START = "RSA_EXEC"  #
_RSA_VERIFY_OK = "RSA_VERIFY_OK"

_CRYPTO_OK = "MANIFEST_OK"


@pyuvm.test()
class sep_firmware_bl1_ver_test(sep_rom_ot_dma_boot_test):
    """manifest security_version carries every BL1_VERSION flag -> accepted, primary boots."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD,
        _PRIMARY_SRC,
        _FUSE_VER_ECHO,
        _MFST_VER_ECHO,
        _RSA_START,
        _RSA_VERIFY_OK,
        _CRYPTO_OK,
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    # VERSION_ROLLBACK is the load-bearing forbid: it is the arm this boundary must
    # NOT take. The rest exclude a boot that completed for some other reason -- a
    # failover, a skipped crypto chain, or a different rejecting arm firing first.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        "SBOOT_OFF",
        "FUSE: SBOOT_DIS: 1",
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "MANIFEST_ERR=",
        "RSA_PKCS1_FAIL",
        "PUBK_ALGO_UNSUPPORTED",
        "PUBK_SLOT_RESERVED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_OTP_EMPTY",
        "PUBK_UNAUTHORIZED",
        "PUBK_HASH_TIMEOUT",
    )

    # --- stimulus ----------------------------------------------------------
    def build_efuse_image(self):
        assert _EFUSE_PRELOAD.is_file(), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): the rollback check is "
            f"reached through manifest_crypto_validate, which only runs when secure "
            f"boot is enabled"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the whole crypto chain, including the "
            f"rollback check under test, would be skipped"
        )
        # The device flags themselves, and the spread that makes a truncated read
        # observable. Only the low 16 bytes are read by the platform, so those are
        # what must match; bits above them are burned but out of the field's reach.
        bl1_ver = image.field_int("BL1_VERSION")
        low16 = bl1_ver & ((1 << 128) - 1)
        words = [(low16 >> (32 * i)) & 0xFFFF_FFFF for i in range(4)]
        assert low16 == _DEVICE_FLAGS, (
            f"BL1_VERSION's low 16 bytes are 0x{low16:032x}, expected "
            f"0x{_DEVICE_FLAGS:032x}: the device flags must EQUAL what this testcase "
            f"writes into both manifests, or the run is no longer the accept boundary"
        )
        assert all(words), (
            f"BL1_VERSION's low 16 bytes have an empty word ({[hex(w) for w in words]}): "
            f"the claim this testcase rests on is that a manifest omitting any word's "
            f"flags is refused, and a word with no flags cannot be omitted"
        )
        assert len(set(words)) == len(words), (
            f"BL1_VERSION's low words are {[hex(w) for w in words]}, which repeat. "
            f"Distinct words are what make a mis-indexed read observable: reading one "
            f"word four times would reproduce an all-equal field exactly"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: a revoked key would "
            f"reject the manifest after the version check passed, and this positive "
            f"testcase would fail for a reason that has nothing to do with rollback"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, PUBK_REVOKE=0x%x, "
            "BL1_VERSION low 16 bytes = %s, four distinct non-empty words, so a read "
            "that truncated or mis-indexed them would change the verdict",
            lc,
            sboot_dis,
            revoke,
            [hex(w) for w in words],
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            # Anchor before mutating: the shipped slot is fully sealed, its modulus
            # is the dev0 key the ROM has in slot 0, and the local signer reproduces
            # the packer's own signature byte for byte. Only then is a re-seal a
            # sound operation rather than an assumption.
            pm.verify_sealed(buf, slot)
            mm.verify_public_key(buf, slot)
            pm.verify_signing_key(buf, slot)

            before = mm.security_version(buf, slot)
            assert before & _DEVICE_FLAGS != _DEVICE_FLAGS, (
                f"shipped {slot} security_version 0x{before:032x} already carries "
                f"every device flag, so the write would be a no-op and the boundary "
                f"would not be set by this testcase"
            )
            mm.set_security_version(buf, slot, _DEVICE_FLAGS)
            got = mm.security_version(buf, slot)
            assert got == _DEVICE_FLAGS, (
                f"{slot} security_version reads back 0x{got:032x} after the write, "
                f"expected 0x{_DEVICE_FLAGS:032x}"
            )
            pm.reseal(buf, slot)
            # The re-seal must be complete: a slot still carrying a stale payload
            # hash, manifest hash or signature would be rejected for THAT, and this
            # positive testcase would fail for a reason it did not choose.
            pm.verify_sealed(buf, slot)
            self.logger.info("CHK-STIMULUS-%s: %s", slot.upper(), mm.describe(buf, slot))
        self.logger.info(
            "CHK-STIMULUS-BOUNDARY: both slots security_version -> 0x%032x, re-signed "
            "and re-verified sealed; the device carries exactly those flags, so the "
            "manifest sits EXACTLY on the accept boundary of the superset rule",
            _DEVICE_FLAGS,
        )
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

    # --- checks ------------------------------------------------------------
    def check_transport(self, console: list[str], flash) -> None:
        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        i_psrc = index_of(_PRIMARY_SRC)
        i_fuse = index_of(_FUSE_VER_ECHO)
        i_mfst = index_of(_MFST_VER_ECHO)
        i_sel = index_of(_PUBK_SEL)
        i_rsa = index_of(_RSA_START)
        i_sig = index_of(_RSA_VERIFY_OK)
        i_ok = index_of(_CRYPTO_OK)

        # CHK-ROLLBACK-BOUNDARY: the version check ran on the primary, read the
        # device flags this testcase burned, read the manifest value this testcase
        # wrote, and then let the boot proceed -- in that order. Presence alone
        # would be satisfied by a run that never compared the two.
        assert 0 <= i_psrc < i_mfst < i_fuse < i_rsa < i_sig < i_ok, (
            f"the rollback check did not run on the primary in the architected "
            f"order: primary@{i_psrc} -> {_MFST_VER_ECHO}@{i_mfst} -> "
            f"{_FUSE_VER_ECHO}@{i_fuse} -> {_RSA_START}@{i_rsa} -> "
            f"{_RSA_VERIFY_OK}@{i_sig} -> {_CRYPTO_OK}@{i_ok}. Console: {console}"
        )
        # CHK-ROLLBACK-AFTER-KEYSEL-BEFORE-SIGNATURE: anti-rollback sits BETWEEN
        # root-key authorization and the signature. Both halves are load-bearing and
        # neither is inherited: the key-selection testcases rely on reaching the key
        # decision before this check can reject, and the reject siblings rely on a
        # rolled-back manifest never being handed to the verifier.
        assert 0 <= i_sel < i_fuse < i_rsa, (
            f"the version comparison is not between key selection and the "
            f"verifier: {_PUBK_SEL}@{i_sel} -> {_FUSE_VER_ECHO}@{i_fuse} -> "
            f"{_RSA_START}@{i_rsa}. Console: {console}"
        )
        # One slot is attempted and there is no retry, so each marker's count is
        # fixed by how many times the ROM emits it per slot. The device flags are
        # read TWICE: the library re-runs the version check after the signature
        # (OCA_RECHECK_SECURITY_VERSION), which is fault-injection hardening, so
        # a count of one there would mean the recheck did not happen.
        for marker, want in (
            (_FUSE_VER_ECHO, 2),
            (_MFST_VER_ECHO, 1),
            (_RSA_START, 1),
            (_RSA_VERIFY_OK, 1),
        ):
            n = sum(1 for line in console if marker in line)
            assert n == want, (
                f"{marker} appeared {n} times, expected {want} (the primary's). Console: {console}"
            )
        self.logger.info(
            "CHK-ROLLBACK-BOUNDARY: primary@%d -> %s@%d -> %s@%d (equal, so accepted) "
            "-> %s@%d -> %s@%d -> %s@%d, each exactly once; and it followed %s@%d",
            i_psrc,
            _MFST_VER_ECHO,
            i_mfst,
            _FUSE_VER_ECHO,
            i_fuse,
            _RSA_START,
            i_rsa,
            _RSA_VERIFY_OK,
            i_sig,
            _CRYPTO_OK,
            i_ok,
            _PUBK_SEL,
            i_sel,
        )

        # --- device evidence -------------------------------------------------
        txns = flash.get_transactions()
        rds = ev.reads(txns)
        assert rds, (
            f"flash BFM served no read transactions, so nothing was fetched over SPI "
            f"and the boot did not come from this device. All {len(txns)} "
            f"transactions: {[hex(t['opcode']) for t in txns]}"
        )
        hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        assert hit is not None, (
            f"no SPI read covered the primary manifest address "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:x}: the boot did not come from the "
            f"primary address"
        )
        idx, txn = hit
        magic = ev.bytes_at(txn, mm.PRIMARY_MANIFEST_OFFSET, 4)
        assert magic == mm.MANIFEST_MAGIC, (
            f"device returned {magic!r} at 0x{mm.PRIMARY_MANIFEST_OFFSET:x}, expected "
            f"{mm.MANIFEST_MAGIC!r}"
        )
        # CHK-NO-FAILOVER: the channel the ROM cannot fake. Both slots carry the same
        # accepted version here, so a failover would still boot and still print the
        # same version echoes -- the device record is what pins the result to the
        # PRIMARY.
        backup_hits = ev.slot_read_indices(rds, "backup", self._image_len)
        assert not backup_hits, (
            f"device served {len(backup_hits)} read(s) inside the backup slot span "
            f"(read indices {backup_hits}): the primary alone did not serve this "
            f"boot, so the accepted version cannot be attributed to the primary"
        )
        self.logger.info(
            "CHK-NO-FAILOVER: read[%d] at 0x%06x returned magic %r, and no read "
            "touched the backup span across %d reads -- the PRIMARY served this boot",
            idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            magic,
            len(rds),
        )
