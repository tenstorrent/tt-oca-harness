# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot the smallest SMC firmware image and read its verdict.

`fw/tests/hello_world/hello_world.c` is `test_pass(0)` and a `wfi` loop, so the
only thing this can prove is that the firmware path is intact end to end -- and
that is what it is for. Everything on that path has to work for the store to
land: c_compile builds the image, the runner stages `hello_world.ecc.hex` into
the simulator directory, `smc_cpu_mem_dv` scatters it across the 32 scratch banks
using the decode in `smc_scratch_map_pkg`, the sequence programs the reset
vector and releases `boot_stall`, crt0
runs picolibc init and `__metal_synchronize_harts` across all four harts, and
`test_pass(0)` writes CPU_CTRL SCRATCH_0 over MMIO.

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


class smc_fw_hello_world_test_seq(SmcCsrSeq):
    """Scratch-image boot to the firmware's own PASS word."""

    def __init__(self, name: str = "smc_fw_hello_world_test_seq") -> None:
        super().__init__(name)
        self.boot: dict[str, object] = {}

    async def body(self) -> None:
        # require_image=True: without the staged image there is nothing to
        # boot, and reporting that as a skip would leave a green run that
        # proved nothing.
        self.boot = await check_cpu_firmware_boot_contract(self, require_image=True)
        cocotb.log.info(
            "CHK-FW-HELLO-WORLD-BOOT: %s",
            ", ".join(f"{k}={v}" for k, v in sorted(self.boot.items())),
        )
