# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest selecting a RESERVED ROM key slot.

The primary is corrupted to force failover, then the backup's
``public_key_select_classic`` is pointed at the first reserved ROM classical slot
-- ``KEY_SLOT_FIRST_ROM_RESERVED``, the bottom of the ``[7:6]`` pair.

WHY THIS SLOT AND NOT AN EMPTY ONE. There is no empty one. All six provisioned
ROM slots carry a digest (``key_digests.c``), and the ROM's classical band is
exactly those six (``OCA_KEY_SLOT_ROM_CLASSICAL_LAST``), so the
``PUBK_SLOT_UNPROVISIONED`` arm is fail-closed defence rather than a state a
manifest can select. This testcase covers what a manifest CAN select and the ROM
must still refuse: a slot the format's octet contains but this generation does
not assign.

WHY A RESERVED SLOT MUST FAIL CLOSED. The RSA modulus used for verification comes
out of the manifest itself (``m->public_key.rsa_modulus``), so binding that
modulus to a digest the ROM holds is the only thing that makes the signature mean
anything. A slot with no anchor behind it has nothing to bind against. If the
bind were skipped there, a manifest could select the slot, pass revocation -- its
fuse bit is 0 -- and then be verified against a modulus it supplied itself.
Signature verification would still report success and the boot would proceed on a
key that was never trusted.

WHAT MAKES THIS ATTRIBUTABLE. Nothing about the backup is invalid except the slot
number: it carries a real signature over a correctly hashed TBS, and the slot
passes the revocation check. It is distinct from the out-of-range arm, which
``sep_firmware_backup_rom_key_index_invalid_test`` drives at
``KEY_SLOT_FIRST_RESERVED`` in ``[31:26]``; the two share a console token, so the
``PUBK_SEL=`` echo below is what says which reserved region this run selected.
The arms that would indicate some other cause -- ``PUBK_SLOT_UNPROVISIONED``,
``PUBK_SEL_AMBIGUOUS``, ``PUBK_OTP_EMPTY`` -- are forbidden. ``RSA_EXEC`` is
forbidden too: the point is that the boot is stopped *before* an
attacker-supplied modulus reaches the verifier, not merely that it is stopped
eventually.
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

# The first RESERVED ROM classical slot. Slots 0..5 all carry a digest, so naming
# one of those would exercise the digest COMPARISON rather than the refusal this
# testcase is about.
_RESERVED_SLOT = mm.KEY_SLOT_FIRST_ROM_RESERVED
_PUBK_SEL_VALUE = _RESERVED_SLOT


@pyuvm.test()
class sep_firmware_backup_unpopulated_rom_key_slot_test(sep_backup_manifest_fail_base):
    """Primary fails over -> backup selects a reserved ROM key slot -> terminal."""

    backup_defect_marker = "PUBK_SLOT_RESERVED"
    expected_error = MANIFEST_ERR_KEY_UNAUTHORIZED
    efuse_preload = _EFUSE_PRELOAD
    # Every arm that would make the verdict mean something other than "the slot
    # had no digest", plus proof the modulus never reached the verifier.
    extra_forbidden = (
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_OTP_EMPTY",
    )

    def corrupt_backup(self, buf: bytearray) -> None:
        mm.set_public_key_sel(buf, "backup", selection=0, index=_RESERVED_SLOT)
        got = mm.get_public_key_sel(buf, "backup")
        assert got == _PUBK_SEL_VALUE, (
            f"backup public_key_sel names slot {got}, expected {_PUBK_SEL_VALUE} "
            f"(the first unprovisioned ROM classical slot)"
        )
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-EMPTY-SLOT: backup public_key_sel=0x%04x "
            "(ROM key slot %d, no compiled-in digest), TBS re-hashed",
            got,
            _RESERVED_SLOT,
        )

    def check_efuse(self, image) -> None:
        # Both of these run before slot resolution and would end the run first,
        # making the PUBK_SLOT_RESERVED verdict unreachable and the test vacuous.
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: slot "
            f"{_RESERVED_SLOT} must not be revoked, or the rejection would be "
            f"attributable to revocation rather than to the reserved slot"
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        # The selector the ROM actually read, so the verdict belongs to this
        # stimulus rather than to some other malformed field.
        marker = f"PUBK_SEL=0x{_PUBK_SEL_VALUE:08x}"
        assert any(marker in line for line in console), (
            f"ROM never printed {marker}: the PUBK_SLOT_RESERVED verdict cannot be "
            f"attributed to the slot this test selected. Console: {console}"
        )
        self.logger.info("CHK-RESERVED-SLOT-ECHO: ROM read %s", marker)
