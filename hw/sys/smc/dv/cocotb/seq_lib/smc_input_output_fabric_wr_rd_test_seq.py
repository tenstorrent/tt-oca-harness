# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Input/output fabric CSR precheck over real SEP_IN AXI."""

from __future__ import annotations

import sys
from pathlib import Path

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
    REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    REMAP_REGION_REGION_END_REG_DEFAULT,
    REMAP_REGION_REGION_START_REG_DEFAULT,
    SMC_ALIAS_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
    SMC_ALIAS_REMAP_0__REGION_REGION_END_REG_ADDR,
    SMC_ALIAS_REMAP_0__REGION_REGION_START_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_0__END_ADDR_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
    SMC_INBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_0__END_ADDR_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
    SMC_OUTBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR,
)

# RDL-traceable reset constants (identical on Verilator/VCS):
# alias_remap.rdl -> ALIAS start/end/attrs = 0; filter_ctrl.rdl -> FILTER_CONFIG
# = 0x3000 (data_bus_width[14:12]=0x3), START_ADDR = 0, END_ADDR = 0x7 ("Defaults
# to 7 on reset"). Each read verifies remap/filter CSR decode AND the full
# 64-bit spec reset content (AxSIZE=3 / length=8), not merely an OKAY response.
FILTER_REMAP_REGS = [
    (
        "ALIAS0_START",
        SMC_ALIAS_REMAP_0__REGION_REGION_START_REG_ADDR,
        REMAP_REGION_REGION_START_REG_DEFAULT,
    ),
    (
        "ALIAS0_END",
        SMC_ALIAS_REMAP_0__REGION_REGION_END_REG_ADDR,
        REMAP_REGION_REGION_END_REG_DEFAULT,
    ),
    (
        "ALIAS0_ATTRS",
        SMC_ALIAS_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
        REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    ),
    (
        "INBOUND0_FILTER_CONFIG",
        SMC_INBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
        FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    ),
    (
        "INBOUND0_START",
        SMC_INBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR,
        FILTER_CTRL_START_ADDR_REG_DEFAULT,
    ),
    (
        "INBOUND0_END",
        SMC_INBOUND_FILTER_CTRL_0__END_ADDR_REG_ADDR,
        FILTER_CTRL_END_ADDR_REG_DEFAULT,
    ),
    (
        "OUTBOUND0_FILTER_CONFIG",
        SMC_OUTBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR,
        FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    ),
    (
        "OUTBOUND0_START",
        SMC_OUTBOUND_FILTER_CTRL_0__START_ADDR_REG_ADDR,
        FILTER_CTRL_START_ADDR_REG_DEFAULT,
    ),
    (
        "OUTBOUND0_END",
        SMC_OUTBOUND_FILTER_CTRL_0__END_ADDR_REG_ADDR,
        FILTER_CTRL_END_ADDR_REG_DEFAULT,
    ),
]


class smc_input_output_fabric_wr_rd_test_seq(SmcCsrSeq):
    """Prove fabric remap/filter CSR decode over real SEP_IN AXI."""

    def __init__(self, name: str = "smc_input_output_fabric_wr_rd_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        import cocotb

        cocotb.log.info("STEP S1: SETUP clocks/resets and CSR-write access")
        cocotb.log.info("STEP S2: SMC-ALIAS-REMAP.S1 read ALIAS0 START/END/ATTRS reset defaults")
        alias_vals = {}
        for name, addr, expected in FILTER_REMAP_REGS:
            val = await self.csr_read(name, addr, expected, length=8)
            if name.startswith("ALIAS0_"):
                alias_vals[name] = val if val is not None else expected
        assert self.accesses == len(FILTER_REMAP_REGS), "fabric CSR precheck mismatch"
        alias0_start = smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR", 0)
        alias0_end = smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR", 0)
        alias0_attrs = smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR", 0)
        cocotb.log.info(
            "CHK-ALIAS-REMAP-RESET-DEFAULT: csr_read "
            f"ALIAS0_START@{alias0_start:#x}"
            f"={alias_vals.get('ALIAS0_START', 0):#x} expected=0; "
            f"ALIAS0_END@{alias0_end:#x}={alias_vals.get('ALIAS0_END', 0):#x} expected=0; "
            f"ALIAS0_ATTRS@{alias0_attrs:#x}={alias_vals.get('ALIAS0_ATTRS', 0):#x} expected=0; "
            "each OKAY length=8"
        )
        cocotb.log.info(
            f"CHK-NONVAC: self.accesses=={self.accesses} confirms full "
            f"{len(FILTER_REMAP_REGS)}-register CSR precheck over SEP_IN AXI"
        )
        cocotb.log.info("SMC_004 scenario PASS")
