# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""LOCAL_BASE is fixed read-only at 0xC000_0000; GLOBAL_BASE is programmable.

``memmap.adoc`` (Memory Map) states that the local alias base ``LOCAL_BASE``
is "fixed read-only at 0xC000_0000", that ``GLOBAL_BASE`` is "programmable by
firmware", and that both apertures are sized by ``REGION_SIZE``, which
"resets to 16 MiB". Those three sentences are the expectations here; nothing
is read back from the DUT to form them.

While ``GLOBAL_BASE`` holds its pattern, ``LOCAL_BASE`` is also read at its
global address: ``fabric.adoc`` lets a local resource be addressed "using
either their global address or a local alias address". The same address is
read first with ``GLOBAL_BASE`` at its reset and must answer DECERR, so the
later read shows the decode follows the programmed ``GLOBAL_BASE``.

The write-has-no-effect leg is given a positive control in the same block:
``GLOBAL_BASE`` takes and returns a pattern through the identical write path,
so a dropped ``LOCAL_BASE`` write is attributable to the read-only attribute
and not to a dead write channel. ``GLOBAL_BASE`` is restored before the
sequence ends and ``LOCAL_BASE`` is written last, so a DUT that wrongly
accepted the write would fail its own readback rather than silently
re-basing every later access.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import LOCAL_BASE_RESET, REGION_SIZE_RESET, smc_addr
from .smc_decode_probe_utils import SmcDecodeProbeSeq

LOCAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
GLOBAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")

# The goldens are the generated reset values (smc_base_config.h). memmap.adoc
# (Memory Map) states the same two values in prose; the asserts make a drift
# between the specification and the RDL fail at import instead of passing.
SPEC_LOCAL_BASE = LOCAL_BASE_RESET
SPEC_REGION_SIZE_RESET = REGION_SIZE_RESET
assert SPEC_LOCAL_BASE == 0xC000_0000, (
    f"LOCAL_BASE resets to 0x{SPEC_LOCAL_BASE:x}; memmap.adoc fixes it at 0xC000_0000"
)
assert SPEC_REGION_SIZE_RESET == 16 * 1024 * 1024, (
    f"REGION_SIZE resets to 0x{SPEC_REGION_SIZE_RESET:x}; memmap.adoc says 16 MiB"
)
# A base inside the 56-bit address space that differs from the reset in every
# byte the reset sets; restored afterwards.
GLOBAL_BASE_PATTERN = 0x0000_0050_0000_0000
# A local base a DUT that ignored the read-only attribute would happily take.
LOCAL_BASE_WRITE_ATTEMPT = 0xC200_0000

# Reads carrying an expectation: REGION_SIZE, LOCAL_BASE three times (once
# through the global window), GLOBAL_BASE pattern and restore readbacks.
EXPECTED_VALUE_CHECKS = 6
EXPECTED_ACCESSES = 11


class smc_dual_base_addressing_test_seq(SmcDecodeProbeSeq):
    """LOCAL_BASE read-only, GLOBAL_BASE programmable, REGION_SIZE reset."""

    def __init__(self, name: str = "smc_dual_base_addressing_test_seq") -> None:
        super().__init__(name)
        self.global_base_reset: int | None = None

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        await self.read_reset("REGION_SIZE_RESET", REGION_SIZE, SPEC_REGION_SIZE_RESET, length=8)
        await self.read_reset("LOCAL_BASE_READ", LOCAL_BASE, SPEC_LOCAL_BASE, length=8)
        self.close_cell(
            "local-base-reads-c0000000",
            f"LOCAL_BASE @0x{LOCAL_BASE:08x} read 0x{SPEC_LOCAL_BASE:08x} (memmap.adoc); "
            f"REGION_SIZE read 0x{SPEC_REGION_SIZE_RESET:x}",
        )

        # Positive control for the write channel: GLOBAL_BASE is the
        # programmable sibling in the same register block.
        self.global_base_reset = await self.csr_read("GLOBAL_BASE_SAVE", GLOBAL_BASE, length=8)
        assert self.global_base_reset != GLOBAL_BASE_PATTERN, (
            "GLOBAL_BASE already holds the probe pattern; the write control would prove nothing"
        )
        # Negative control for the global-window read below: while GLOBAL_BASE
        # still holds its reset value, the same address lies in neither the
        # local nor the global aperture, and the fabric's error slave answers
        # it (fabric.adoc, Traffic Subordinates). Only the GLOBAL_BASE write can
        # turn it into LOCAL_BASE.
        via_global = GLOBAL_BASE_PATTERN + (LOCAL_BASE - SPEC_LOCAL_BASE)
        monitor = getattr(self.env, "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.add(via_global)
        await self.read_decerr("LOCAL_BASE_VIA_GLOBAL_BEFORE", via_global, length=8)
        await self.csr_write("GLOBAL_BASE_PATTERN", GLOBAL_BASE, GLOBAL_BASE_PATTERN, length=8)
        await self.csr_read(
            "GLOBAL_BASE_PATTERN_RB", GLOBAL_BASE, expected=GLOBAL_BASE_PATTERN, length=8
        )
        # fabric.adoc (Local and Remote Resource Access): "Local resources can be
        # addressed using either their global address or a local alias address."
        await self.read_reset("LOCAL_BASE_VIA_GLOBAL", via_global, SPEC_LOCAL_BASE, length=8)
        self.close_cell(
            "local-resource-via-global-address",
            f"0x{via_global:x} answered DECERR while GLOBAL_BASE held its reset "
            f"0x{self.global_base_reset:x}, and with GLOBAL_BASE at 0x{GLOBAL_BASE_PATTERN:x} "
            f"read LOCAL_BASE's 0x{SPEC_LOCAL_BASE:08x}",
        )
        await self.csr_write("GLOBAL_BASE_RESTORE", GLOBAL_BASE, self.global_base_reset, length=8)
        await self.csr_read(
            "GLOBAL_BASE_RESTORE_RB", GLOBAL_BASE, expected=self.global_base_reset, length=8
        )

        # The read-only leg, last: the same write path, one register up.
        await self.csr_write(
            "LOCAL_BASE_WRITE_ATTEMPT", LOCAL_BASE, LOCAL_BASE_WRITE_ATTEMPT, length=8
        )
        await self.read_reset("LOCAL_BASE_AFTER_WRITE", LOCAL_BASE, SPEC_LOCAL_BASE, length=8)
        self.close_cell(
            "local-base-write-has-no-effect",
            f"writing 0x{LOCAL_BASE_WRITE_ATTEMPT:08x} to LOCAL_BASE left it at "
            f"0x{SPEC_LOCAL_BASE:08x}, while the same write path took "
            f"0x{GLOBAL_BASE_PATTERN:x} into GLOBAL_BASE (restored to 0x{self.global_base_reset:x})",
        )

        self.assert_all_reachable(EXPECTED_ACCESSES, "DUAL_BASE_ADDRESSING")
        self.report_cells("CHK-DUAL-BASE")
        cocotb.log.info(
            "CHK-DUAL-BASE-ADDRESSING: LOCAL_BASE fixed at 0x%08x across a write attempt of "
            "0x%08x; GLOBAL_BASE programmable (0x%x -> 0x%x -> 0x%x); REGION_SIZE reset 0x%x",
            SPEC_LOCAL_BASE,
            LOCAL_BASE_WRITE_ATTEMPT,
            self.global_base_reset,
            GLOBAL_BASE_PATTERN,
            self.global_base_reset,
            SPEC_REGION_SIZE_RESET,
        )
