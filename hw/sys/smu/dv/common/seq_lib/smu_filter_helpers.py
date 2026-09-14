# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYS_IN inbound0 filter program helpers (JTAG2AXI)."""

from __future__ import annotations

from typing import Any

from cocotb.triggers import ClockCycles

from seq_lib.smu_addr_map import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    filter_ctrl_bm,
    filter_ctrl_field_reset_encode,
    smc_addr,
)
from seq_lib.smu_axi_helpers import axi_read32_resp_bounded, resp_name
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    jtag2axi_single_read,
    jtag2axi_single_write,
    require_jtag_tdo_resolved,
)

# External SMN fabric window used by SMC SYS_OUT (not an SMC CSR address).
EXT_FABRIC_PROBE_ADDR = 0x8000_0000

# Compose from filter_ctrl.h *_bm (DATA_BUS_WIDTH reset encoding = 3 << bp).
_F_READ = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_F_WRITE = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_F_ENTRY = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_F_ALLOW_NS = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
_F_ALLOW_BURST = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
_F_BUS_WIDTH_64 = filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")

PASS_RW_CONFIG = _F_READ | _F_WRITE | _F_ENTRY | _F_ALLOW_NS | _F_BUS_WIDTH_64 | _F_ALLOW_BURST
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF

SMC_VERSION_LO_ADDR = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_EXPECT = SMC_CHIP_CONFIG_VERSION_LO_RESET
SCRATCH_COLD_ADDR = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
WDT_CTRL_ADDR = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR")

FILTER_READY_POLLS = 64
FILTER_READY_STEP = 4


# hw/ip/axi_filter/doc/index.adoc, "Address Range Granule": with
# allow_burst=1 the granule is 4 KB and address bits [11:0] are ignored;
# START_ADDR widens down and END_ADDR widens up to the granule, and the
# widened values are written back into START_ADDR/END_ADDR when both land in
# the same granule.
FILTER_BURST_GRANULE_BITS = 12
_FILTER_BURST_GRANULE_MASK = (1 << FILTER_BURST_GRANULE_BITS) - 1


def page_align_window(start: int, end: int) -> tuple[int, int]:
    """Effective allow_burst=1 range [granule base of start, granule top of end]."""
    start_a = int(start) & ~_FILTER_BURST_GRANULE_MASK
    return start_a, int(end) | _FILTER_BURST_GRANULE_MASK


async def program_inbound0_window(
    jtag,
    start: int,
    end: int,
    *,
    config: int = PASS_RW_CONFIG,
    scoreboard: Any = None,
    tag: str = "INBOUND0",
) -> None:
    """Program INBOUND0 START/END/CONFIG via JTAG2AXI; optional status checks."""
    for addr, data, name in (
        (INBOUND0_START, start, f"{tag}_START"),
        (INBOUND0_END, end, f"{tag}_END"),
        (INBOUND0_FILTER_CONFIG, config, f"{tag}_CONFIG"),
    ):
        st, _ = await jtag2axi_single_write(jtag, addr, data, require_complete=True)
        require_jtag_tdo_resolved(f"J2A WR {name}")
        if scoreboard is not None:
            scoreboard.expect_eq(f"JTAG2AXI {name} write", st, J2A_STATUS_SUCCESS)


async def clear_inbound0_config(jtag, *, scoreboard: Any = None) -> None:
    """Clear INBOUND0 CONFIG (restore BlockByDefault deny for unprogrammed)."""
    st, _ = await jtag2axi_single_write(jtag, INBOUND0_FILTER_CONFIG, 0, require_complete=True)
    require_jtag_tdo_resolved("J2A WR INBOUND0_CONFIG clear")
    if scoreboard is not None:
        scoreboard.expect_eq("JTAG2AXI INBOUND0_CONFIG clear", st, J2A_STATUS_SUCCESS)


async def program_outbound0_pass_all(jtag, *, scoreboard: Any = None) -> None:
    """Program OUTBOUND0 pass-all via JTAG2AXI (best-effort under SEP=0)."""
    for addr, data, name in (
        (OUTBOUND0_START, 0, "OUTBOUND0_START"),
        (OUTBOUND0_END, PASS_ALL_END, "OUTBOUND0_END"),
        (OUTBOUND0_FILTER_CONFIG, PASS_RW_CONFIG, "OUTBOUND0_CONFIG"),
    ):
        st, _ = await jtag2axi_single_write(jtag, addr, data, require_complete=True)
        require_jtag_tdo_resolved(f"J2A WR {name}")
        if scoreboard is not None:
            scoreboard.expect_eq(f"JTAG2AXI {name} write", st, J2A_STATUS_SUCCESS)


async def inbound0_config_readback(jtag) -> int:
    """Read INBOUND0 FILTER_CONFIG (32b)."""
    st, rdata = await jtag2axi_single_read(jtag, INBOUND0_FILTER_CONFIG, require_complete=True)
    require_jtag_tdo_resolved("J2A RD INBOUND0_CONFIG")
    if st != J2A_STATUS_SUCCESS:
        raise AssertionError(f"INBOUND0_CONFIG read status={st} want SUCCESS={J2A_STATUS_SUCCESS}")
    return int(rdata) & 0xFFFF_FFFF


async def await_smn_resp(
    master,
    addr: int,
    want,
    *,
    clk,
    label: str,
) -> tuple[int, object]:
    """Poll SMN until ``want`` resp; fail-closed with last-state."""
    last = None
    last_data = None
    for poll in range(FILTER_READY_POLLS):
        val, resp = await axi_read32_resp_bounded(master, addr, label=label)
        last, last_data = resp, val
        if resp == want:
            return val, resp
        await ClockCycles(clk, FILTER_READY_STEP)
    raise AssertionError(
        f"TIMEOUT FILTER_READY {label}: want={resp_name(want)} "
        f"last={resp_name(last) if last is not None else None} "
        f"data={last_data!r} polls={FILTER_READY_POLLS} "
        f"step={FILTER_READY_STEP} addr=0x{addr:08x}"
    )
