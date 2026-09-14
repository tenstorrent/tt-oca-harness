# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The chiplet fuse holds the WRONG digest -> both slots refused, terminally.

**THIS TESTCASE CLOSES THE DIGEST-SOURCE CLASS THAT
``rom_fw/sep_chiplet_pubkey_base.py`` DISCLOSES**, and it does so without a second
private key.

============================================================================
THE GAP, AND WHY IT DOES NOT NEED A SECOND SIGNING KEY
============================================================================

Only one usable RSA-3072 private key ships here
(``bootrom/prod/tools/tt-boot-manifest/tests/signing_keys/rsa_private_key.dev0.pem``;
the ``ec_private_key.pem`` beside it is unusable because this ROM implements
RSA-3072 only). So every chiplet member's fuse digest must EQUAL the ROM's
compiled-in ``public_key_digests[0]`` (``key_digests.c``) or the image
could not verify at all. The consequence, stated in that base's docstring: a ROM
that took the fused arm, tested the right revocation bit, read the right fuse
address and then compared the modulus against ``public_key_digests[0]`` instead
of the fuse it had just read would boot in
``sep_firmware_chiplet_pubkey_0_test`` and be refused in
``sep_firmware_chiplet_pubkey_0_revoke_test``, exactly as expected, and nothing
in that family could see it.

Closing this needs no second committed private KEY. It needs the FUSE to differ
from ``public_key_digests[0]``, plus a NEGATIVE assertion:

  * **correct ROM:** ``read_fuse_key`` returns the decoy, ``check_pubkey_hash``
    fails on it (``manifest_crypto.c``), both slots are refused,
    ``MANIFEST_ALL_FAILED``, ``CRYPTO_FAIL=0x00030016``;
  * **ROM comparing against the compiled-in table:** the modulus matches, the
    image verifies, the part **boots** -- and this testcase FAILS.

**IT ALSO CATCHES THE WRONG-FUSE-ADDRESS CLASS, BECAUSE THE UNSELECTED FUSE
HOLDS THE REAL DIGEST.** ``sep_efuse_lc_prod_chiplet_key0_wrong_digest.toml``
puts the decoy in ``CHIPLET_PUBK_HASH0`` -- the fuse ``PUBK_SEL_FUSE_KEY_0``
selects -- and leaves the REAL dev0 digest in ``CHIPLET_PUBK_HASH1``. A ROM that
read the wrong chiplet fuse would therefore find a digest that matches, verify,
and boot, so this testcase fails on that defect too. Two different decoys would
catch only the compiled-in-table class; leaving the real digest in the unselected
fuse is strictly more sensitive. The cost is attribution, not detection -- a
failure here does not by
itself say which wrong source was used, and the sibling
``sep_firmware_chiplet_pubkey_0_test`` (HASH0 real, HASH1 decoy) is what
separates them.

Those three fuse values are byte-identical to
``sep_efuse_lc_prod_chiplet_key1.toml``'s, which makes this testcase and
``sep_firmware_chiplet_pubkey_1_test`` a MATCHED PAIR on the FUSE side: one fuse
image, two manifests differing only in ``public_key_sel``, opposite verdicts.
That mirrors the matched-pair-on-one-image shape of the ROM-slot families.

**WHAT IT DOES NOT CATCH.** A ROM deriving the fuse-key digest addresses as
``CHIPLET_PUBK_REVOKE + 0x100/0x120`` instead of ``+0x110/0x130`` (the derivation
``manifest_crypto.c`` warns against) is not discriminated by a digest-source test.
That base lands ``0x10`` BELOW ``CHIPLET_PUBK_HASH0``, so ``read_fuse_key`` returns
four unrelated non-zero words followed by HASH0's first four: a digest that matches
nothing, producing ``PUBK_HASH_MISMATCH`` and ``0x00030016`` -- the outcome this
testcase REQUIRES. **A ROM with that derivation passes here.** The class this
testcase closes is "the ROM compared against the wrong SOURCE", not "the ROM read a
malformed address"; the second is covered by the positive members, which would fail
on it.

============================================================================
WHAT MAKES THE REJECTION ATTRIBUTABLE
============================================================================

Both slots select ``PUBK_SEL_FUSE_KEY_0`` and are re-signed with dev0 by
``select_chiplet_fuse_key`` -- **the same two calls, on the same shipped image,
that the positive member ``sep_firmware_chiplet_pubkey_0_test`` makes**, so the
flash images of the two testcases are byte-identical and the ONLY difference
between "boots" and "refused" is the two fuse words. That is the matched-pair
shape the ROM-slot families use, applied to the digest instead of to a
revocation bit.

Revocation must not be what refuses this image, or the digest comparison is never
reached: ``check_pubkey_revoked`` runs at ``manifest_crypto.c`` and
``check_pubkey_hash`` only. So ``CHIPLET_PUBK_REVOKE`` bits 16 and 17
are CLEAR, ``PUBK_REVOKE=0x00000001`` is required exactly twice (the fuse word
the ROM read, once per slot, proving the revocation check ran and PERMITTED the
key), and ``KEY_REVOKED`` is forbidden outright.

Bit 0 -- ROM development key 0 -- is blown, as in every member of this family.
It is the ROM-key-arm counterfactual: inert on a correct ROM, but a ROM that
ignored ``public_key_sel.selection`` and took the ROM-key arm with index 0 would
print ``KEY_REVOKED idx=0x00000000`` and refuse the image for the wrong reason.
Forbidding ``KEY_REVOKED`` catches that too.

``RSA_VERIFY_START`` and ``SIG_VALID`` are forbidden: the digest bind precedes
``rsa_3072_verify`` (``manifest_crypto.c`` then), so a run that
reached the verifier did not fail where this testcase says it failed. No
``+sep_crypto_edn_force`` is passed, and none is needed.

``PUBK_HASH_TIMEOUT`` is forbidden as well, and it is not decoration:
``check_pubkey_hash`` returns ``MANIFEST_ERR_SIG_FAILED`` on a SHA-256 timeout
(``manifest_crypto.c``) and ``MANIFEST_ERR_KEY_HASH_MISMATCH`` only on a
real mismatch, so requiring ``0x00030016`` already excludes the
timeout path -- but the console token names it directly.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_KEY_HASH_MISMATCH,
    sep_backup_manifest_fail_base,
)
from rom_fw.sep_chiplet_pubkey_base import (
    PUBK_REVOKE_BIT_CHIPLET_HASH,
    ROM_ARM_KEY_REVOKED,
    select_chiplet_fuse_key,
)

_EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"

_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

_CHIPLET_KEY = 0
# manifest.h -- public_key_sel is {index:4, selection:3}, so a selection of
# PUBK_SEL_FUSE_KEY_0 with index 0 encodes as 0x10, a value the ROM-key arm cannot
# produce.
_PUBK_SEL_VALUE = (mm.PUBK_SEL_FUSE_KEY_0 & 0x7) << 4
_PUBK_SEL_ECHO = f"PUBK_SEL=0x{_PUBK_SEL_VALUE:08x}"  # manifest_crypto.c
# Only ROM dev key 0. Bits 16/17 (CHIPLET_PUBK_HASH0/1, sep_efuse_map.rdl:727) are
# clear -- see the docstring.
_REVOKE_BITMAP = 1 << 0
_REVOKE_ECHO = f"PUBK_REVOKE=0x{_REVOKE_BITMAP:08x}"  # manifest_crypto.c
_HASH_MISMATCH = "PUBK_HASH_MISMATCH"  # manifest_crypto.c


@pyuvm.test()
class sep_firmware_chiplet_pubkey_0_wrong_digest_test(sep_backup_manifest_fail_base):
    """CHIPLET_PUBK_HASH0 holds a decoy: the modulus binds to nothing, both refused."""

    efuse_preload = _EFUSE_DIR / "sep_efuse_lc_prod_chiplet_key0_wrong_digest.toml"

    expected_error = MANIFEST_ERR_KEY_HASH_MISMATCH
    primary_expected_error = MANIFEST_ERR_KEY_HASH_MISMATCH
    backup_defect_marker = _HASH_MISMATCH

    # KEY_REVOKED covers both the ROM-key-arm counterfactual and an accidental
    # chiplet revoke; the RSA markers prove the digest bind stopped the run before
    # the verifier; the rest are the other rejecting arms of validate_signature.
    extra_forbidden = (
        "KEY_REVOKED",
        "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY",
        "PUBK_HASH_TIMEOUT",
        "RSA_VERIFY_START",
        "RSA_VERIFY_FAIL",
        "SIG_VALID",
        "CRYPTO_VALIDATE_OK",
        "BAD_KEY_IDX",
        "BAD_KEY_SEL",
        "BAD_SIG_TYPE=",
        "VERSION_ROLLBACK",
        "LC_USAGE_CONSTRAINT_FAIL",
        ROM_ARM_KEY_REVOKED,
    )

    # --- stimulus ----------------------------------------------------------
    def corrupt_primary(self, buf: bytearray) -> None:
        # NOT the base's default BAD_MAGIC trigger: the primary is the first slot
        # under test and must reach validate_signature. One call points BOTH slots
        # at fused key 0 and re-seals each, so the two are refused for the same
        # reason and the image is byte-identical to the positive member's.
        p_sel, b_sel = select_chiplet_fuse_key(buf, _CHIPLET_KEY)
        assert p_sel == b_sel == _PUBK_SEL_VALUE, (
            f"selectors are primary=0x{p_sel:04x} backup=0x{b_sel:04x}, expected "
            f"both 0x{_PUBK_SEL_VALUE:04x}: this testcase's claim is that ONE fuse "
            f"value refuses BOTH manifests"
        )
        self.logger.info(
            "CHK-STIMULUS-FUSED-KEY: both slots public_key_sel=0x%04x "
            "(PUBK_SEL_FUSE_KEY_%d, index 0), re-signed with dev0 and re-verified "
            "sealed. Both are fully valid manifests; the only defect in this run is "
            "in the FUSE",
            p_sel,
            _CHIPLET_KEY,
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        got = mm.get_public_key_sel(buf, "backup")
        assert got == _PUBK_SEL_VALUE, (
            f"backup public_key_sel is 0x{got:04x}, expected 0x{_PUBK_SEL_VALUE:04x}"
        )
        pm.verify_sealed(buf, "backup")
        mm.verify_public_key(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-BOTH-SEALED: backup public_key_sel=0x%04x and the backup "
            "passes payload_hash, every TOC image digest, manifest_hash over the TBS "
            "and RSA verification of its re-signed signature against the dev0 "
            "modulus. Neither slot carries a defect -- the fuse does",
            got,
        )

    def check_efuse(self, image) -> None:
        """The fuse image IS the defect here, so every word of it is asserted."""
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced by the lifecycle, or key selection is never reached"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == _REVOKE_BITMAP, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:08x}, expected 0x{_REVOKE_BITMAP:08x} "
            f"-- exactly bit 0 (ROM dev key 0, the ROM-key-arm counterfactual). Bits "
            f"{PUBK_REVOKE_BIT_CHIPLET_HASH[0]} and "
            f"{PUBK_REVOKE_BIT_CHIPLET_HASH[1]} MUST be clear: revocation is tested "
            f"at manifest_crypto.c:228, before the digest bind at :236, so a revoked "
            f"chiplet key would refuse this image before the check under test ran"
        )
        want = int.from_bytes(mm.ROM_KEY0_DIGEST, "little")
        h0 = image.field_int("CHIPLET_PUBK_HASH0")
        h1 = image.field_int("CHIPLET_PUBK_HASH1")
        assert h0 != 0 and h0 != want, (
            f"CHIPLET_PUBK_HASH0 is 0x{h0:064x}; it must be NON-ZERO and NOT the "
            f"dev0 digest 0x{want:064x}. This is the fuse PUBK_SEL_FUSE_KEY_0 "
            f"selects and the whole defect of this run. Zero would make it a "
            f"FUSE_KEY_EMPTY testcase instead (read_fuse_key's non-zero test at "
            f"manifest_crypto.c:148-150, token at :233), and the real digest would "
            f"make it the positive member"
        )
        assert h1 == want, (
            f"CHIPLET_PUBK_HASH1 is 0x{h1:064x}, expected the REAL dev0 digest "
            f"0x{want:064x}. The unselected fuse holds the real digest on purpose: "
            f"it is what makes a ROM that read the WRONG chiplet fuse address boot "
            f"and so fail this testcase. Putting a second decoy here would leave "
            f"only the compiled-in-table class detectable"
        )
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364 then :369) and would end "
            f"the run before the fused-key path is reached"
        )
        self.logger.info(
            "CHK-STIMULUS-WRONG-DIGEST: CHIPLET_PUBK_REVOKE=0x%08x (bit 0 only, "
            "chiplet bits clear), SELECTED fuse CHIPLET_PUBK_HASH0=0x%064x which is "
            "NOT the dev0 digest, UNSELECTED fuse CHIPLET_PUBK_HASH1=0x%064x which "
            "IS it. So a ROM comparing against public_key_digests[0], and a ROM "
            "reading the wrong chiplet fuse, both boot -- and both fail this "
            "testcase",
            revoke,
            h0,
            h1,
        )

    # --- checks ------------------------------------------------------------
    def check_defect_attribution(self, console, i_backup: int) -> None:
        """Both slots print the marker, so the base's single-occurrence rule is wrong.

        The default requires the FIRST occurrence to follow the backup read, which
        is false here and would also accept a run in which only one slot reached
        the digest bind.
        """
        hits = [i for i, line in enumerate(console) if _HASH_MISMATCH in line]
        assert len(hits) == 2, (
            f"{_HASH_MISMATCH} appeared {len(hits)} times at {hits}, expected exactly "
            f"2 -- one per manifest slot. One occurrence would mean only one slot "
            f"reached check_pubkey_hash. Console: {console}"
        )
        assert hits[0] < i_backup < hits[1], (
            f"{_HASH_MISMATCH} occurrences {hits} do not straddle the backup read"
            f"@{i_backup}: the two rejections are not one per slot. Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-MISMATCHED: %s at lines %s, one before and one after the backup "
            "read@%d -- both manifests were refused by the chiplet digest fuse",
            _HASH_MISMATCH,
            hits,
            i_backup,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        i_backup = next((i for i, line in enumerate(console) if _BACKUP_SRC in line), -1)

        # The selector and the fuse WORD the ROM read, once per slot. Without these
        # the mismatch verdicts could belong to some other key or some other bitmap.
        # PUBK_REVOKE= is load-bearing in the positive direction here: it proves the
        # revocation check RAN and PERMITTED the key, so the rejection below is
        # attributable to the digest and not to a revoke bit.
        for marker in (_PUBK_SEL_ECHO, _REVOKE_ECHO):
            n = sum(1 for line in console if marker in line)
            assert n == 2, (
                f"{marker} appeared {n} times, expected exactly 2 (one per manifest "
                f"slot). Console: {console}"
            )

        crypto_fail = f"CRYPTO_FAIL=0x{self.expected_error:08x}"
        hits = [i for i, line in enumerate(console) if crypto_fail in line]
        assert len(hits) == 2, (
            f"{crypto_fail} appeared {len(hits)} times at {hits}, expected exactly 2 "
            f"-- one per manifest slot, because both are refused by the same fuse "
            f"value. Console: {console}"
        )
        assert 0 <= i_backup and hits[0] < i_backup < hits[1], (
            f"{crypto_fail} occurrences {hits} do not straddle the backup read"
            f"@{i_backup}: the terminal error is not attributable to both slots. "
            f"Console: {console}"
        )
        assert any("MANIFEST_ALL_FAILED" in line for line in console), (
            f"ROM never printed MANIFEST_ALL_FAILED (manifest_load.c:808): the retry "
            f"loop did not exhaust. Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-SLOTS-REFUSED: %s and %s each twice, %s at lines %s straddling "
            "the backup read@%d, then MANIFEST_ALL_FAILED -- and PUBK_REVOKE=0x%08x "
            "says the revocation check ran and PERMITTED the key, so the digest is "
            "the sole cause",
            _PUBK_SEL_ECHO,
            _REVOKE_ECHO,
            crypto_fail,
            hits,
            i_backup,
            _REVOKE_BITMAP,
        )

        # Device-side: the console says which address the ROM intended to read; the
        # BFM's record says what the device actually served, and in what order.
        rds = ev.reads(self._flash.get_transactions())
        p_hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert p_hit is not None and b_hit is not None, (
            f"device did not serve both manifest addresses: primary hit="
            f"{p_hit is not None}, backup hit={b_hit is not None}"
        )
        p_idx, _p = p_hit
        b_idx, _b = b_hit
        assert p_idx < b_idx, (
            f"device served the backup address (read[{b_idx}]) before the primary "
            f"(read[{p_idx}]): the transaction order is not a failover"
        )
        self.logger.info(
            "CHK-BOTH-FETCHED: device served read[%d] 0x%06x then read[%d] 0x%06x",
            p_idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            b_idx,
            mm.BACKUP_MANIFEST_OFFSET,
        )
