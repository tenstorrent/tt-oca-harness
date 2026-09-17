# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Parameterised family: the manifest authenticates against a CHIPLET FUSED key.

Four testcases -- ``sep_firmware_chiplet_pubkey_{0,1}_test`` and
``sep_firmware_chiplet_pubkey_{0,1}_revoke_test`` -- differ from one another by two
integers: which fused key slot the manifest selects, and whether that slot's
revocation bit is blown. The stimulus, the per-member derivations and the
attribution assertions live here once; each member is a module whose only
substantive lines are ``_CHIPLET_KEY = N`` and the base class it picks.

**THE FUSED-KEY PATH IS GENUINELY DISTINCT CODE, NOT THE ROM-KEY PATH REACHED BY A
DIFFERENT SELECTOR.** ``validate_signature`` branches on
``m->public_key_sel.selection`` at ``manifest_crypto.c``. The fused arm has its
own ``switch`` choosing BOTH the digest fuse address AND a different
revocation bit, its own ``read_fuse_key`` / ``FUSE_KEY_EMPTY``, and
it hashes the manifest modulus against the FUSE rather than against the compiled-in
table. It is also the only arm that does NOT report
``SEP_MSG_VALIDATE_CHECK`` before the revocation check (that call is inside the
ROM-key arm). So these four testcases are coverage distinct from the
``pubkey_rom_*_revoked`` families.

**THE REVOCATION BITS ARE 16 AND 17, AND THE AUTHORITY IS THE REGISTER MAP.**
``regs/blocks/sep_efuse_map/sep_efuse_map.rdl:727`` gives the bit map of
``CHIPLET_PUBK_REVOKE``: "[7:0] ROM chiplet-creator classical keys ... [16]/[17]
CHIPLET_PUBK_HASH0/1". The ROM's own ``#define``\\ s agree
(``manifest_crypto.c``) but are NOT cited as the authority -- using the DUT's
definition to justify asserting the DUT's behaviour is the same error as an
instrument that shares the assumption under test. **The reference uses bits 6 and 7**
(encoded as ``32'h40`` and ``32'h80``), which in THIS map are unused ROM-slot bits and
would revoke nothing at all. Those numbers must not be copied. **This is a
register-map difference, NOT a defect in the reference:** 6 and 7 are the reference
ROM's own contract -- it defines ``PUBK_FUSE_KEY_0_REVOCATION_INDEX 6`` and
``..._1_... 7`` and consumes them in its own manifest check -- so the reference test
matched its own ROM exactly.

**WHAT THE REFERENCE ASSERTS, WHICH IS LESS THAN IT LOOKS, AND IT IS WHY THIS PORT IS
STRICTER.** Its cocotb test awaits ``sep_binary_preloader(dut, cold_scratch_check=False)``,
and with that flag ``monitor_test`` returns True even on a ROM ``TEST_FAIL``. So
the two POSITIVE reference members assert **nothing** about boot success -- their
``[PASS] SEP BOOT SUCCESS`` line (``sep_firmware_pub_key_test.py``) is an
unconditional ``log.info`` that prints on a failed boot too -- and the two REVOKE
members' entire result is one substring search for ``REVOKED_KEY``. The terminal
strictness this port demands is therefore a documented
STRENGTHENING over the reference's gate, not an unexplained divergence.

WHAT THE REFERENCE DOES, AND THE ONE THING THIS PORT DOES NOT REPRODUCE. The
reference generates a fresh RSA-3072 keypair per run
(``generate_rsa3072_key.sh``), programs SHA-256 of ITS
modulus into ``PUBLIC_KEY_0``/``_1``
(``sep_firmware_pubkey_test.sv`` reads the digest and places it) and signs BOTH
manifest slots with that key
(``sep_firmware_pub_key_test.py``). Its
fused digest therefore DIFFERS from its ROM slot-0 digest, and a ROM that ignored
``selection`` would fail. This tree ships exactly one usable RSA-3072 private key,
``rsa_private_key.dev0.pem``
(``bootrom/prod/tools/tt-boot-manifest/tests/signing_keys/``, whose other file
``ec_private_key.pem`` the ROM cannot use because it implements RSA-3072 only), so
the fused digest here MUST equal ROM slot 0's compiled-in digest
(``key_digests.c``) or the image could not verify at all. That collapse is
this family's narrowing.

**THE CLOSURE A SECOND KEY WOULD GIVE.** Signing the chiplet image with a SECOND
RSA-3072 key and programming ITS digest into the chiplet fuse, leaving
``key_digests.c`` slot 0 at dev0, would make a ROM taking the wrong arm fail on
``PUBK_HASH_MISMATCH`` instead of booting; ``env/sep_payload_mutate.py`` has the PEM
reader (``load_rsa_private_key``) and the PKCS#1 v1.5 signer for it. Committing that
key changes the tree's key inventory rather than a testcase, so this family uses the
two fuse-only discriminators below instead.

**TWO FUSE-ONLY DISCRIMINATORS, AND WHAT THEY DO AND DO NOT COVER.** Between them
they close the WRONG-ARM class and the WRONG-FUSE-ADDRESS class completely, and
neither needs a second key. **They do NOT close the DIGEST-SOURCE question:** a ROM
that took the fused arm, tested the right revocation bit, read the right fuse address
and then compared the modulus against ``public_key_digests[0]`` instead of the fuse it
had just read would boot in both positive members and be refused in both revoke
members, exactly as expected, and nothing in this family could see it -- because the
two digests are byte-identical. ``sep_firmware_chiplet_pubkey_0_wrong_digest_test``
closes that class with a decoy in the SELECTED fuse and no second key.

  * **ROM development key 0 is REVOKED in every member's preload**
    (``CHIPLET_PUBK_REVOKE`` bit 0). On the correct ROM this is inert: the manifest
    selects a fused key, the ROM-key arm is never entered, and bit 0 is never
    tested. It is a counterfactual. A ROM that ignored ``selection`` and took the
    ROM-key arm with index 0 would reach ``check_pubkey_revoked(0)``
    (``manifest_crypto.c``) and print ``KEY_REVOKED idx=0x00000000``, which every
    member of this family forbids. That is also the architecturally intended
    configuration for a fused-key part: ``sep_efuse_map.rdl:727`` says the
    development-key bits "shall be set (revoked)" before a part is transferred.
  * **The OTHER chiplet digest fuse holds a DECOY** -- the same digest with one bit
    flipped. It is non-zero, so a ROM that addressed the wrong chiplet fuse would
    pass ``read_fuse_key``'s non-zero test (``manifest_crypto.c``) and fail
    ``check_pubkey_hash`` with ``PUBK_HASH_MISMATCH`` instead of booting. This is a
    live regression guard: ``manifest_crypto.c`` records that this ROM once
    derived the digest addresses as ``CHIPLET_PUBK_REVOKE + 0x100/0x120`` and read
    the wrong fuse words.

BOTH SLOTS SELECT THE FUSED KEY, AND BOTH ARE RE-SEALED, WHICH IS WHY THE REVOKE
MEMBERS ARE TERMINAL AND STRICT. The reference sets the selection on primary AND
backup (``sep_firmware_pub_key_test.py``), so one revocation bit refuses
both manifests and the retry loop exhausts. This port does the same and then
re-signs both slots with dev0 (``env/sep_payload_mutate.reseal``), so each slot is a
fully valid, provably bootable manifest bound to the fused key -- ``verify_sealed``
is re-run after the re-seal to prove it. Revocation is therefore the SOLE cause of
the rejection, which is the strict form of the property. Note this is stronger than
the ROM-slot revoke families, where only slot 0 is strict: there, slots 1-5 have no
populated digest and their stale dev0 signature is never re-signed, so they prove
only that revocation preempts the empty-digest arm. Here every member is the strict
case.

PLATFORM ADAPTATION -- MARKERS. The reference asserts the fused-key path positively
with ``STATUS: USING_FUSE_KEY_0`` / ``USING_FUSE_KEY_1``
(the reference ROM's ``manifest.c``) and the revoke case with
``WARNING:``/``ERROR: REVOKED_KEY``. This ROM has NO ``SEP_MSG_USING_FUSE_KEY*``
code at all -- ``grep -rn 'USING_FUSE_KEY' bootrom/prod/include/`` is empty -- and
``SEP_MSG_REVOKED_KEY`` (``bootrom/prod/include/status_values.h:13``, 0x0c) is
defined and never emitted. The substitutions are the console echoes
``PUBK_SEL=0x000000{10,20}`` (``manifest_crypto.c``), which carry the selection
in a form the ROM-key arm cannot produce, and ``KEY_REVOKED idx=0x0000001{0,1}``,
whose index value is reachable only from the fused arm because the ROM-key arm's
index is bounded below 6.

``+sep_crypto_edn_force`` is needed by the two POSITIVE members only: their
manifest verifies, so a real RSA-3072 modexp runs on OTBN. The revoke members must
NOT have it -- revocation precedes ``rsa_3072_verify`` (``manifest_crypto.c``),
no slot reaches the verifier, and both members forbid
``RSA_VERIFY_START`` to say so.
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

# manifest_crypto.c. Named here for the derivation below; the AUTHORITY for
# the values is sep_efuse_map.rdl:727, and the family asserts the fuse bitmap it
# was given rather than trusting either.
PUBK_REVOKE_BIT_CHIPLET_HASH = (16, 17)

# What a ROM that fell through to the ROM-key arm with index 0 would print. Every
# member forbids it; see the module docstring.
ROM_ARM_KEY_REVOKED = "KEY_REVOKED idx=0x00000000"


def select_chiplet_fuse_key(buf: bytearray, key_index: int) -> tuple[int, int]:
    """Point BOTH slots' ``public_key_sel`` at CHIPLET fused key ``key_index``, re-sealed.

    ``public_key_sel`` is ``{index:4, selection:3}`` (``manifest.h``) and lives
    inside the TBS, so the write invalidates ``manifest_hash`` and the shipped dev0
    signature. Unlike the ROM-slot families this family must leave a
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
        expected = (selection & 0x7) << 4
        sel = mm.get_public_key_sel(buf, slot)
        assert sel == expected, (
            f"{slot} public_key_sel encoded as 0x{sel:04x}, expected 0x{expected:04x} "
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
            f"(manifest_crypto.c:214-221) with revoke bits 20 and 22, and have no testcase"
        )
        selection = (mm.PUBK_SEL_FUSE_KEY_0, mm.PUBK_SEL_FUSE_KEY_1)[key]
        cls._PUBK_SEL_VALUE = (selection & 0x7) << 4
        # manifest_crypto.c -- simputshex32("PUBK_SEL=", public_key_sel.value).
        cls._PUBK_SEL_ECHO = f"PUBK_SEL=0x{cls._PUBK_SEL_VALUE:08x}"
        cls._REVOKE_BIT = PUBK_REVOKE_BIT_CHIPLET_HASH[key]
        # Bit 0 -- ROM development key 0 -- is blown in EVERY member of this family
        # as the ROM-key-arm counterfactual. See the module docstring.
        cls._REVOKE_BITMAP = 1 << 0
        if cls._REVOKED:
            cls._REVOKE_BITMAP |= 1 << cls._REVOKE_BIT
        # manifest_crypto.c -- the whole 32-bit fuse WORD, echoed before the bit
        # test, so both slot attempts print the same value.
        cls._REVOKE_ECHO = f"PUBK_REVOKE=0x{cls._REVOKE_BITMAP:08x}"
        # manifest_crypto.c -- simputshex32("KEY_REVOKED idx=", revocation_index).
        cls._KEY_REVOKED_ECHO = f"KEY_REVOKED idx=0x{cls._REVOKE_BIT:08x}"
        suffix = "_revoke" if cls._REVOKED else ""
        cls.efuse_preload = _EFUSE_DIR / f"sep_efuse_lc_prod_chiplet_key{key}{suffix}.toml"

    # --- stimulus ----------------------------------------------------------
    def _plant_fused_selector(self, buf: bytearray) -> None:
        p_sel, b_sel = select_chiplet_fuse_key(buf, self._CHIPLET_KEY)
        assert p_sel == b_sel == self._PUBK_SEL_VALUE, (
            f"selectors are primary=0x{p_sel:04x} backup=0x{b_sel:04x}, expected both "
            f"0x{self._PUBK_SEL_VALUE:04x}: this family's outcome shape depends on BOTH "
            f"slots selecting the same fused key, exactly as the reference does"
        )
        self.logger.info(
            "CHK-STIMULUS-FUSED-KEY: both slots public_key_sel=0x%04x "
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
        # read_fuse_key() (manifest_crypto.c) rebuilds the byte array from
        # eight mmio_read32() results, byte 0 first.
        want = int.from_bytes(mm.ROM_KEY0_DIGEST, "little")
        assert mine == want, (
            f"CHIPLET_PUBK_HASH{key} is 0x{mine:064x}, expected 0x{want:064x} -- the "
            f"little-endian SHA-256 of the dev0 modulus (key_digests.c:18-21). The "
            f"manifest is signed with dev0 and carries its modulus, so any other "
            f"value makes this a PUBK_HASH_MISMATCH testcase instead"
        )
        assert theirs != 0 and theirs != want, (
            f"CHIPLET_PUBK_HASH{other} is 0x{theirs:064x}; it must be a NON-ZERO "
            f"digest that is not the dev0 one. Zero would make a wrong-fuse read "
            f"fail as FUSE_KEY_EMPTY instead of PUBK_HASH_MISMATCH, and the dev0 "
            f"value would let a ROM reading the wrong chiplet fuse boot anyway"
        )
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364 then :369) and would end "
            f"the run before the fused-key path is reached"
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
        the primary (``manifest_crypto.c``). The VALUE is what excludes the
        ROM-key arm on the stimulus side: ``{index:4, selection:3}``
        (``manifest.h``) makes 0x10 uniquely "selection=PUBK_SEL_FUSE_KEY_0,
        index=0";
      * ``PUBK_REVOKE=0x00000001`` exactly once -- the fuse word
        ``check_pubkey_revoked`` read (``manifest_crypto.c``), proving the
        revocation check ran and PERMITTED this key. Note this marker does NOT by
        itself prove which arm ran: ``check_pubkey_revoked`` is called from the
        ROM-key arm too. What excludes that arm is ``KEY_REVOKED`` being
        forbidden outright -- ``CHIPLET_PUBK_REVOKE`` bit 0 IS blown in this
        member's preload, so a ROM taking the ROM-key arm with index 0 would have
        printed ``KEY_REVOKED idx=0x00000000`` and refused the image;
      * ``RSA_VERIFY_START`` then ``SIG_VALID`` then ``CRYPTO_VALIDATE_OK``, in that
        order and after the selector echo: the modulus reached the verifier, which
        happens only once the revocation check and the FUSE digest bind have both
        passed (``manifest_crypto.c``);
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
            "RSA_VERIFY_START",
            "SIG_VALID",
            "CRYPTO_VALIDATE_OK",
            "BL1_COPIED",
            "BL1_JUMP=",
        )
        # Every rejecting arm of validate_signature, both arms' empty-slot checks,
        # the ROM-key-arm counterfactual, and the failover evidence. This is a
        # positive test, so none of them may fire.
        cls.forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
            "SBOOT_OFF",
            "FUSE: SBOOT_DIS: 1",
            _BACKUP_SRC,
            "MANIFEST_ERR=",
            "MANIFEST_ALL_FAILED",
            "BAD_SIG_TYPE=",
            "BAD_KEY_IDX",
            "BAD_KEY_SEL",
            "ROM_KEY_EMPTY",
            "FUSE_KEY_EMPTY",
            "PUBK_HASH_MISMATCH",
            "PUBK_HASH_TIMEOUT",
            "KEY_REVOKED",
            "VERSION_ROLLBACK",
            "RSA_VERIFY_FAIL",
            "CRYPTO_FAIL=",
            "LC_USAGE_CONSTRAINT_FAIL",
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
        i_rsa = index_of("RSA_VERIFY_START")
        i_sig = index_of("SIG_VALID")
        i_ok = index_of("CRYPTO_VALIDATE_OK")

        # CHK-FUSEKEY-RAN: the fused-key path executed on the PRIMARY in the
        # architected order -- slot read, selector read, revocation bitmap consulted
        # and permitted, verifier driven, signature valid. Presence alone says
        # nothing about order, and order is the substance.
        assert 0 <= i_psrc < i_sel < i_revoke < i_rsa < i_sig < i_ok, (
            f"the fused-key path did not run on the primary in the architected "
            f"order: primary@{i_psrc} -> {self._PUBK_SEL_ECHO}@{i_sel} -> "
            f"{self._REVOKE_ECHO}@{i_revoke} -> RSA_VERIFY_START@{i_rsa} -> "
            f"SIG_VALID@{i_sig} -> CRYPTO_VALIDATE_OK@{i_ok}. Console: {console}"
        )
        # Exactly once each. The backup is never read in this scenario, so a second
        # occurrence would mean a slot this testcase did not select also reached key
        # selection or the verifier.
        for marker in (self._PUBK_SEL_ECHO, self._REVOKE_ECHO, "RSA_VERIFY_START", "SIG_VALID"):
            n = sum(1 for line in console if marker in line)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the primary's). "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-FUSEKEY-RAN PASS: primary@%d -> %s@%d -> %s@%d -> RSA_VERIFY_START@%d -> "
            "SIG_VALID@%d -> CRYPTO_VALIDATE_OK@%d, each exactly once; the ROM read "
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
    (``MANIFEST_ALL_FAILED``, ``manifest_load.c``). That is the strict form of
    the revocation property, and it is available here for BOTH members -- unlike the
    ROM-slot families, where only slot 0 is strict.
    """

    _REVOKED = True

    expected_error = MANIFEST_ERR_KEY_REVOKED
    primary_expected_error = MANIFEST_ERR_KEY_REVOKED
    # Every other rejecting arm of validate_signature, both empty-slot checks, and
    # proof the modulus never reached the verifier. RSA_VERIFY_START and SIG_VALID
    # are the load-bearing forbids: both manifests are otherwise valid, so without
    # them a revocation that did nothing would boot. ROM_ARM_KEY_REVOKED is the
    # ROM-key-arm counterfactual described in the module docstring.
    extra_forbidden = (
        "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY",
        "PUBK_HASH_MISMATCH",
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

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls._CHIPLET_KEY >= 0:
            cls.backup_defect_marker = cls._KEY_REVOKED_ECHO

    # --- stimulus ----------------------------------------------------------
    def corrupt_primary(self, buf: bytearray) -> None:
        # NOT the base's default BAD_MAGIC trigger. The primary is the first slot
        # under test here and must reach validate_signature, exactly as the
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
            "passes payload_hash, every TOC image digest, manifest_hash over the TBS "
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
        # CRYPTO_FAIL= is PRESENT, and its index_of() returns the FIRST occurrence,
        # which here is the primary's -- so without this the run's convergence on
        # KEY_REVOKED would rest on the primary alone and the backup's own crypto
        # verdict would be unasserted.
        crypto_fail = f"CRYPTO_FAIL=0x{self.expected_error:08x}"
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
        # the first". manifest_load.c, reached only after the loop.
        assert any("MANIFEST_ALL_FAILED" in line for line in console), (
            f"ROM never printed MANIFEST_ALL_FAILED (manifest_load.c:808): the retry "
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
