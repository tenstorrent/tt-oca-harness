# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary does not permit the live lifecycle; the backup boots.

On a PROD part the primary's life_cycle_states becomes 0x5 (TEST_DEV | PROD_END), so
the ROM must decode the live lifecycle as PROD (LC_BIT=0x00000001) and refuse the slot.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_usage_constraint_base import (
    LC_ALLOWED_WITHOUT_LIVE,
    LIVE_LC_MANIFEST_BIT,
    sep_primary_usage_constraint_base,
)


@pyuvm.test()
class sep_firmware_manifest_primary_lc_state_failure_test(sep_primary_usage_constraint_base):
    """Primary permits TEST_DEV|PROD_END on a PROD part -> refused -> backup boots."""

    defect_marker = fd.LC_MARKER
    defect_evidence = fd.lc_state_required_markers(LC_ALLOWED_WITHOUT_LIVE, LIVE_LC_MANIFEST_BIT)

    def plant(self, buf: bytearray, slot: str) -> None:
        before = mm.lifecycle_states(buf, slot)
        fd.plant_lc_state_defect(buf, slot, LC_ALLOWED_WITHOUT_LIVE)
        after = mm.lifecycle_states(buf, slot)
        assert not after & (1 << LIVE_LC_MANIFEST_BIT), (
            f"life_cycle_states is 0x{after:08x} and still permits bit "
            f"{LIVE_LC_MANIFEST_BIT} (the live lifecycle): the constraint would be "
            f"satisfied and the slot would not be refused"
        )
        assert after, (
            "life_cycle_states is 0: a bitmap that permits nothing would refuse "
            "any lifecycle, so the rejection would not be specific to the live one"
        )
        self.logger.info(
            "CHK-STIMULUS-LC-STATE: %s life_cycle_states 0x%08x -> 0x%08x, which "
            "clears bit %d (PROD, the live lifecycle) and keeps TEST_DEV and "
            "PROD_END; selector_bits[16] was already set so the check runs",
            slot,
            before,
            after,
            LIVE_LC_MANIFEST_BIT,
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
            "absent from the manifest's 0x%08x",
            bit,
            allowed,
        )
