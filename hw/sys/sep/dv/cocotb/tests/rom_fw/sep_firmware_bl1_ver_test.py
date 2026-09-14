# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""BL1 security version EQUALS the BL1_VERSION fuse floor -> accepted, boots.

``check_security_version`` rejects only when ``manifest_ver < fuse_ver``
(``bootrom/prod/src/manifest_crypto.c:94-97``), so equality is the ACCEPT BOUNDARY
of the rollback check -- the last value that must be allowed through. This testcase
runs that boundary on the PRIMARY and requires a completed boot.

WHY THE ACCEPT CASE, WHEN THE REFERENCE RUNS THE REJECT CASE.
``sep_firmware_base_test.sv`` burns ``bl_ver_value = 256'hFF`` -- popcount 8 --
into ``efuse_bl1_ver``, while the packer default leaves the manifest at
``security_version: 5``, so ``5 < 8`` and the ROM must reject. It is a
self-consistent REJECT test.

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

The reference's own stated intent, moreover, is the equality case: it writes
the fuse's BL1 version into ``primary.manifest.version`` and
``backup.manifest.version``, i.e. "make the manifest version equal the fuse version".
Two latent defects in the reference defeat that intent -- it reads field
``'BL1_Version'`` while the parser names it ``BL1_VER``, so the
lookup returns ``None`` and the test falls back to 0; and
``manifest.version`` is not a packer key at all, the field the ROM reads being
``security_version`` (``bootrom/prod/include/manifest.h:218``). This testcase sets
``security_version`` directly and asserts ``MFST_VER=`` as an exact value; it does
not port ``manifest.version``.

**The REJECT side is covered TWICE in this testlist**, by
``sep_firmware_backup_invalid_security_version_test`` (fuse floor 8, both slots below
it) and by ``sep_firmware_primary_invalid_security_version_test`` (fuse floor 1,
primary below it and the backup re-signed at the boundary). Neither covers the
primary-side ACCEPT boundary; this testcase does. It is a DIFFERENT CASE from the
reference's, not a correction of it.

**THE COVERAGE THIS ADDS BEYOND THE BOUNDARY: ALL EIGHT THERMOMETER WORDS, EACH
DISTINGUISHABLE.** ``get_security_version_from_fuse`` (``manifest_crypto.c``)
loops over EIGHT 32-bit words of ``BL1_VERSION`` and sums their popcounts. Every
other preload in this tree keeps its bits in word 0 --
``sep_efuse_lc_prod_secver1.toml`` uses ``0x1`` and
``sep_efuse_lc_prod_secver8.toml`` uses ``0xff`` -- so a ROM that read only the first
word would decode all of them correctly. ``sep_efuse_lc_prod_bl1ver36_spread.toml``
gives word ``i`` exactly ``i+1`` set bits, so the total is 1+2+...+8 = 36 and **no
plausible truncated, repeated or
mis-indexed decode of those eight words reaches 36**.

A literal "no other multiset sums to 36" would be false --
8+8+8+8+1+1+1+1 also sums to 36 -- but no decode DEFECT produces that multiset. What
the spread does catch is every systematic misread: read only word 0 (1), read word 0
eight times (8), stop at seven words (29), read one word twice and skip another (any
value but 36), or index with a wrong stride (a different subset sum). The load-bearing
check is not the total alone but ``sorted(per_word) == list(range(1, 9))`` at
:meth:`_check_efuse` plus the exact ``FUSE_VER=0x00000024`` echo.

One bit per word (total 8) would be weaker: eight reads of the SAME word also sum to
8, so it would catch a wrong loop bound but not a wrong index expression. This is
also why the floor is 36 rather than the reference's 8 -- eight non-zero words with
distinct popcounts need at least 36 bits, so matching the reference's VALUE and
distinguishing the eight words cannot both be done. The boundary itself is preserved
because the manifest is raised to match.

The accept boundary ALONE cannot catch a truncated decode -- a smaller floor is still
satisfied by the same manifest, so the run would still boot. What catches it is the
EXACT console echo: ``FUSE_VER=0x00000024`` is a required marker. Worked examples of
what a broken decode would print instead: word 0 only -> ``0x00000001``; word 0 read
eight times -> ``0x00000008``; the first four words -> ``0x0000000a``; the last word
only -> ``0x00000008``. That marker, not the boot, is where this testcase's
thermometer coverage lives.

WHAT ELSE THE RUN MUST SHOW, because "it booted" is not a result:

  * ``FUSE_VER=0x00000024`` then ``MFST_VER=0x00000024``, each EXACTLY ONCE and in
    that order (``manifest_crypto.c``). One slot is attempted, so a second
    occurrence would mean a failover this testcase forbids;
  * ``VERSION_ROLLBACK`` absent -- the rejecting arm did not fire;
  * the rollback check ran BEFORE key selection: ``FUSE_VER`` precedes ``PUBK_SEL=``
    because ``manifest_crypto_validate`` calls ``check_security_version``
    before ``validate_signature``. This is the ordering the key-selection
    testcases rely on to keep their verdicts attributable, and this
    is the one testcase whose stimulus IS the version field, so it is asserted here
    rather than assumed. Be honest about its weight: on an ACCEPT path both stages
    run, so this shows SEQUENCE only. The stronger property -- that a rejected
    version PREEMPTS key selection entirely -- is already proven by
    ``sep_firmware_primary_invalid_security_version_test``, which requires the
    primary's ``PUBK_SEL=`` to come after the BACKUP read;
  * ``RSA_VERIFY_START`` -> ``SIG_VALID`` -> ``CRYPTO_VALIDATE_OK``, after the
    version echoes: the manifest really verified, so acceptance is a completed
    validation and not a skipped one;
  * the DEVICE side: not one read inside the backup slot's span. A silent failover
    also reaches ``MANIFEST_OK``.

PLATFORM ADAPTATION -- MARKERS. The reference asserts
``STATUS: MANIFEST_VALIDATED``, which this ROM DOES emit
(``SEP_MSG_MANIFEST_VALIDATED``, ``manifest_crypto.c``), and
``ERROR: INVALID_SECURITY_VERSION``, whose code ``SEP_MSG_INVALID_SECURITY_VERSION``
(``bootrom/prod/include/status_values.h:9``) is defined and never emitted -- that
gap does not bite here because this port runs the ACCEPT case and needs no
rejection code. The version
values themselves have no architected code on either ROM, so ``FUSE_VER=`` /
``MFST_VER=`` are console echoes in both.

WHAT THIS TESTCASE CANNOT PROVE, AND WHERE THAT IS PROVED INSTEAD. An ACCEPT-only
test cannot exclude a ROM in which the comparison at ``manifest_crypto.c`` has been
deleted while the two ``simputshex32`` echoes remain: printing both
operands does not show the ``<`` executed, and the absence of ``VERSION_ROLLBACK``
plus continuation to ``RSA_VERIFY_START`` is equally consistent with "compared and
accepted" and with "never compared". The ordering assertion above does not close that
either -- order is sequence, not comparison. **The comparison's EXISTENCE is proven by
the two REJECT siblings named earlier.**

BOTH SLOTS ARE RE-SIGNED. ``security_version`` sits inside the TBS
(``bootrom/prod/include/manifest.h:218``, offset 162), so raising it invalidates the
manifest hash and the
shipped dev0 signature. ``env/sep_payload_mutate.reseal`` re-hashes and re-signs with
the same dev0 key, and ``verify_signing_key`` proves beforehand that the local signer
reproduces the packer's shipped signature byte for byte -- so the re-seal is sound by
construction rather than by assertion. The DUT's own OTBN then verifies the result
(``RSA_VERIFY_OK`` / ``SIG_VALID``), so the signature check stays fully ENABLED; this
is not a bypass.

Needs ``+sep_crypto_edn_force``: the primary is valid, so a full RSA-3072 modexp runs
on OTBN, which parks in UrndRefresh until EDN grants entropy. The shortcut grants
OTBN's EDN handshakes only; the RSA assertions are untouched, so ``SIG_VALID`` still
means the signature really verified.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
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

# The thermometer floor the preload burns, and the manifest value this testcase
# writes. Equal: that equality IS the boundary under test.
#
# 36 = 1+2+...+8, because the preload gives word i exactly i+1 set bits so that no
# other combination of the eight words sums to it. The reference's effective floor is
# 8 (sep_firmware_base_test.sv burns 'hFF -> popcount 8), all of it in the low
# byte; matching that VALUE and distinguishing the eight words are mutually exclusive.
_SECURITY_VERSION = 36
_FUSE_VER_ECHO = f"FUSE_VER=0x{_SECURITY_VERSION:08x}"  # manifest_crypto.c
_MFST_VER_ECHO = f"MFST_VER=0x{_SECURITY_VERSION:08x}"  # manifest_crypto.c

_LC_PROD = "LC=PROD"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_PUBK_SEL = "PUBK_SEL="  # manifest_crypto.c
_RSA_START = "RSA_VERIFY_START"  # manifest_crypto.c
_SIG_VALID = "SIG_VALID"  # manifest_crypto.c
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"  # manifest_crypto.c


@pyuvm.test()
class sep_firmware_bl1_ver_test(sep_rom_ot_dma_boot_test):
    """manifest security_version == BL1_VERSION popcount -> accepted, primary boots."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD,
        _PRIMARY_SRC,
        _FUSE_VER_ECHO,
        _MFST_VER_ECHO,
        _RSA_START,
        _SIG_VALID,
        _CRYPTO_OK,
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    # VERSION_ROLLBACK is the load-bearing forbid: it is the arm this boundary must
    # NOT take. The rest exclude a boot that completed for some other reason -- a
    # failover, a skipped crypto chain, or a different rejecting arm firing first.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        "VERSION_ROLLBACK",
        "SBOOT_OFF",
        "FUSE: SBOOT_DIS: 1",
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "CRYPTO_FAIL=",
        "RSA_VERIFY_FAIL",
        "BAD_SIG_TYPE=",
        "BAD_KEY_IDX",
        "BAD_KEY_SEL",
        "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY",
        "PUBK_HASH_MISMATCH",
        "PUBK_HASH_TIMEOUT",
        "KEY_REVOKED",
        "LC_USAGE_CONSTRAINT_FAIL",
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
            f"boot is enabled (manifest_load.c:668-669)"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the whole crypto chain, including the "
            f"rollback check under test, would be skipped"
        )
        # The floor itself, and the property that makes this testcase's thermometer
        # coverage real. Both halves matter: the POPCOUNT is what the ROM decodes,
        # and the SPREAD is what makes a truncated decode observable.
        bl1_ver = image.field_int("BL1_VERSION")
        popcount = bin(bl1_ver).count("1")
        words = [(bl1_ver >> (32 * i)) & 0xFFFF_FFFF for i in range(8)]
        nonzero_words = sum(1 for w in words if w)
        assert popcount == _SECURITY_VERSION, (
            f"BL1_VERSION popcount is {popcount}, expected {_SECURITY_VERSION}: the "
            f"fuse floor must EQUAL the manifest security_version this testcase "
            f"writes, or the run is no longer the accept boundary"
        )
        assert nonzero_words == 8, (
            f"BL1_VERSION has bits in only {nonzero_words} of its 8 words "
            f"({[hex(w) for w in words]}): this testcase's whole thermometer claim "
            f"is that all eight mmio_read32() calls of "
            f"get_security_version_from_fuse (manifest_crypto.c:73-84) contribute, "
            f"and a floor concentrated in one word cannot show that"
        )
        # And each word must contribute a DIFFERENT amount. Eight equal words summing
        # to the right total would be reproduced by reading ONE of them eight times,
        # so an equal spread catches a wrong loop BOUND but not a wrong INDEX
        # expression. With distinct per-word popcounts no other multiset of these
        # eight words reaches the total, and the exact FUSE_VER= marker below
        # discriminates any omitted, repeated or mis-indexed word.
        per_word = [bin(w).count("1") for w in words]
        assert sorted(per_word) == list(range(1, 9)), (
            f"BL1_VERSION per-word popcounts are {per_word}, expected a permutation "
            f"of 1..8. Equal or duplicated per-word contributions would let a "
            f"mis-indexed decode reach the same total, and this testcase's "
            f"thermometer claim rests on that not being possible"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: a revoked key would "
            f"reject the manifest after the version check passed, and this positive "
            f"testcase would fail for a reason that has nothing to do with rollback"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, PUBK_REVOKE=0x%x, "
            "BL1_VERSION popcount=%d spread over %d/8 words %s with per-word "
            "popcounts %s (a permutation of 1..8, so no mis-indexed decode reaches "
            "the same total)",
            lc,
            sboot_dis,
            revoke,
            popcount,
            nonzero_words,
            [hex(w) for w in words],
            per_word,
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
            assert before < _SECURITY_VERSION, (
                f"shipped {slot} security_version is already {before}, which is not "
                f"below the {_SECURITY_VERSION} this testcase writes; the mutation "
                f"would be a no-op or a downgrade and the boundary would not be set "
                f"by this testcase (configs/secure_boot_test.yaml:65 and :130 ship 0)"
            )
            mm.set_security_version(buf, slot, _SECURITY_VERSION)
            got = mm.security_version(buf, slot)
            assert got == _SECURITY_VERSION, (
                f"{slot} security_version reads back {got} after the write, expected "
                f"{_SECURITY_VERSION}"
            )
            pm.reseal(buf, slot)
            # The re-seal must be complete: a slot still carrying a stale payload
            # hash, manifest hash or signature would be rejected for THAT, and this
            # positive testcase would fail for a reason it did not choose.
            pm.verify_sealed(buf, slot)
            self.logger.info("CHK-STIMULUS-%s: %s", slot.upper(), mm.describe(buf, slot))
        self.logger.info(
            "CHK-STIMULUS-BOUNDARY: both slots security_version %d -> %d, re-signed "
            "with dev0 and re-verified sealed; the fuse floor is also %d, so the "
            "manifest sits EXACTLY on the accept boundary of manifest_crypto.c:94",
            0,
            _SECURITY_VERSION,
            _SECURITY_VERSION,
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
        i_sig = index_of(_SIG_VALID)
        i_ok = index_of(_CRYPTO_OK)

        # CHK-ROLLBACK-BOUNDARY: the version check ran on the primary, read the
        # thermometer floor this testcase burned, read the manifest value this
        # testcase wrote, and then let the boot proceed -- in that order. Presence
        # alone would be satisfied by a run that never compared the two.
        assert 0 <= i_psrc < i_fuse < i_mfst < i_rsa < i_sig < i_ok, (
            f"the rollback check did not run on the primary in the architected "
            f"order: primary@{i_psrc} -> {_FUSE_VER_ECHO}@{i_fuse} -> "
            f"{_MFST_VER_ECHO}@{i_mfst} -> {_RSA_START}@{i_rsa} -> "
            f"{_SIG_VALID}@{i_sig} -> {_CRYPTO_OK}@{i_ok}. Console: {console}"
        )
        # CHK-ROLLBACK-BEFORE-KEYSEL: check_security_version (manifest_crypto.c)
        # precedes validate_signature (:369). Every key-selection testcase relies
        # on that ordering to keep its own verdict attributable; this is the
        # testcase whose stimulus is the version field, so it is the right place to
        # assert the ordering rather than inherit it.
        assert 0 <= i_fuse < i_sel, (
            f"{_FUSE_VER_ECHO}@{i_fuse} did not precede {_PUBK_SEL}@{i_sel}: the "
            f"rollback check no longer runs before key selection, which invalidates "
            f"the attribution of every key-selection testcase in this testlist. "
            f"Console: {console}"
        )
        # Exactly once each. One slot is attempted and there is no retry, so a
        # second occurrence would mean the backup also reached the version check.
        for marker in (_FUSE_VER_ECHO, _MFST_VER_ECHO, _RSA_START, _SIG_VALID):
            n = sum(1 for line in console if marker in line)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the primary's). "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-ROLLBACK-BOUNDARY: primary@%d -> %s@%d -> %s@%d (equal, so accepted) "
            "-> %s@%d -> %s@%d -> %s@%d, each exactly once; and the version check "
            "preceded %s@%d",
            i_psrc,
            _FUSE_VER_ECHO,
            i_fuse,
            _MFST_VER_ECHO,
            i_mfst,
            _RSA_START,
            i_rsa,
            _SIG_VALID,
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
