# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Parameterised family: the manifest authenticates against a chiplet FUSED key.

Four testcases -- ``sep_firmware_chiplet_pubkey_{0,1}_test`` and
``sep_firmware_chiplet_pubkey_{0,1}_revoke_test`` -- differ by two integers: which
fused key slot the manifest selects, and whether that slot's revocation bit is
blown. The stimulus, the per-member derivations and the attribution assertions live
here; each member sets ``_CHIPLET_KEY = N`` and picks a base class.

The fused-key arm is distinct code from the ROM-key arm, not the same code behind a
different selector: it has its own digest fuse address, its own revocation bit and
its own empty-slot refusal, and it hashes the manifest modulus against the FUSE
rather than against the compiled-in table in ``key_digests.c``.

Revocation bits 16 and 17, and where the authority lies. ``CHIPLET_PUBK_REVOKE``
bits [16] and [17] revoke ``CHIPLET_PUBK_HASH0`` and ``_HASH1``; the bit map is
``regs/blocks/sep_efuse_map/sep_efuse_map.rdl:727``. The ROM's own defines agree but
are deliberately not the authority here -- using the DUT's definition to justify
asserting the DUT's behaviour shares the assumption under test.

Both slots select the fused key and both are re-sealed, which is what makes the
revoke members strict: each slot is a fully valid, provably bootable manifest bound
to the fused key (``verify_sealed`` re-runs after ``reseal`` to establish that), so
one revocation bit is the SOLE cause of the rejection and the retry loop exhausts.

Two fuse-only discriminators. Between them they close the wrong-arm and
wrong-fuse-address classes:

  * ROM development key 0 is revoked in every member's preload
    (``CHIPLET_PUBK_REVOKE`` bit 0). On a correct ROM this is inert -- the manifest
    selects a fused key, so the ROM-key arm is never entered. It is a
    counterfactual: a ROM ignoring the selector would resolve slot 0 and echo
    ``PUBK_SEL=0x00000000``, which every member forbids. It is also the
    architecturally intended state for a fused-key part -- ``sep_efuse_map.rdl:727``
    says the development-key bits "shall be set (revoked)" before transfer.
  * The OTHER chiplet digest fuse holds a decoy: the same digest with one bit
    flipped. Being non-zero it passes the empty-fuse test, so a ROM addressing the
    wrong chiplet fuse fails ``PUBK_UNAUTHORIZED`` rather than booting.

What this family can NOT see. This tree ships one usable RSA-3072 private key, so
fused digest and ROM slot 0's compiled-in digest are byte-identical. A ROM that took
the fused arm, tested the right revocation bit, read the right fuse address and then
compared the modulus against ``public_key_digests[0]`` would behave identically in
all four members. Closing that needs a second signing key in the tree.

Entropy: the two positive members verify a manifest, so a real RSA-3072 modexp runs
on OTBN and they need ``+esrc_noise_force``. The revoke members must not reach the
verifier -- revocation precedes it -- and they forbid ``RSA_EXEC`` to say so.
"""

from __future__ import annotations

from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_KEY_REVOKED,
    sep_backup_manifest_fail_base,
)
from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)

_EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"

_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# Named here for the derivation below; the AUTHORITY for
# the values is sep_efuse_map.rdl:727, and the family asserts the fuse bitmap it
# was given rather than trusting either.
PUBK_REVOKE_BIT_CHIPLET_HASH = (16, 17)

# What a ROM that resolved the selector to ROM slot 0 instead of the fused
# chiplet slot would echo. Every member forbids it; see the module docstring.
ROM_ARM_KEY_REVOKED = "PUBK_SEL=0x00000000"


def select_chiplet_fuse_key(buf: bytearray, key_index: int) -> tuple[int, int]:
    """Point BOTH slots' ``public_key_sel`` at CHIPLET fused key ``key_index``, re-sealed.

    ``public_key_select`` is a 128-bit slot bitmap inside the signed region, so
    the write invalidates ``manifest_hash`` and the shipped signature. Unlike the ROM-slot families of R1/R2 this family must leave a
    manifest that would BOOT -- a revocation test whose image was independently
    unbootable would prove nothing about revocation -- so each slot is re-sealed
    (``env/sep_payload_mutate.reseal``: payload_hash -> manifest_hash -> signature)
    and then re-checked with ``verify_sealed``.

    ``verify_signing_key`` runs FIRST, on the untouched slot, so the local signer is
    proven to reproduce the packer's own signature byte for byte before it is trusted
    to produce a new one. Returns ``(primary_selector, backup_selector)``.
    """
    selection = (mm.PUBK_SEL_FUSE_KEY_0, mm.PUBK_SEL_FUSE_KEY_1)[key_index]
    got: list[int] = []
    for slot in ("primary", "backup"):
        # Anchor: the shipped slot is fully sealed and its modulus is the dev0 key
        # whose SHA-256 the preload programs into the chiplet fuse. Both facts are
        # preconditions for everything below.
        pm.verify_sealed(buf, slot)
        mm.verify_public_key(buf, slot)
        pm.verify_signing_key(buf, slot)

        mm.set_public_key_sel(buf, slot, selection=selection, index=0)
        # Ask the mutator which slot that pair names rather than repacking the
        # field here. ``public_key_select`` is a BITMAP under OCA -- one bit per
        # key slot -- and :func:`mm.get_public_key_sel` returns the slot NUMBER,
        # not a packed field. The two agree for CHIPLET_PUBK_HASH0 (slot 16 ==
        # the old ``selection << 4``), which is why only the HASH1 members caught
        # the hand-rolled expectation: slot 17 asserted against 0x20.
        expected = mm.key_slot_for(selection, 0)
        sel = mm.get_public_key_sel(buf, slot)
        assert sel == expected, (
            f"{slot} public_key_sel names slot {sel} (0x{sel:04x}), expected slot "
            f"{expected} (0x{expected:04x}) "
            f"(selection=PUBK_SEL_FUSE_KEY_{key_index}, index=0)"
        )
        pm.reseal(buf, slot)
        # The re-seal must be complete. A slot still carrying a stale payload hash,
        # manifest hash or signature would be rejected for THAT, and the run would
        # show a terminal error that has nothing to do with the fused key.
        pm.verify_sealed(buf, slot)
        got.append(sel)
    return got[0], got[1]


class _chiplet_key_mixin:
    """Per-member derivations shared by both outcome shapes of the family.

    Members set ``_CHIPLET_KEY`` (and, on the revoking base, inherit ``_REVOKED``).
    Everything else is derived in :meth:`__init_subclass__`, so the per-member values
    are real class attributes -- greppable, and visible in the run log -- rather than
    hidden inside a method.
    """

    # Set by every concrete member. -1 makes an unset subclass fail immediately
    # instead of silently testing key 0.
    _CHIPLET_KEY: int = -1
    # Set by the concrete base, not by the member.
    _REVOKED: bool = False

    # Derived; see __init_subclass__.
    _PUBK_SEL_VALUE: int = 0
    _PUBK_SEL_ECHO: str = ""
    _REVOKE_BITMAP: int = 0
    _REVOKE_ECHO: str = ""
    _REVOKE_BIT: int = 0
    _KEY_REVOKED_ECHO: str = ""
    _PUBK_SEL_ECHO: str = ""

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        key = cls._CHIPLET_KEY
        if key < 0:
            # An intermediate base that has not chosen a key yet is allowed; the
            # run-time asserts below catch it if it is ever executed.
            return
        assert key in (0, 1), (
            f"{cls.__name__}: _CHIPLET_KEY {key} is not a CHIPLET fused key. Only "
            f"PUBK_SEL_FUSE_KEY_0 and _1 are covered here; PUBK_SEL_FUSE_SOP_KEY (4) "
            f"and PUBK_SEL_FUSE_SYS_KEY (5) are two more arms of the same switch "
            f" with revoke bits 20 and 22, and have no "
            f"testcase yet"
        )
        selection = (mm.PUBK_SEL_FUSE_KEY_0, mm.PUBK_SEL_FUSE_KEY_1)[key]
        # The SLOT number, because that is what the ROM echoes:
        # ``simputshex32("PUBK_SEL=", (uint32_t)slot)`` (``oca_platform.c``), not
        # the bitmap word and not a packed selection nibble.
        cls._PUBK_SEL_VALUE = mm.key_slot_for(selection, 0)
        cls._PUBK_SEL_ECHO = f"PUBK_SEL=0x{cls._PUBK_SEL_VALUE:08x}"
        cls._REVOKE_BIT = PUBK_REVOKE_BIT_CHIPLET_HASH[key]
        # Bit 0 -- ROM development key 0 -- is blown in EVERY member of this family
        # as the ROM-key-arm counterfactual. See the module docstring.
        cls._REVOKE_BITMAP = 1 << 0
        if cls._REVOKED:
            cls._REVOKE_BITMAP |= 1 << cls._REVOKE_BIT
        #  -- the whole 32-bit fuse WORD, echoed before the bit
        # test, so both slot attempts print the same value.
        cls._REVOKE_ECHO = f"PUBK_REVOKE=0x{cls._REVOKE_BITMAP:08x}"
        # Revocation is the library's verdict, so the reason it refused is the
        # result code. Which slot that applied to is _PUBK_SEL_ECHO's job.
        cls._KEY_REVOKED_ECHO = f"MANIFEST_ERR=0x{MANIFEST_ERR_KEY_REVOKED:08x}"
        cls._PUBK_SEL_ECHO = f"PUBK_SEL=0x{cls._REVOKE_BIT:08x}"
        suffix = "_revoke" if cls._REVOKED else ""
        cls.efuse_preload = _EFUSE_DIR / f"sep_efuse_lc_prod_chiplet_key{key}{suffix}.toml"

    # --- stimulus ----------------------------------------------------------
    def _plant_fused_selector(self, buf: bytearray) -> None:
        p_sel, b_sel = select_chiplet_fuse_key(buf, self._CHIPLET_KEY)
        assert p_sel == b_sel == self._PUBK_SEL_VALUE, (
            f"selectors are primary=0x{p_sel:04x} backup=0x{b_sel:04x}, expected both "
            f"0x{self._PUBK_SEL_VALUE:04x}: this family's outcome shape depends on BOTH "
            f"slots selecting the same fused key"
        )
        self.logger.info(
            "CHK-STIMULUS-FUSED-KEY PASS: both slots public_key_sel=0x%04x "
            "(PUBK_SEL_FUSE_KEY_%d, index 0), re-signed with dev0 and re-verified "
            "sealed; the digest the ROM will compare against is CHIPLET_PUBK_HASH%d",
            p_sel,
            self._CHIPLET_KEY,
            self._CHIPLET_KEY,
        )
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        self.logger.info("CHK-STIMULUS-BACKUP: %s", mm.describe(buf, "backup"))

    def _assert_chiplet_efuse(self, image) -> None:
        """The fuse image is the other half of this family's stimulus, so assert it.

        Three independent things, each of which would silently change what the run
        proves: the revoke bitmap must be EXACTLY this member's bits, the selected
        chiplet digest must be the dev0 digest the manifest's modulus hashes to, and
        the OTHER chiplet digest must be a non-zero decoy that is NOT that digest.
        """
        key = self._CHIPLET_KEY
        other = 1 - key
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == self._REVOKE_BITMAP, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:08x}, expected "
            f"0x{self._REVOKE_BITMAP:08x}: exactly bit 0 (ROM dev key 0, the "
            f"ROM-key-arm counterfactual)"
            + (f" and bit {self._REVOKE_BIT} (CHIPLET_PUBK_HASH{key})" if self._REVOKED else "")
            + ". A wider bitmap could refuse a key this testcase did not select"
        )
        mine = image.field_int(f"CHIPLET_PUBK_HASH{key}")
        theirs = image.field_int(f"CHIPLET_PUBK_HASH{other}")
        # The fuse holds the digest little-endian by 32-bit word, because
        # the fuse-digest read() rebuilds the byte array from
        # eight mmio_read32() results, byte 0 first.
        want = int.from_bytes(mm.rom_key_digest(0), "little")
        assert mine == want, (
            f"CHIPLET_PUBK_HASH{key} is 0x{mine:064x}, expected 0x{want:064x} -- the "
            f"little-endian SHA-256 of the dev0 modulus (key_digests.c:18-21). The "
            f"manifest is signed with dev0 and carries its modulus, so any other "
            f"value makes this a PUBK_UNAUTHORIZED testcase instead"
        )
        assert theirs != 0 and theirs != want, (
            f"CHIPLET_PUBK_HASH{other} is 0x{theirs:064x}; it must be a NON-ZERO "
            f"digest that is not the dev0 one. Zero would make a wrong-fuse read "
            f"fail as PUBK_OTP_EMPTY instead of PUBK_UNAUTHORIZED, and the dev0 "
            f"value would let a ROM reading the wrong chiplet fuse boot anyway"
        )
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
        )
        self.logger.info(
            "CHK-STIMULUS-CHIPLET-EFUSE: CHIPLET_PUBK_REVOKE=0x%08x (bit 0 ROM dev "
            "key 0%s), CHIPLET_PUBK_HASH%d=dev0 digest, CHIPLET_PUBK_HASH%d=decoy "
            "(non-zero, != dev0), BL1_VERSION=0",
            revoke,
            f" + bit {self._REVOKE_BIT}" if self._REVOKED else "",
            key,
            other,
        )


class sep_chiplet_pubkey_valid_base(_chiplet_key_mixin, sep_rom_ot_dma_boot_test):
    """The fused key is programmed and NOT revoked: the PRIMARY verifies and boots.

    "It booted" is not the result. Boot completion is also what a ROM that skipped
    key selection, or took the ROM-key arm, or read the wrong chiplet fuse would
    produce, so four independent channels are required and none of them is the
    banner:

      * ``PUBK_SEL=0x000000{10,20}`` exactly once -- the selector the ROM read out of
        the primary. The VALUE is what excludes the
        ROM-key arm on the stimulus side: slot 16 is CHIPLET_PUBK_HASH0, outside
        the [0, 8) range the ROM classical arm serves;
      * ``PUBK_REVOKE=0x00000001`` exactly once -- the fuse word
        the revocation check read, proving the
        revocation check ran and PERMITTED this key. Note this marker does NOT by
        itself prove which arm ran: the revocation check is called from the
        ROM-key arm too. What excludes that arm is ``KEY_REVOKED`` being
        forbidden outright -- ``CHIPLET_PUBK_REVOKE`` bit 0 IS blown in this
        member's preload, so a ROM taking the ROM-key arm with index 0 would have
        printed the revocation error code and refused the image;
      * ``RSA_EXEC`` then ``RSA_VERIFY_OK`` then ``MANIFEST_OK``, in that
        order and after the selector echo: the modulus reached the verifier, which
        happens only once the revocation check and the FUSE digest bind have both
        passed ( then);
      * the DEVICE side: not one read inside the backup slot's span. A silent
        failover also reaches ``MANIFEST_OK``, and only the BFM's transaction record
        can say the PRIMARY served this boot.
    """

    flash_image = SECURE_FLASH_IMAGE
    _REVOKED = False

    efuse_preload: Path | None = None

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls._CHIPLET_KEY < 0:
            return
        cls.required_markers = sep_rom_ot_dma_boot_test.required_markers + (
            "LC=PROD",
            _PRIMARY_SRC,
            cls._PUBK_SEL_ECHO,
            cls._REVOKE_ECHO,
            "RSA_EXEC",
            "RSA_VERIFY_OK",
            "BL1_COPIED",
            "BL1_JUMP=",
        )
        # Every rejecting arm of the signature path, both arms' empty-slot checks,
        # the ROM-key-arm counterfactual, and the failover evidence. This is a
        # positive test, so none of them may fire.
        cls.forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
            "SBOOT_OFF",
            "FUSE: SBOOT_DIS: 1",
            _BACKUP_SRC,
            "MANIFEST_ERR=",
            "MANIFEST_ALL_FAILED",
            "PUBK_ALGO_UNSUPPORTED",
            "PUBK_SLOT_RESERVED",
            "PUBK_SEL_AMBIGUOUS",
            "PUBK_SLOT_UNPROVISIONED",
            "PUBK_OTP_EMPTY",
            "PUBK_UNAUTHORIZED",
            "PUBK_HASH_TIMEOUT",
            "RSA_PKCS1_FAIL",
            "MANIFEST_ERR=",
        )

    # --- stimulus ----------------------------------------------------------
    def build_efuse_image(self):
        assert self.efuse_preload and self.efuse_preload.is_file(), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced by the lifecycle, or the key selection under test is never "
            f"reached on the production path"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        self._assert_chiplet_efuse(image)
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        self._plant_fused_selector(buf)
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
        i_sel = index_of(self._PUBK_SEL_ECHO)
        i_revoke = index_of(self._REVOKE_ECHO)
        i_rsa = index_of("RSA_EXEC")
        i_sig = index_of("RSA_VERIFY_OK")
        i_ok = index_of("MANIFEST_OK")

        # CHK-FUSEKEY-RAN: the fused-key path executed on the PRIMARY in the
        # architected order -- slot read, selector read, revocation bitmap consulted
        # and permitted, verifier driven, signature valid. Presence alone says
        # nothing about order, and order is the substance.
        assert 0 <= i_psrc < i_sel < i_revoke < i_rsa < i_sig < i_ok, (
            f"the fused-key path did not run on the primary in the architected "
            f"order: primary@{i_psrc} -> {self._PUBK_SEL_ECHO}@{i_sel} -> "
            f"{self._REVOKE_ECHO}@{i_revoke} -> RSA_EXEC@{i_rsa} -> "
            f"RSA_VERIFY_OK@{i_sig} -> MANIFEST_OK@{i_ok}. Console: {console}"
        )
        # Exactly once each. The backup is never read in this scenario, so a second
        # occurrence would mean a slot this testcase did not select also reached key
        # selection or the verifier.
        for marker in (self._PUBK_SEL_ECHO, self._REVOKE_ECHO, "RSA_EXEC", "RSA_VERIFY_OK"):
            n = sum(1 for line in console if marker in line)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the primary's). "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-FUSEKEY-RAN PASS: primary@%d -> %s@%d -> %s@%d -> RSA_EXEC@%d -> "
            "RSA_VERIFY_OK@%d -> MANIFEST_OK@%d, each exactly once; the ROM read "
            "CHIPLET fused key %d, found it unrevoked, and the manifest modulus bound "
            "to that fuse's digest",
            i_psrc,
            self._PUBK_SEL_ECHO,
            i_sel,
            self._REVOKE_ECHO,
            i_revoke,
            i_rsa,
            i_sig,
            i_ok,
            self._CHIPLET_KEY,
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
        # CHK-NO-FAILOVER: the channel the ROM cannot fake. Without it a run whose
        # primary was refused and whose backup booted would satisfy every marker
        # above except the forbidden backup source -- and that forbid is a console
        # claim, while this is the device's own record.
        backup_hits = ev.slot_read_indices(rds, "backup", self._image_len)
        assert not backup_hits, (
            f"device served {len(backup_hits)} read(s) inside the backup slot span "
            f"(read indices {backup_hits}): the primary alone did not serve this "
            f"boot, so this is a failover result and not a fused-key result"
        )
        self.logger.info(
            "CHK-NO-FAILOVER: read[%d] at 0x%06x returned magic %r, and no read "
            "touched the backup span across %d reads -- the PRIMARY served this boot",
            idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            magic,
            len(rds),
        )


class sep_chiplet_pubkey_revoked_base(_chiplet_key_mixin, sep_backup_manifest_fail_base):
    """The fused key's revocation bit is blown: BOTH slots are refused, terminally.

    Both manifests select the same fused key and both are re-sealed and provably
    bootable, so one fuse bit refuses two valid images and the retry loop exhausts
    (``MANIFEST_ALL_FAILED``, ). That is the strict form of
    the revocation property, and it is available here for BOTH members -- unlike the
    ROM-slot families, where only slot 0 could be strict.
    """

    _REVOKED = True

    expected_error = MANIFEST_ERR_KEY_REVOKED
    primary_expected_error = MANIFEST_ERR_KEY_REVOKED
    # Every other rejecting arm of the signature path, both empty-slot checks, and
    # proof the modulus never reached the verifier. RSA_EXEC and RSA_VERIFY_OK
    # are the load-bearing forbids: both manifests are otherwise valid, so without
    # them a revocation that did nothing would boot. ROM_ARM_KEY_REVOKED is the
    # ROM-key-arm counterfactual described in the module docstring.
    extra_forbidden = (
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_OTP_EMPTY",
        "PUBK_UNAUTHORIZED",
        "PUBK_HASH_TIMEOUT",
        "RSA_EXEC",
        "RSA_PKCS1_FAIL",
        "RSA_VERIFY_OK",
        "PUBK_SLOT_RESERVED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_ALGO_UNSUPPORTED",
        ROM_ARM_KEY_REVOKED,
    )

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls._CHIPLET_KEY >= 0:
            cls.backup_defect_marker = cls._KEY_REVOKED_ECHO

    # --- stimulus ----------------------------------------------------------
    def corrupt_primary(self, buf: bytearray) -> None:
        # NOT the base's default BAD_MAGIC trigger. The primary is the first slot
        # under test here and must reach the signature path, exactly as the
        # reference sets the selection on both slots rather than breaking one
        # (sep_firmware_pub_key_test.py). One call does both slots.
        self._plant_fused_selector(buf)

    def corrupt_backup(self, buf: bytearray) -> None:
        # The backup carries no separate defect: corrupt_primary() already pointed
        # it at the same revoked fused key and re-sealed it. Assert that, so the
        # terminal verdict cannot be blamed on a damaged backup.
        got = mm.get_public_key_sel(buf, "backup")
        assert got == self._PUBK_SEL_VALUE, (
            f"backup public_key_sel is 0x{got:04x}, expected "
            f"0x{self._PUBK_SEL_VALUE:04x}: this member's claim is that ONE fuse bit "
            f"refuses BOTH manifests, which requires the backup to select the revoked "
            f"key too"
        )
        pm.verify_sealed(buf, "backup")
        mm.verify_public_key(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-BOTH-SEALED: backup public_key_sel=0x%04x, and the backup "
            "passes payload_hash, every TOC image digest, manifest_hash over the signed region "
            "and RSA verification of its RE-SIGNED signature against the dev0 "
            "modulus, whose SHA-256 is the CHIPLET_PUBK_HASH%d fuse value. Both "
            "manifests are genuinely bootable and one fuse bit refuses both",
            got,
            self._CHIPLET_KEY,
        )

    def check_efuse(self, image) -> None:
        self._assert_chiplet_efuse(image)

    # --- checks ------------------------------------------------------------
    def check_defect_attribution(self, console, i_backup: int) -> None:
        """Both slots print the marker, so the base's default is not applicable.

        The default requires the FIRST occurrence to follow the backup read, which
        is false here and would also accept a run that never evaluated the backup.
        Instead: exactly two occurrences, one on each side of the backup read.
        """
        hits = [i for i, line in enumerate(console) if self.backup_defect_marker in line]
        assert len(hits) == 2, (
            f"{self.backup_defect_marker} appeared {len(hits)} times at {hits}, "
            f"expected exactly 2 -- one per manifest slot. One occurrence would mean "
            f"only one slot reached key selection. Console: {console}"
        )
        assert hits[0] < i_backup < hits[1], (
            f"{self.backup_defect_marker} occurrences {hits} do not straddle the "
            f"backup read@{i_backup}: the two rejections are not one per slot. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-REVOKED: %s at lines %s, one before and one after the backup "
            "read@%d -- both manifests were refused by CHIPLET_PUBK_REVOKE bit %d",
            self.backup_defect_marker,
            hits,
            i_backup,
            self._REVOKE_BIT,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        # The selector and the fuse word the ROM actually read, once per slot.
        # Without these the KEY_REVOKED verdicts could belong to some other key or
        # some other bitmap.
        for marker in (self._PUBK_SEL_ECHO, self._REVOKE_ECHO):
            n = sum(1 for line in console if marker in line)
            assert n == 2, (
                f"{marker} appeared {n} times, expected exactly 2 (one per manifest "
                f"slot): the revocation verdicts cannot be attributed to CHIPLET "
                f"fused key {self._CHIPLET_KEY} under a 0x{self._REVOKE_BITMAP:08x} "
                f"bitmap. Console: {console}"
            )

        # The terminal error code, once per slot. The shared base checks only that
        # MANIFEST_ERR= is PRESENT, and its index_of() returns the FIRST occurrence,
        # which here is the primary's -- so without this the run's convergence on
        # KEY_REVOKED would rest on the primary alone and the backup's own crypto
        # verdict would be unasserted.
        crypto_fail = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_backup = next((i for i, line in enumerate(console) if _BACKUP_SRC in line), -1)
        hits = [i for i, line in enumerate(console) if crypto_fail in line]
        assert len(hits) == 2, (
            f"{crypto_fail} appeared {len(hits)} times at {hits}, expected exactly 2 "
            f"-- one per manifest slot, because both are refused by the same fuse "
            f"bit. Console: {console}"
        )
        assert 0 <= i_backup and hits[0] < i_backup < hits[1], (
            f"{crypto_fail} occurrences {hits} do not straddle the backup read"
            f"@{i_backup}: the terminal error is not attributable to both slots. "
            f"Console: {console}"
        )

        # CHK-ALL-SLOTS-EXHAUSTED: the retry loop ran out of slots, which is the
        # observable distinguishing "both were refused" from "the ROM stopped after
        # the first". , reached only after the loop.
        assert any("MANIFEST_ALL_FAILED" in line for line in console), (
            f"ROM never printed MANIFEST_ALL_FAILED: the retry "
            f"loop did not exhaust, so the run is not the both-slots-refused outcome "
            f"this member claims. Console: {console}"
        )
        self.logger.info(
            "CHK-BOTH-SLOTS-REFUSED: %s and %s each twice, %s at lines %s straddling "
            "the backup read@%d, then MANIFEST_ALL_FAILED",
            self._PUBK_SEL_ECHO,
            self._REVOKE_ECHO,
            crypto_fail,
            hits,
            i_backup,
        )

        # Device-side evidence: the console says which address the ROM INTENDED to
        # read; the BFM's record says which address the device actually served, and
        # in what order. The base publishes the flash handle for exactly this.
        rds = ev.reads(self._flash.get_transactions())
        p_hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert p_hit is not None and b_hit is not None, (
            f"device did not serve both manifest addresses: primary "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:x} hit={p_hit is not None}, backup "
            f"0x{mm.BACKUP_MANIFEST_OFFSET:x} hit={b_hit is not None}. Both slots "
            f"must be fetched for 'both were refused' to mean anything"
        )
        p_idx, _p = p_hit
        b_idx, _b = b_hit
        assert p_idx < b_idx, (
            f"device served the backup address (read[{b_idx}]) before the primary "
            f"(read[{p_idx}]): the transaction order is not a failover"
        )
        self.logger.info(
            "CHK-BOTH-FETCHED: device served read[%d] 0x%06x then read[%d] 0x%06x; "
            "both slots were really fetched and both were refused",
            p_idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            b_idx,
            mm.BACKUP_MANIFEST_OFFSET,
        )
