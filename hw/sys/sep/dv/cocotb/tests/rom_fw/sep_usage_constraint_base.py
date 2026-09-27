# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary and backup bases for usage-constraint rejections: fail over, or halt.

The lifecycle, chiplet_id and package_id arms share one error code, so each member
requires its own console token and forbids the other two.
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

MANIFEST_ERR_LC_USAGE_CONSTRAINT = 0x0003_0013

EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# Manifest lifecycle bitmap bit for the preload's PROD state.
LIVE_LC_MANIFEST_BIT = 1  # PROD
# TEST_DEV | PROD_END: the shipped 0x7 minus PROD, so only the live state is refused.
LC_ALLOWED_WITHOUT_LIVE = 0x5

# A slot that reaches a crypto failure path was refused somewhere else.
_CRYPTO_FORBIDDEN = (
    "CRYPTO_FAIL=",
    "RSA_VERIFY_FAIL",
    "PLD_HASH_MISMATCH",
    "MANIFEST_HASH_MISMATCH",
    "VERSION_ROLLBACK",
)


class _usage_constraint_mixin:
    defect_marker: str = ""
    defect_evidence: tuple[str, ...] = ()

    @classmethod
    def _forbidden(cls) -> tuple[str, ...]:
        assert cls.defect_marker in fd.SIBLING_MARKERS, (
            f"defect_marker {cls.defect_marker!r} is not one of the three usage-constraint tokens"
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
        raise NotImplementedError


class sep_primary_usage_constraint_base(_usage_constraint_mixin, sep_primary_fail_backup_boot_base):
    # The arm prints no CRYPTO_FAIL=, so check_transport() carries the attribution.
    primary_defect_marker = ""
    primary_expected_error = MANIFEST_ERR_LC_USAGE_CONSTRAINT
    # The constraint block runs before the RSA verifier, so the refused primary starts none.
    primary_expected_rsa_starts = 0
    efuse_preload = EFUSE_PRELOAD

    def __init__(self, *args, **kwargs) -> None:
        self.extra_forbidden = self._forbidden()
        # Require the full positive chain so the recovery is a real boot, not an early exit.
        self.extra_required = self.defect_evidence + ("PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
        super().__init__(*args, **kwargs)

    def corrupt_primary(self, buf: bytearray) -> None:
        self.plant(buf, "primary")

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        fd.assert_slot_attributed(console, slot_err, after=i_psrc, before=i_bsrc)
        i_defect = fd.assert_slot_attributed(
            console, self.defect_marker, after=i_psrc, before=i_bsrc
        )
        self.logger.info(
            "CHK-CONSTRAINT: %s@%d and %s inside the primary attempt (read@%d, backup read@%d)",
            self.defect_marker,
            i_defect,
            slot_err,
            i_psrc,
            i_bsrc,
        )
        self.check_constraint_evidence(console)

    def check_constraint_evidence(self, console: list[str]) -> None:
        pass


class sep_backup_usage_constraint_base(
    _usage_constraint_mixin, sep_backup_manifest_structural_fail_base
):
    expected_error = MANIFEST_ERR_LC_USAGE_CONSTRAINT
    # The inherited primary corruption gives BAD_MAGIC, distinct from the backup's code.
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
        pass
