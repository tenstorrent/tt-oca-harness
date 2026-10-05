# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest names a reserved key slot -> terminal.

The primary's magic is broken to force failover. The backup's ``public_key_select`` names slot 26,
which the format reserves (``[31:26]``), so the platform refuses it with ``PUBK_SLOT_RESERVED``
before it looks for an anchor. Slot 26 is ``OCA_KEY_SLOT_MAX + 1``, the smallest slot the bound
must refuse, so only this value catches ``>=`` written for ``>``. Slot 25 is a fuse-held chiplet
key and is accepted.

``sep_firmware_backup_invalid_public_key_selection_test`` names two slots and is refused for
ambiguity. Both return ``MANIFEST_ERR_KEY_UNAUTHORIZED``, so the console token is the only
discriminator: ``PUBK_SLOT_RESERVED`` is required and ``PUBK_SEL_AMBIGUOUS`` is forbidden.

The reserved-range check runs before revocation, which indexes its bitmap by slot number.
``PUBK_REVOKE=`` and ``PUBK_SLOT_UNPROVISIONED`` are forbidden, so the bound must stop the slot
first. The selector is inside the signed region, so the helper re-hashes; ``RSA_EXEC`` is
forbidden, so the stale signature is never examined. No ``+esrc_noise_force``.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_KEY_UNAUTHORIZED,
    sep_backup_manifest_fail_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# The boundary: the smallest index the ROM key table does not contain.
_BAD_INDEX = mm.KEY_SLOT_FIRST_RESERVED
_PUBK_SEL_VALUE = _BAD_INDEX
_PUBK_SEL_ECHO = f"PUBK_SEL=0x{_PUBK_SEL_VALUE:08x}"


@pyuvm.test()
class sep_firmware_backup_rom_key_index_invalid_test(sep_backup_manifest_fail_base):
    """Primary BAD_MAGIC -> failover -> backup names reserved key slot 26 -> terminal."""

    backup_defect_marker = "PUBK_SLOT_RESERVED"
    expected_error = MANIFEST_ERR_KEY_UNAUTHORIZED
    efuse_preload = _EFUSE_PRELOAD
    # PUBK_REVOKE= and PUBK_SLOT_UNPROVISIONED are the load-bearing pair: they are the next
    # two things an accepted index would have caused, and an out-of-range index
    # reaching either would be indexing past its own table. The rest are the arms
    # that would make the verdict mean something other than "the index was out of
    # range".
    extra_forbidden = (
        "PUBK_REVOKE=",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_UNAUTHORIZED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_OTP_EMPTY",
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "PUBK_ALGO_UNSUPPORTED",
    )

    def corrupt_backup(self, buf: bytearray) -> None:
        mm.set_public_key_sel(buf, "backup", selection=0, index=_BAD_INDEX)
        got = mm.get_public_key_sel(buf, "backup")
        assert got == _PUBK_SEL_VALUE, (
            f"backup public_key_sel names slot {got}, expected "
            f"{_PUBK_SEL_VALUE} (the first reserved slot)"
        )
        # Exactly one bit, or this would be the PUBK_SEL_AMBIGUOUS testcase
        # wearing this one's name. get_public_key_sel raises on any other count,
        # so reaching here at all is the assertion.
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-KEY-INDEX: backup public_key_sel names slot %d "
            "(== OCA_KEY_SLOT_MAX + 1, the smallest reserved slot), re-hashed",
            got,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot "
            f"reject a manifest when the device carries no security flags, and "
            f"that is what keeps this verdict attributable to the key decision"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: this testcase "
            f"forbids the fuse echo to prove the index bound ran first, so the "
            f"bitmap must be clear for that forbid to be meaningful"
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        # The value the ROM actually read out of the manifest. Without it,
        # PUBK_SLOT_RESERVED could belong to any out-of-range index, including one this
        # stimulus did not plant.
        assert any(_PUBK_SEL_ECHO in line for line in console), (
            f"ROM never printed {_PUBK_SEL_ECHO}: the PUBK_SLOT_RESERVED verdict cannot "
            f"be attributed to the index this testcase planted. Console: {console}"
        )
        n = sum(1 for line in console if "PUBK_SLOT_RESERVED" in line)
        assert n == 1, (
            f"PUBK_SLOT_RESERVED appeared {n} times, expected exactly 1 (the backup's). Console: {console}"
        )
        self.logger.info(
            "CHK-KEY-INDEX-ECHO: ROM read %s and refused it once, without "
            "consulting the revocation bitmap",
            _PUBK_SEL_ECHO,
        )
