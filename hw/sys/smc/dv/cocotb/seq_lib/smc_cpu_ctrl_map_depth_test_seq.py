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

There is deliberately no row addressing ``0xC001_0050``. It is not
"reserved/open-bus space within the block window":
``SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR``
is ``0xC0010000`` and ``SMC_TOP_SMC_BASE_CONFIG_SIZE`` is ``0x0000004C``
(``hw/sys/smc/regs/gen/c/smc_addr.h:108-109``), so the window ends at
``0xC001004B`` and ``0xC0010050`` is outside it. Undecoded space reads back
``0x00000000``, which is exactly what the row expected, so it could not fail on
any RTL while logging a register-shaped name that names no register
(``[ADDRESS-FROM-AUTHORITATIVE-MAP]``). It is replaced here by ``REGION_SIZE``,
a real register of the same block with a non-zero generated reset -- more decode
coverage, not less, and a row that fails if the fabric ever stops decoding it.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import _SMC_BASE_CFG_H, _field_mask, smc_addr
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
        smc_addr(
            "SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD_BASE_ADDR"
        ),
        _base_config_reset(
            "SMC_BASE_CONFIG__HANG_DET_TIMEOUT_THRESHOLD__VALUE_reset"
        ),
    ),
]


class smc_cpu_ctrl_map_depth_test_seq(SmcCsrSeq):
    """Cover SMC_BASE_CONFIG map/hang-detector CSRs until firmware traffic is public."""

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
        self.assert_all_reachable(len(CPU_MAP_READS), "CPU_CTRL_MAP")
        # Conditional evidence for the map rows themselves: emitted only after
        # every row's exact reset compare has been enforced by the scoreboard
        # and the reachability cross-check above has passed.
        cocotb.log.info(
            "CHK-CPU-CTRL-MAP-DEPTH: %d SMC_BASE_CONFIG register(s) read over "
            "SEP_IN AXI, each addressed by its generated "
            "SMC_TOP_SMC_BASE_CONFIG_*_BASE_ADDR symbol and compared against its "
            "generated RDL reset: %s",
            len(CPU_MAP_READS),
            "; ".join(
                f"{name}@0x{addr:08x}==0x{exp:x}" for name, addr, exp in CPU_MAP_READS
            ),
        )
        self.chk_seen.add("CHK-CPU-CTRL-MAP-DEPTH")
