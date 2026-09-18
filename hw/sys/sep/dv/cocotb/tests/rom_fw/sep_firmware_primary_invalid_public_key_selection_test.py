# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest names two public keys at once; the backup boots.

The PRIMARY's ``public_key_select_classic`` names ROM key slots 0 AND 1. Under OCA
the field is a 128-bit BITMAP, not a packed selection value, and
[SEP-ROM-SB-045] requires it to resolve to exactly one slot: a bitmap with more
than one bit set is ambiguous about which anchor applies, so the ROM refuses it
rather than resolving to either. Both named slots are individually valid and
provisioned, which is what makes the ambiguity itself the sole possible cause.

``plat_is_key_authorized`` (``oca_platform.c``) prints ``PUBK_SEL_AMBIGUOUS`` and
returns ``OCA_FAIL_ROOT_KEY_UNAUTHORIZED`` -- a key-AUTHORIZATION verdict, not a
signature one. The refusal happens inside the resolution loop, before any slot
number is echoed, so the primary contributes no ``PUBK_SEL=`` line and the single
``PUBK_SEL=`` in the console is the backup's.

THE PRIMARY MUST NOT BE BROKEN ANY OTHER WAY, and that is the whole difference between
this testcase and its backup-side sibling. So there is no BAD_MAGIC failover trigger
here: the primary is structurally perfect and is rejected by key selection alone.

The expected outcome is A Completed boot, NOT A Terminal failure. Copying the backup-
side base class here would have inverted the requirement.

Platform adaptation -- MARKER. This ROM *defines* that code
(``bootrom/prod/include/status_values.h:12``) but never EMITS it: there is no
``report_status`` call for it anywhere under ``bootrom/prod/src``, so the architected
status ring carries only the generic terminal code and the debug console token is the
only per-reason evidence available. Hence the ambiguity arm's
``PUBK_SEL_AMBIGUOUS`` is required here instead. ``PUBK_SLOT_RESERVED`` -- a bad ROM key
INDEX, a different arm -- is forbidden below so the two cannot be confused.

``public_key_sel`` is at offset 166, inside the TBS, so the helper re-hashes. No
re-sign: the selection is rejected before ``rsa_3072_verify``, so the primary's
now-stale signature is never examined, and the shared base forbids any
``RSA_EXEC`` before the backup read to check that rather than assume it.

Needs ``+esrc_noise_force``: the backup is valid, so the full RSA-3072 modexp
runs on OTBN, which parks in UrndRefresh until EDN grants entropy. The RSA
assertions are untouched, so ``RSA_VERIFY_OK`` still means the signature verified.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_fail_backup_boot_base import (
    MANIFEST_ERR_KEY_UNAUTHORIZED,
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# Two provisioned ROM key slots named at once. Both are individually valid, so
# the refusal can only be the ambiguity itself.
_AMBIGUOUS_SLOTS = (0, 1)
# The backup keeps the shipped selector: ROM key slot 0.
_BACKUP_SEL_ECHO = "PUBK_SEL=0x00000000"


@pyuvm.test()
class sep_firmware_primary_invalid_public_key_selection_test(sep_primary_fail_backup_boot_base):
    """Primary names two key slots at once -> refused -> backup boots."""

    primary_defect_marker = "PUBK_SEL_AMBIGUOUS"
    primary_expected_error = MANIFEST_ERR_KEY_UNAUTHORIZED
    efuse_preload = _EFUSE_PRELOAD
    # Only the backup's selector is echoed. The primary's is refused inside the
    # resolution loop, before any slot number is printed, so exactly one
    # PUBK_SEL= line in the whole run is itself the evidence -- asserted below.
    extra_required = (_BACKUP_SEL_ECHO,)
    # PUBK_SLOT_RESERVED is the discriminator against the index arm, which shares this
    # error code. The rest must not fire at all: the primary is rejected at the
    # selection and the backup is valid, so nothing else may complain.
    extra_forbidden = (
        "PUBK_SLOT_RESERVED",
        "PUBK_ALGO_UNSUPPORTED",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_OTP_EMPTY",
        "PUBK_UNAUTHORIZED",
        "RSA_PKCS1_FAIL",
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        # Anchor the modulus while the selection still resolves: verify_public_key
        # picks its digest via get_public_key_sel, which the ambiguity below makes
        # unresolvable by design. Proving the key is the one its selection claimed
        # before the mutation is what keeps the rejection attributable to the
        # bitmap rather than to a bad key.
        signed_slot = mm.verify_public_key(buf, "primary")
        # No manifest_identifier corruption: the primary must reach key selection.
        mm.set_public_key_slots(buf, "primary", _AMBIGUOUS_SLOTS)
        # get_public_key_sel refuses to resolve a bitmap naming more than one
        # slot, which is the property this stimulus is planting.
        try:
            got = mm.get_public_key_sel(buf, "primary")
        except AssertionError:
            pass
        else:
            raise AssertionError(
                f"primary public_key_sel resolved to a single slot {got}; the "
                f"bitmap should name {_AMBIGUOUS_SLOTS}"
            )
        # The re-hash must have restored a valid manifest hash, or the primary is
        # thrown out before key selection and this testcase would be asserting on
        # the wrong rejection.
        mm.verify_layout(buf, "primary")
        # set_public_key_slots rewrites the selection field and re-hashes; the
        # modulus is outside both, so the key anchored above is still in place.
        self.logger.info(
            "CHK-STIMULUS-PUBKSEL: primary public_key_sel names slots %s, both "
            "individually valid, modulus still the ROM key %d it was signed with, "
            "re-hashed, magic intact so the slot still reaches key authorization",
            _AMBIGUOUS_SLOTS,
            signed_slot,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: the backup selects "
            f"ROM slot 0 and must be able to use it, or nothing would boot"
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        i_psrc = index_of(f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}")
        i_bad = index_of("PUBK_SEL_AMBIGUOUS")
        i_bsrc = index_of(f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}")
        i_bsel = index_of(_BACKUP_SEL_ECHO)

        # CHK-PUBKSEL-ATTRIBUTION: the refusal happened on the PRIMARY, between
        # its read and the failover. The ambiguity is caught inside the resolution
        # loop, so there is no slot echo to tie it to -- the position between the
        # two slot reads is what attributes it, and the count check below is what
        # says no slot number was printed for it.
        assert 0 <= i_psrc < i_bad < i_bsrc, (
            f"the PUBK_SEL_AMBIGUOUS verdict is not attributable to the primary: "
            f"primary@{i_psrc} -> PUBK_SEL_AMBIGUOUS@{i_bad} -> backup@{i_bsrc}. "
            f"Console: {console}"
        )
        # CHK-PUBKSEL-UNRESOLVED: exactly one resolved slot in the run, the
        # backup's. A second would mean the primary's ambiguous bitmap was
        # resolved to something rather than refused.
        sels = [i for i, line in enumerate(console) if "PUBK_SEL=" in line]
        assert len(sels) == 1, (
            f"PUBK_SEL= appeared at {sels}, expected exactly 1 (the backup's): an "
            f"ambiguous bitmap must be refused before resolution completes. "
            f"Console: {console}"
        )
        # CHK-BACKUP-SELECTOR: the recovering slot used the valid ROM-key selector,
        # so the boot is attributable to slot 0 rather than to an unread selection.
        assert i_bsrc < i_bsel, (
            f"{_BACKUP_SEL_ECHO}@{i_bsel} did not follow the backup read@{i_bsrc}: "
            f"the booting slot's key selection is unattributed. Console: {console}"
        )
        self.logger.info(
            "CHK-PUBKSEL-FAILOVER: primary@%d -> PUBK_SEL_AMBIGUOUS@%d (no slot "
            "echoed) -> backup@%d -> %s@%d",
            i_psrc,
            i_bad,
            i_bsrc,
            _BACKUP_SEL_ECHO,
            i_bsel,
        )
