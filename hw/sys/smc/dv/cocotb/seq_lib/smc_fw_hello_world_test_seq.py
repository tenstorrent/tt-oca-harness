# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot the smallest SMC firmware image and read its verdict.

`fw/tests/hello_world/hello_world.c` is `test_pass(0)` and a `wfi` loop, so it
proves that the firmware path is intact end to end. Everything on that path has
to work for the store to land: c_compile builds the image, the runner stages
`hello_world.ecc.hex` into the simulator directory, `smc_cpu_mem_dv` scatters
it across the 32 scratch banks using the decode in `smc_scratch_map_pkg`, the
sequence programs the reset vector and releases `boot_stall`, crt0 runs
picolibc init and `__metal_synchronize_harts` across all four harts, and
`test_pass(0)` writes CPU_CTRL SCRATCH_0 over MMIO.

The bank residency in the plan's pass criteria is checked on the CPU's own
fetches: the per-bank scratch read counters of `smc_cpu_mem_dv` are snapshotted
before the cores are released and after the verdict, and every bank that moved
must be one of banks 0-3.

The verdict comes from `check_cpu_firmware_boot_contract`, which clears
SCRATCH_0 and reads the clear back before releasing the CPU, so a residual value
from an earlier test cannot be mistaken for this run's. It fails on
`TEST_FAIL` (0xFFFF_FFFF) and on the `0xBAD0_xxxx` fatal namespace as well as on
the bound expiring, and `require_image=True` here makes a run without the
staged image a failure rather than a skip.
"""

from __future__ import annotations

import cocotb

from .smc_cpu_vip_utils import check_cpu_firmware_boot_contract
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_scratch_residency_utils import (
    HELLO_WORLD_RESIDENT_BANKS,
    check_scratch_residency,
    snapshot_scratch_bank_reads,
)


class smc_fw_hello_world_test_seq(SmcCsrSeq):
    """Scratch-image boot to the firmware's own PASS word."""

    def __init__(self, name: str = "smc_fw_hello_world_test_seq") -> None:
        super().__init__(name)
        self.boot: dict[str, object] = {}

    async def body(self) -> None:
        # require_image=True: without the staged image there is nothing to
        # boot, and reporting that as a skip would leave a green run that
        # proved nothing.
        bank_reads_before = snapshot_scratch_bank_reads()
        self.boot = await check_cpu_firmware_boot_contract(self, require_image=True)
        # Residency is scored on the CPU's own fetches: every scratch bank read
        # between the pre-release snapshot and the verdict must be one of the
        # banks the plan places the image in.
        bank_reads = check_scratch_residency(
            bank_reads_before, snapshot_scratch_bank_reads(), HELLO_WORLD_RESIDENT_BANKS
        )
        self.boot["scratch_banks_read"] = sorted(bank_reads)
        self.boot["scratch_reads_per_bank"] = bank_reads
        cocotb.log.info(
            "CHK-FW-HELLO-WORLD-BOOT: %s",
            ", ".join(f"{k}={v}" for k, v in sorted(self.boot.items())),
        )
