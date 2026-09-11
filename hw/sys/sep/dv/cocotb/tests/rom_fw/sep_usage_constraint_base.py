# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The two shapes of a usage-constraint rejection: fail over, or halt.

Six testcases plant a lifecycle, chiplet_id or
package_id constraint the part does not satisfy. They differ on exactly two axes
-- which arm of the ``selector_bits`` block refuses the slot, and which slot
carries the defect -- so the two bases here hold everything else once.

All three arms return ``MANIFEST_ERR_LC_USAGE_CONSTRAINT``
(``bootrom/prod/src/manifest_load.c``), as does the encrypted-payload-without-
secure-boot rejection just ahead of the block, so they are separable only on the
console. Each member therefore requires its own token and forbids the other two
(``sep_manifest_field_defect.SIBLING_MARKERS``). Without that the six would be
mutually interchangeable: the error code, the status word and the boot outcome
are identical across all of them.

The block runs BEFORE ``manifest_crypto_validate`` and after
``manifest_check_integrity`` (``manifest_load.c``), which fixes what a run may
contain. A refused slot has already had its hash verified, so
``MANIFEST_HASH_OK`` is expected rather than forbidden; it has NOT reached the
verifier, so on the primary-side members the base's
``primary_expected_rsa_starts = 0`` is what checks that ordering, and on the
backup-side members ``RSA_VERIFY_START`` must be absent altogether.
"""

from __future__ import annotations

from pathlib import Path

from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_structural_fail_base import (
    sep_backup_manifest_structural_fail_base,
)
from rom_fw.sep_primary_fail_backup_boot_base import (
    sep_primary_fail_backup_boot_base,
)

# manifest.h -- shared by the lifecycle, chiplet_id and package_id arms.
MANIFEST_ERR_LC_USAGE_CONSTRAINT = 0x0003_0013

EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

# The live lifecycle of that preload, and the manifest bitmap bit
# lc_state_to_manifest_bit() maps it to (bootrom/prod/src/lifecycle.c).
LIVE_LC_MANIFEST_BIT = 1  # PROD
# TEST_DEV | PROD_END: the shipped 0x7 with the live state's bit removed. Keeping
# the other two is what makes the rejection specific to PROD rather than to a
# bitmap that permits nothing.
LC_ALLOWED_WITHOUT_LIVE = 0x5

# Markers that must not appear on either side: a slot that reached the crypto
# chain's failure paths was refused somewhere else.
_CRYPTO_FORBIDDEN = ("CRYPTO_FAIL=", "RSA_VERIFY_FAIL", "PLD_HASH_MISMATCH",
                     "MANIFEST_HASH_MISMATCH", "VERSION_ROLLBACK")


class _usage_constraint_mixin:
    """Subclass contract and the shared attribution check."""

    # One of sep_manifest_field_defect's three arm tokens.
    defect_marker: str = ""
    # Extra console lines the arm echoes, e.g. CID_IDX= / LC_ALLOWED=.
    defect_evidence: tuple[str, ...] = ()

    @classmethod
    def _forbidden(cls) -> tuple[str, ...]:
        assert cls.defect_marker in fd.SIBLING_MARKERS, (
            f"defect_marker {cls.defect_marker!r} is not one of the three "
            f"usage-constraint tokens"
        )
        return fd.SIBLING_MARKERS[cls.defect_marker] + _CRYPTO_FORBIDDEN

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)
        lc = image.lc_raw()
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}: LIVE_LC_MANIFEST_BIT and "
            f"LC_ALLOWED_WITHOUT_LIVE are both derived from PROD, so a different "
            f"lifecycle would make the lifecycle stimulus and its LC_BIT= "
            f"assertion disagree"
        )

    def plant(self, buf: bytearray, slot: str) -> None:
        """Apply the arm's stimulus to one slot."""
        raise NotImplementedError


class sep_primary_usage_constraint_base(_usage_constraint_mixin,
                                        sep_primary_fail_backup_boot_base):
    """Primary violates a usage constraint; the untouched backup boots."""

    # The arm prints its own token but no CRYPTO_FAIL=, so the base's
    # crypto-shaped defect-marker path is not used and check_transport() below
    # carries the attribution.
    primary_defect_marker = ""
    primary_expected_error = MANIFEST_ERR_LC_USAGE_CONSTRAINT
    primary_expected_rsa_starts = 0
    efuse_preload = EFUSE_PRELOAD

    def __init__(self, *args, **kwargs) -> None:
        self.extra_forbidden = self._forbidden()
        # The backup runs the whole positive chain, so "it recovered" is a real
        # boot rather than an early exit that happened not to fail.
        self.extra_required = self.defect_evidence + ("PLD_HASH_OK", "BL1_COPIED",
                                                      "BL1_JUMP=")
        super().__init__(*args, **kwargs)

    def corrupt_primary(self, buf: bytearray) -> None:
        self.plant(buf, "primary")

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        # CHK-CONSTRAINT-ATTRIBUTION: the arm's token and the shared error code
        # both sit inside the primary's attempt, and each occurs once. The code
        # alone cannot do this -- all three arms produce it -- and the token alone
        # would not tie the rejection to the slot.
        fd.assert_slot_attributed(console, slot_err, after=i_psrc, before=i_bsrc)
        i_defect = fd.assert_slot_attributed(console, self.defect_marker,
                                             after=i_psrc, before=i_bsrc)
        self.logger.info(
            "CHK-CONSTRAINT: %s@%d and %s inside the primary attempt (read@%d, "
            "backup read@%d)", self.defect_marker, i_defect, slot_err, i_psrc,
            i_bsrc,
        )
        self.check_constraint_evidence(console)

    def check_constraint_evidence(self, console: list[str]) -> None:
        """Arm-specific read-back of the values the ROM echoed."""


class sep_backup_usage_constraint_base(_usage_constraint_mixin,
                                       sep_backup_manifest_structural_fail_base):
    """Primary refused as BAD_MAGIC, backup violates a usage constraint, halt."""

    expected_error = MANIFEST_ERR_LC_USAGE_CONSTRAINT
    # sep_backup_manifest_fail_base.corrupt_primary() plants the identifier, and
    # BAD_MAGIC is deliberately a different code from the backup's so the two
    # slots' rejections stay individually countable.
    primary_expected_error = 0x0003_0002
    efuse_preload = EFUSE_PRELOAD

    def __init__(self, *args, **kwargs) -> None:
        self.extra_forbidden = self._forbidden()
        self.backup_defect_marker = self.defect_marker
        super().__init__(*args, **kwargs)

    def corrupt_backup(self, buf: bytearray) -> None:
        self.plant(buf, "backup")
        for marker in self.defect_evidence:
            self.logger.info("CHK-STIMULUS-EXPECTS: %s", marker)

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        for marker in self.defect_evidence:
            assert any(marker in line for line in console), (
                f"ROM never printed {marker}, so the arm's own echo of the values "
                f"it compared is missing and the rejection is not attributable to "
                f"the field this testcase plants. Console: {console}"
            )
            self.logger.info("CHK-CONSTRAINT-ECHO: %s", marker)
        self.check_constraint_evidence(console)

    def check_constraint_evidence(self, console: list[str]) -> None:
        """Arm-specific read-back of the values the ROM echoed."""
