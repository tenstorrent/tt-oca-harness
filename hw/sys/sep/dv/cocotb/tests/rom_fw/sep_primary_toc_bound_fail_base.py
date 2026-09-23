# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PRIMARY's TOC claims a bad length or places image 0 too low; the backup boots.

Members set bound_defect and encrypted. The TOC check runs after the signature and
decryption, so the primary reaches SIG_VALID before it is refused.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base


class sep_primary_toc_bound_fail_base(sep_primary_fail_backup_boot_base):

    # --- member contract ---------------------------------------------------
    # tbd.BOUND or tbd.PLEN.
    bound_defect: str = ""
    # Selects the encrypted image and fuse preload; checked against the image's own flag.
    encrypted: bool = False

    # The base would pair a defect marker with CRYPTO_FAIL=, which these arms never print.
    primary_defect_marker = ""
    # The primary's signature verifies and its payload decrypts; only the TOC is refused.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        assert cls.bound_defect in tbd.DEFECT_TOKEN, (
            f"{cls.__name__} must declare bound_defect as one of "
            f"{list(tbd.DEFECT_TOKEN)}, got {cls.bound_defect!r}"
        )
        cls.flash_image = tbd.ENCRYPTED_IMAGE if cls.encrypted else tbd.PLAINTEXT_IMAGE
        cls.efuse_preload = tbd.ENCRYPTED_EFUSE if cls.encrypted else tbd.PLAINTEXT_EFUSE
        cls.primary_expected_error = tbd.EXPECTED_ERROR[cls.bound_defect]
        cls.backup_sealed_check_toc = not cls.encrypted

        required = [tbd.DEFECT_TOKEN[cls.bound_defect],
                    "MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP="]
        # Forbid every code but this row's; the accepted backup prints no MANIFEST_ERR=.
        forbidden = tbd.neighbouring_errors(cls.bound_defect)
        forbidden += ["CRYPTO_FAIL=", "MANIFEST_ALL_FAILED"]
        forbidden += list(tbd.other_payload_tokens(cls.bound_defect))
        forbidden += list(tbd.DECRYPT_FAILURE_TOKENS)
        if cls.encrypted:
            required += [tbd.DECRYPT_START, tbd.DECRYPT_OK]
        else:
            # decrypt_payload() runs only for encrypted_payload; no DECRYPT_START proves plaintext.
            forbidden.append(tbd.DECRYPT_START)
        cls.extra_required = tuple(required)
        cls.extra_forbidden = tuple(forbidden)

    # --- stimulus ----------------------------------------------------------
    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # Fail here if the loaded image does not match the declared encryption.
        for slot in ("primary", "backup"):
            got = pm.is_encrypted(buf, slot)
            assert got == self.encrypted, (
                f"{slot} payload encrypted_payload flag is {int(got)} but this "
                f"member declares encrypted={self.encrypted}; the loaded image "
                f"({self.flash_image}) is not the one this cell is about"
            )
        self._payload_offset = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        # Keep the pre-TOC checks satisfiable; validate_manifest_header also returns BAD_LENGTH.
        major, minor = mm.manifest_version(buf, "primary")
        assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {major}.{minor}: the slot would be "
            f"refused by validate_manifest_header before the TOC is ever parsed"
        )
        assert mm.manifest_length(buf, "primary") == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {mm.manifest_length(buf, 'primary')}, "
            f"expected {mm.MANIFEST_SIZE}: validate_manifest_header would return "
            f"BAD_LENGTH from a different check with the same code"
        )
        self._served = tbd.plant(self.logger, buf, "primary", self.bound_defect)

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    # --- checks ------------------------------------------------------------
    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        token = tbd.DEFECT_TOKEN[self.bound_defect]
        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # The token and the error code must both be the primary's, in order, once each.
        n = fd.count(console, token)
        assert n == 1, (
            f"{token} appeared {n} times, expected exactly 1 (the primary's). "
            f"Console: {console}"
        )
        i_token = fd.assert_slot_attributed(console, token, after=i_psrc,
                                            before=i_bsrc)
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_token,
                                          before=i_bsrc)

        # The primary's TOC must be refused after its own payload decrypted, not instead of it.
        if self.encrypted:
            for marker in (tbd.DECRYPT_START, tbd.DECRYPT_OK):
                k = fd.count(console, marker)
                assert k == 2, (
                    f"{marker} appeared {k} times, expected exactly 2 (the mutated "
                    f"primary's and the recovering backup's). Console: {console}"
                )
            i_ds = fd.first_index(console, tbd.DECRYPT_START)
            i_do = fd.first_index(console, tbd.DECRYPT_OK)
            assert i_psrc < i_ds < i_do < i_token, (
                f"expected primary read@{i_psrc} -> {tbd.DECRYPT_START}@{i_ds} -> "
                f"{tbd.DECRYPT_OK}@{i_do} -> {token}@{i_token}: the primary's TOC "
                f"was not refused after its own payload decrypted. "
                f"Console: {console}"
            )
            self.logger.info(
                "CHK-DECRYPT-ARM: primary@%d -> %s@%d -> %s@%d -> %s@%d, and both "
                "markers appear twice (primary and recovering backup)",
                i_psrc, tbd.DECRYPT_START, i_ds, tbd.DECRYPT_OK, i_do, token, i_token,
            )

        # Check planted bytes by address: both slots' ciphertexts agree this early in the CBC chain.
        tbd.assert_served_bound_field(self.logger, flash, "primary",
                                      self.bound_defect, self._served,
                                      self._payload_offset)

        self.logger.info(
            "CHK-TOC-BOUND-RULE: primary@%d violated %s, was announced %s@%d and "
            "refused %s@%d inside its own attempt, after its signature verified; the "
            "untouched backup was read@%d and booted",
            i_psrc, self.bound_defect, token, i_token, slot_err, i_err, i_bsrc,
        )
