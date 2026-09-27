# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_BASE_CONFIG (CPU address-map + hang-detector) reset-value precheck.

The block at ``smc_addr("SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR")`` is SMC_BASE_CONFIG
(``hw/sys/smc/regs/blocks/smc_base_config/smc_base_config.rdl``), reached over
real SEP_IN AXI.

Every row of :data:`CPU_MAP_READS` addresses a **real register that exists in the
generated map**, by its own generated ``SMC_TOP_SMC_BASE_CONFIG_*_BASE_ADDR``
symbol, and expects that register's **generated RDL reset constant**, imported by
symbol from ``hw/sys/smc/regs/gen/c/blocks/smc_base_config.h`` -- never a hand
literal and never an address computed as ``BASE_ADDR + <offset>``. So every read
verifies decode *and* spec-defined reset content.

``SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR`` is ``0xC0010000`` and
``SMC_TOP_SMC_BASE_CONFIG_SIZE`` is ``0x0000004C``
(``hw/sys/smc/regs/gen/c/smc_addr.h:108-109``), so the window ends at
``0xC001004B``. Undecoded space above it reads back ``0x00000000``, so a row
that expected 0 there could not fail on any RTL while logging a register-shaped
name that names no register (``[ADDRESS-FROM-AUTHORITATIVE-MAP]``); every row
therefore addresses a register inside the window, and ``REGION_SIZE`` -- a real
register of the same block with a non-zero generated reset -- fails if the
fabric ever stops decoding it.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import _SMC_BASE_CFG_H, HANG_DET_IRQ_TEST, _field_mask, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq


def _base_config_reset(symbol: str) -> int:
    """RDL reset constant from generated ``blocks/smc_base_config.h``."""
    return _field_mask(_SMC_BASE_CFG_H, symbol)


# (name, address-by-generated-symbol, generated RDL reset constant).
# `csr_read` is a 32-bit access, so the 56-bit BASE fields are compared on their
# low word -- both reset constants fit in 32 bits.
CPU_MAP_READS = [
    (
        "GLOBAL_BASE",
        smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR"),
        _base_config_reset("SMC_BASE_CONFIG__GLOBAL_BASE__BASE_reset") & 0xFFFF_FFFF,
    ),
    (
        "LOCAL_BASE",
        smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR"),
        _base_config_reset("SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset") & 0xFFFF_FFFF,
    ),
    (
        "REGION_SIZE",
        smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR"),
        _base_config_reset("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset"),
    ),
    (
        "HANG_DET_DATA_ACCEL_CTRL",
        smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR"),
        (
            _base_config_reset("SMC_BASE_CONFIG__HANG_DET_CTRL__ENABLE_reset")
            | _base_config_reset("SMC_BASE_CONFIG__HANG_DET_CTRL__IRQ_EN_reset")
            | _base_config_reset("SMC_BASE_CONFIG__HANG_DET_CTRL__IRQ_TEST_reset")
        ),
    ),
    (
        "HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD",
        smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD_BASE_ADDR"),
        _base_config_reset("SMC_BASE_CONFIG__HANG_DET_TIMEOUT_THRESHOLD__VALUE_reset"),
    ),
]


class smc_cpu_ctrl_map_depth_test_seq(SmcCsrSeq):
    """Read the SMC_BASE_CONFIG map/hang-detector CSRs at their generated resets over SEP_IN."""

    def __init__(self, name: str = "smc_cpu_ctrl_map_depth_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()

    async def body(self) -> None:
        await self.csr_read_many(CPU_MAP_READS)
        # `accesses == len(...)` alone is loop integrity, not reachability: the
        # counter is bumped unconditionally by `csr_read` regardless of what the
        # DUT returned, so a mis-bound analysis path would leave the scoreboard
        # checking zero items while this sequence still passed
        # ([NO-ZERO-ACTIVITY-PASS]). `assert_all_reachable` adds the scoreboard
        # cross-check (`sys_axi_checks_seen >= accesses`) that carries the claim.

        # Positive control for the sweep above. Every row compares a reset value,
        # so a window that answered its reset word from a dead responder, or a
        # read path stuck at those constants, satisfies all of them. Writing a
        # non-reset value into one row and reading it back shows the window is
        # live, then the reset value is restored so the sweep's own compares are
        # unaffected.
        probe_addr = dict((n, a) for n, a, _e in CPU_MAP_READS)["HANG_DET_DATA_ACCEL_CTRL"]
        probe_reset = dict((n, e) for n, _a, e in CPU_MAP_READS)["HANG_DET_DATA_ACCEL_CTRL"]
        probe_val = probe_reset ^ HANG_DET_IRQ_TEST
        await self.csr_write("CPU_MAP_PROBE_WRITE", probe_addr, probe_val)
        await self.csr_read("CPU_MAP_PROBE_READBACK", probe_addr, expected=probe_val)
        await self.csr_write("CPU_MAP_PROBE_RESTORE", probe_addr, probe_reset)
        await self.csr_read("CPU_MAP_PROBE_RESTORE_RB", probe_addr, expected=probe_reset)
        cocotb.log.info(
            "CHK-CPU-CTRL-MAP-LIVE: HANG_DET_DATA_ACCEL_CTRL@0x%08x took "
            "0x%x and returned to its reset 0x%x, so the reset compares below "
            "are read from a live window",
            probe_addr,
            probe_val,
            probe_reset,
        )
        self.chk_seen.add("CHK-CPU-CTRL-MAP-LIVE")

        # LOCAL_BASE is a read-only field: the write completes and the readback
        # still carries the generated reset.
        local_base_addr = dict((n, a) for n, a, _e in CPU_MAP_READS)["LOCAL_BASE"]
        local_base_reset = dict((n, e) for n, _a, e in CPU_MAP_READS)["LOCAL_BASE"]
        await self.csr_write(
            "CPU_MAP_LOCAL_BASE_WRITE", local_base_addr, local_base_reset ^ 0x1000_0000
        )
        await self.csr_read(
            "CPU_MAP_LOCAL_BASE_READBACK", local_base_addr, expected=local_base_reset
        )
        cocotb.log.info(
            "CHK-CPU-CTRL-MAP-LOCAL-BASE-RO: LOCAL_BASE@0x%08x accepted a write of 0x%x and "
            "still reads its reset 0x%x",
            local_base_addr,
            local_base_reset ^ 0x1000_0000,
            local_base_reset,
        )
        self.chk_seen.add("CHK-CPU-CTRL-MAP-LOCAL-BASE-RO")

        self.assert_all_reachable(len(CPU_MAP_READS) + 6, "CPU_CTRL_MAP")
        # Conditional evidence for the map rows themselves: emitted only after
        # every row's exact reset compare has been enforced by the scoreboard
        # and the reachability cross-check above has passed.
        cocotb.log.info(
            "CHK-CPU-CTRL-MAP-DEPTH: %d SMC_BASE_CONFIG register(s) read over "
            "SEP_IN AXI, each addressed by its generated "
            "SMC_TOP_SMC_BASE_CONFIG_*_BASE_ADDR symbol and compared against its "
            "generated RDL reset: %s",
            len(CPU_MAP_READS),
            "; ".join(f"{name}@0x{addr:08x}==0x{exp:x}" for name, addr, exp in CPU_MAP_READS),
        )
        self.chk_seen.add("CHK-CPU-CTRL-MAP-DEPTH")
