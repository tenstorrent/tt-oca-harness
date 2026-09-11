# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup does not permit the live lifecycle; the ROM halts.

The mirror of ``sep_firmware_manifest_primary_lc_state_failure_test``. The primary
is refused by the failover trigger, the backup's
``usage_constraints.life_cycle_states`` excludes the live lifecycle, and with both
slots refused ``rom_manifest_boot`` runs out of retries and ``rom_err_fail`` halts
the ROM (``bootrom/prod/src/manifest_load.c``, ``bootrom/prod/src/rom_main.c``).

THE FAILOVER TRIGGER. Unlike the two device-id backup
scenarios, this one already reaches the backup by corrupting the primary's
``manifest_identifier`` (its ``BACKUP_INVALID_LC_STATE`` config sets
``primary.manifest.manifest_identifier`` to 99), which is exactly what the shared
``corrupt_primary`` does here. So no adaptation of the trigger is needed: this
member keeps both halves of the stimulus.

The bitmap adaptation is the one described in the primary-side sibling: the
reference's ``life_cycle_states = 6`` excludes TEST_DEV on a TEST_DEV part, and
this environment runs PROD, so the same shape applied to PROD gives ``0x5``.

**HOW THIS IS TOLD APART FROM THE OTHER TWO BACKUP-SIDE ARMS.** This member
requires ``LC_USAGE_CONSTRAINT_FAIL`` with ``LC_ALLOWED=0x00000005`` and
``LC_BIT=0x00000001``, and forbids ``CHIPLET_ID_MISMATCH`` and
``PACKAGE_ID_MISMATCH``; each sibling forbids this one's token. ``LC_BIT=`` is
also the strongest single line available on any of the three: it is the ROM's own
decode of the OTP lifecycle.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_usage_constraint_base import (
    LC_ALLOWED_WITHOUT_LIVE,
    LIVE_LC_MANIFEST_BIT,
    sep_backup_usage_constraint_base,
)


@pyuvm.test()
class sep_firmware_manifest_backup_lc_state_failure_test(
        sep_backup_usage_constraint_base):
    """Backup permits TEST_DEV|PROD_END on a PROD part -> both refused -> halt."""

    defect_marker = fd.LC_MARKER
    defect_evidence = fd.lc_state_required_markers(LC_ALLOWED_WITHOUT_LIVE,
                                                   LIVE_LC_MANIFEST_BIT)

    def plant(self, buf: bytearray, slot: str) -> None:
        before = mm.life_cycle_states(buf, slot)
        fd.plant_lc_state_defect(buf, slot, LC_ALLOWED_WITHOUT_LIVE)
        after = mm.life_cycle_states(buf, slot)
        assert not after & (1 << LIVE_LC_MANIFEST_BIT), (
            f"life_cycle_states is 0x{after:08x} and still permits bit "
            f"{LIVE_LC_MANIFEST_BIT} (the live lifecycle): the constraint would be "
            f"satisfied and the slot would boot"
        )
        assert after, (
            "life_cycle_states is 0: a bitmap that permits nothing would refuse "
            "any lifecycle, so the rejection would not be specific to the live one"
        )
        self.logger.info(
            "CHK-STIMULUS-LC-STATE: %s life_cycle_states 0x%08x -> 0x%08x, which "
            "clears bit %d (PROD, the live lifecycle) and keeps TEST_DEV and "
            "PROD_END", slot, before, after, LIVE_LC_MANIFEST_BIT,
        )

    def check_constraint_evidence(self, console: list[str]) -> None:
        allowed = fd.hex_value(console, "LC_ALLOWED=")
        bit = fd.hex_value(console, "LC_BIT=")
        assert allowed == LC_ALLOWED_WITHOUT_LIVE, (
            f"LC_ALLOWED=0x{allowed:08x} is not the planted "
            f"0x{LC_ALLOWED_WITHOUT_LIVE:08x}: the ROM read a different bitmap "
            f"than this testcase wrote"
        )
        assert bit == LIVE_LC_MANIFEST_BIT, (
            f"LC_BIT=0x{bit:08x}, expected {LIVE_LC_MANIFEST_BIT} (PROD): the ROM "
            f"did not decode the live lifecycle, so its refusal is not attributable "
            f"to this part's state"
        )
        assert not allowed & (1 << bit), (
            f"LC_ALLOWED=0x{allowed:08x} permits LC_BIT=0x{bit:08x}: the ROM "
            f"refused a manifest that satisfied the constraint it echoed"
        )
        self.logger.info(
            "CHK-LC-STATE: ROM decoded the live lifecycle as bit %d and found it "
            "absent from the backup's 0x%08x", bit, allowed,
        )
