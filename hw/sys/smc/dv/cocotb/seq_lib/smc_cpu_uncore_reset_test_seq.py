# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CPU cluster's uncore reset requested on its own.

`cpu_ctrl.rdl` gives `RESET_CTRL.uncore_reset_n_n0_scan` as an active-low
reset for the cluster's uncore, and `RESET_TIMEOUT.reset_applied` as set once
a software reset request "has been applied either after drain completes or
after a force-mode timeout". A request is any held core or uncore reset, or a
core pulse.

With `RESET_TIMEOUT` in force mode, so the request is applied whether or not
the cluster drains, the uncore reset is written low with every core field
left high. `reset_applied` has to set. The uncore reset is then written high
again, and `reset_applied` has to clear with the request gone. `RESET_CTRL`
and `RESET_TIMEOUT` are restored and read back.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import cpu_ctrl_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
UNCORE_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__UNCORE_RESET_N_N0_SCAN_bm")
CORE_LEVEL_N = (
    cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE0_RESET_N_N0_SCAN_bm")
    | cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE1_RESET_N_N0_SCAN_bm")
    | cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE2_RESET_N_N0_SCAN_bm")
    | cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE3_RESET_N_N0_SCAN_bm")
)
VALUE_BP = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_VALUE_bp")
MODE_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_MODE_bm")
APPLIED = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_APPLIED_bm")
TIMED_OUT = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_TIMEOUT_bm")

FORCE_AFTER_32 = (32 << VALUE_BP) | MODE_BM
_POLLS = 64


class smc_cpu_uncore_reset_test_seq(SmcCsrSeq):
    """Hold the uncore reset alone, then release it."""

    def __init__(self, name: str = "smc_cpu_uncore_reset_test_seq") -> None:
        super().__init__(name)
        self.applied: tuple[int, int] | None = None

    async def _await_status(self, tag: str, want_applied: bool) -> int:
        word = 0
        for i in range(_POLLS):
            word = await self.csr_read(f"{tag}_{i}", RESET_TIMEOUT, length=8)
            if bool(word & APPLIED) == want_applied:
                return word
        raise AssertionError(
            f"{tag}: RESET_TIMEOUT 0x{word:x}, reset_applied never read "
            f"{int(want_applied)} within {_POLLS} reads"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        ctrl = await self.csr_read("RESET_CTRL_IDLE", RESET_CTRL, length=8)
        timeout = await self.csr_read("RESET_TIMEOUT_IDLE", RESET_TIMEOUT, length=8)
        assert ctrl & UNCORE_N and ctrl & CORE_LEVEL_N == CORE_LEVEL_N, (
            f"RESET_CTRL 0x{ctrl:x}: the uncore and every core are expected released at idle"
        )
        assert not timeout & APPLIED, f"RESET_TIMEOUT 0x{timeout:x}: a reset is already applied"

        await self.csr_write("UNCORE_TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_32, length=8)
        held = ctrl & ~UNCORE_N
        await self.csr_write("UNCORE_HOLD", RESET_CTRL, held, length=8)
        await self.csr_read("UNCORE_HOLD_RB", RESET_CTRL, length=8, expected=held)
        during = await self._await_status("UNCORE_APPLIED", True)
        await self.csr_write("UNCORE_RELEASE", RESET_CTRL, ctrl, length=8)
        after = await self._await_status("UNCORE_RELEASED", False)
        assert not after & TIMED_OUT, (
            f"RESET_TIMEOUT 0x{after:x}: reset_timeout still set with no request outstanding"
        )
        self.applied = (during, after)
        cocotb.log.info(
            "CHK-CPU-UNCORE-RESET: the uncore reset written low with every core released set "
            "reset_applied (RESET_TIMEOUT 0x%x), and writing it high again cleared "
            "reset_applied and reset_timeout (RESET_TIMEOUT 0x%x)",
            during,
            after,
        )

        await self.csr_write("RESET_TIMEOUT_RESTORE", RESET_TIMEOUT, timeout, length=8)
        await self.csr_read("RESET_TIMEOUT_RESTORE_RB", RESET_TIMEOUT, length=8, expected=timeout)
        await self.csr_read("RESET_CTRL_RESTORE_RB", RESET_CTRL, length=8, expected=ctrl)
