# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary does not permit the live lifecycle; the backup boots.

``selector_bits[16]`` gates the lifecycle usage constraint. With it set the ROM
maps the live OTP lifecycle to a manifest bitmap bit through
``lc_state_to_manifest_bit`` (``bootrom/prod/src/lifecycle.c``) and refuses the
slot when ``usage_constraints.life_cycle_states`` has that bit clear, printing
``LC_USAGE_CONSTRAINT_FAIL``, ``LC_ALLOWED=`` and ``LC_BIT=`` and returning
``MANIFEST_ERR_LC_USAGE_CONSTRAINT`` (``bootrom/prod/src/manifest_load.c``). The
reference expects that verdict on the primary and a completed boot from the
backup.

WHICH BITMAP, AND WHY IT IS NOT 6. The
reference writes ``life_cycle_states = 6`` (PROD | PROD_END) and runs on its
default OTP image, whose lifecycle is TEST_DEV -- so its bitmap excludes exactly
the state the part is in. This environment cannot use 6: the shared failover base
requires the PROD preload, because secure boot has to be enforced for the backup
to complete the crypto chain, and 6 PERMITS PROD, so the constraint would be
satisfied and the testcase would prove nothing. The port therefore keeps the
reference's shape -- remove the live state's bit, keep the other two -- and
applies it to PROD, giving ``0x5`` (TEST_DEV | PROD_END). The verification intent
is preserved exactly and the evidence is stronger: ``LC_BIT=0x00000001``
pins the ROM to having DECODED the live lifecycle as PROD, which a bitmap of 0
(refuse everything) would not.

``selector_bits[16]`` is already set in the shipped image, so unlike the two
device-id arms this stimulus is a value change rather than an enable, and
:func:`plant_lc_state_defect` asserts the selector is set rather than assuming
it -- with the bit clear the ROM skips the check and the stimulus would be inert.

**HOW THIS IS TOLD APART FROM THE TWO DEVICE-ID SIBLINGS.** All three arms share
``MANIFEST_ERR_LC_USAGE_CONSTRAINT`` and the same terminal shape, so this member
requires ``LC_USAGE_CONSTRAINT_FAIL`` and forbids ``CHIPLET_ID_MISMATCH`` and
``PACKAGE_ID_MISMATCH``, and each sibling forbids this one's token.

MARKER SUBSTITUTION. There is no per-reason status code at all:
``bootrom/prod/include/status_values.h`` defines ``SEP_MSG_LIFECYCLE_INVALID``
(0x01) for the OTP lifecycle decode in ``lifecycle.c`` and
``SEP_MSG_FUSE_LC_STATE`` (0x20), and neither is emitted by the manifest
usage-constraint arm. The debug console tokens are the only per-reason evidence.
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
class sep_firmware_manifest_primary_lc_state_failure_test(
        sep_primary_usage_constraint_base):
    """Primary permits TEST_DEV|PROD_END on a PROD part -> refused -> backup boots."""

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
            slot, before, after, LIVE_LC_MANIFEST_BIT,
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
            "absent from the manifest's 0x%08x", bit, allowed,
        )
