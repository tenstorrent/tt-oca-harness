# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Local-fabric CSR depth sweep over real SEP_IN AXI."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    AXIL_MAILBOX_ERROR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
    LOG_ENGINE_CTRL_REG_DEFAULT,
    REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    REMAP_REGION_REGION_START_REG_DEFAULT,
    SMC_ALIAS_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
    SMC_ALIAS_REMAP_0__REGION_REGION_START_REG_ADDR,
    SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_ADDR,
    SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_DEFAULT,
    SMC_BASE_CONFIG_GLOBAL_BASE_REG_ADDR,
    SMC_BASE_CONFIG_GLOBAL_BASE_REG_DEFAULT,
    SMC_MAILBOX_OUTBOUND_MAILBOX_0_ERROR_FLAGS_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR,
    SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__LOG_ENGINE_CTRL_REG_ADDR,
    SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__UART_LOG_ENGINE_CTRL_CTRL_REG_ADDR,
    SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__UART_LSR_REG_ADDR,
    UART_16550_MAIN_LSR_REG_DEFAULT,
    UART_LOG_ENGINE_CTRL_CTRL_REG_DEFAULT,
    ZEROER_CTRL_DEST_ADDR_REG_ADDR,
    ZEROER_CTRL_DEST_ADDR_REG_DEFAULT,
    ZEROER_CTRL_SIZE_REG_ADDR,
    ZEROER_CTRL_SIZE_REG_DEFAULT,
)

# Local-fabric CSR windows backed by real register blocks. Addresses and
# expected values are imported from the generated PeakRDL map. Each read
# verifies decode + route AND the reset value, not merely an OKAY response.
# 64-bit RDL windows use length=8; 32-bit UART/log-engine windows use length=4.
# MAILBOX STATUS.empty is a live FIFO wire (RDL REG_DEFAULT 0x0 disagrees with
# empty-at-reset); this sweep samples ERROR_FLAGS instead (clean RDL reset).
# I3C HCI windows are covered by smc_i3c_to_fabric_test at 0xC000_5000.
# Tuple: (name, addr, expected, length)
LOCAL_FABRIC_READS = [
    (
        "SMC_BASE_CONFIG_GLOBAL_BASE",
        SMC_BASE_CONFIG_GLOBAL_BASE_REG_ADDR,
        SMC_BASE_CONFIG_GLOBAL_BASE_REG_DEFAULT,
        8,
    ),
    (
        "CLOCK_GATE_CONTROL",
        SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_ADDR,
        SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_DEFAULT,
        8,
    ),
    (
        "MAILBOX0_OUT_ERROR_FLAGS",
        SMC_MAILBOX_OUTBOUND_MAILBOX_0_ERROR_FLAGS_REG_ADDR,
        AXIL_MAILBOX_ERROR_REG_DEFAULT,
        8,
    ),
    (
        "ALIAS0_START",
        SMC_ALIAS_REMAP_0__REGION_REGION_START_REG_ADDR,
        REMAP_REGION_REGION_START_REG_DEFAULT,
        8,
    ),
    (
        "ALIAS0_ATTRS",
        SMC_ALIAS_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
        REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
        8,
    ),
    (
        "OUTBOUND0_FILTER_CONFIG",
        SMC_OUTBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
        FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
        8,
    ),
    (
        "OUTBOUND0_START",
        SMC_OUTBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR,
        FILTER_CTRL_START_ADDR_REG_DEFAULT,
        8,
    ),
    (
        "UART0_LOG_ENGINE_CTRL",
        SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__UART_LOG_ENGINE_CTRL_CTRL_REG_ADDR,
        UART_LOG_ENGINE_CTRL_CTRL_REG_DEFAULT,
        4,
    ),
    (
        "UART0_LSR",
        SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__UART_LSR_REG_ADDR,
        UART_16550_MAIN_LSR_REG_DEFAULT,
        4,
    ),
    (
        "LOG_ENGINE0_CTRL",
        SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__LOG_ENGINE_CTRL_REG_ADDR,
        LOG_ENGINE_CTRL_REG_DEFAULT,
        4,
    ),
    ("ZEROER_DEST_ADDR", ZEROER_CTRL_DEST_ADDR_REG_ADDR, ZEROER_CTRL_DEST_ADDR_REG_DEFAULT, 8),
    ("ZEROER_SIZE", ZEROER_CTRL_SIZE_REG_ADDR, ZEROER_CTRL_SIZE_REG_DEFAULT, 8),
]


# Independent floor: a literal, not computed from the table the body walks.
# Every entry of LOCAL_FABRIC_READS carries a non-null `expected`, so each read
# must book one scoreboard VALUE compare, not merely one access; other
# testcases' `covered_by_live` claims rest on this sweep.
LOCAL_FABRIC_MIN_VALUE_CHECKS = 12


class smc_local_fabric_csr_depth_test_seq(SmcCsrSeq):
    """Sample representative local-fabric CSR windows with one AXI ingress."""

    def __init__(self, name: str = "smc_local_fabric_csr_depth_test_seq") -> None:
        super().__init__(name)
        self.value_checks: int | None = None

    async def body(self) -> None:
        sb = self.env.scoreboard
        before = sb.sys_axi_value_checks_seen
        for name, addr, expected, length in LOCAL_FABRIC_READS:
            await self.csr_read(name, addr, expected, length=length)
        # Loop integrity PLUS the scoreboard cross-check: `self.accesses` on its
        # own is a counter this sequence bumps unconditionally and cannot see a
        # mis-bound analysis path ([NO-ZERO-ACTIVITY-PASS]).
        self.assert_all_reachable(len(LOCAL_FABRIC_READS), "local_fabric_csr")
        # SmcScoreboard._check_sys_axi books a value check only after an exact
        # rdata compare has PASSED, so an `expected` that went None, a partial
        # analysis-path loss, or an item-type change all land here instead of
        # passing silently.
        self.value_checks = sb.sys_axi_value_checks_seen - before
        assert self.value_checks >= LOCAL_FABRIC_MIN_VALUE_CHECKS, (
            f"local_fabric_csr: the scoreboard performed {self.value_checks} "
            f"exact value compare(s) for this sweep, expected at least "
            f"{LOCAL_FABRIC_MIN_VALUE_CHECKS} -- one per register in "
            f"{[entry[0] for entry in LOCAL_FABRIC_READS]}. An access-only sweep "
            f"proves decode, not register content"
        )
        cocotb.log.info(
            "CHK-LOCAL-FABRIC-CSR-DEPTH: %d local-fabric CSR windows read over "
            "SEP_IN AXI and %d of them value-compared against their generated "
            "RDL reset value by the scoreboard (delta measured across this "
            "sequence, so bring-up traffic cannot be counted toward the floor): "
            "%s",
            len(LOCAL_FABRIC_READS),
            self.value_checks,
            ", ".join(entry[0] for entry in LOCAL_FABRIC_READS),
        )
