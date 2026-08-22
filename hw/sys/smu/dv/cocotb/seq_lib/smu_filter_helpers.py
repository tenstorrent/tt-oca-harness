# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYS_IN inbound0 filter program helpers (JTAG2AXI)."""

from __future__ import annotations

from typing import Any

from seq_lib.smu_jtag_helpers import J2A_STATUS_SUCCESS, jtag2axi_single_write

INBOUND0_FILTER_CONFIG = 0xC001_5000
INBOUND0_START = 0xC001_5008
INBOUND0_END = 0xC001_5010
OUTBOUND0_FILTER_CONFIG = 0xC001_6000
OUTBOUND0_START = 0xC001_6008
OUTBOUND0_END = 0xC001_6010
# External SMN fabric window used by SMC SYS_OUT (not an SMC CSR address).
EXT_FABRIC_PROBE_ADDR = 0x8000_0000
# READ+WRITE + ADDR_MODE + ALLOW_NS + bus-width/src encodings (P1/P2).
PASS_RW_CONFIG = 0x0100_3113
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF

SMC_VERSION_LO_ADDR = 0xC000_2900
VERSION_LO_EXPECT = 0x0001_00A0
SCRATCH_COLD_ADDR = 0xC000_2800
WDT_CTRL_ADDR = 0xC000_0000


def page_align_window(start: int, end: int) -> tuple[int, int]:
    """Match axi_filter_wrap page expansion when start/end share [55:12]."""
    start_a = int(start) & ~0xFFF
    # Same-page programming expands to full page in HW.
    if (int(start) & ~0xFFF) == (int(end) & ~0xFFF):
        return start_a, start_a | 0xFFF
    return start_a, int(end) | 0xFFF


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
        st, _ = await jtag2axi_single_write(jtag, addr, data)
        if scoreboard is not None:
            scoreboard.expect_eq(f"JTAG2AXI {name} write", st, J2A_STATUS_SUCCESS)


async def clear_inbound0_config(jtag, *, scoreboard: Any = None) -> None:
    """Clear INBOUND0 CONFIG (restore BlockByDefault deny for unprogrammed)."""
    st, _ = await jtag2axi_single_write(jtag, INBOUND0_FILTER_CONFIG, 0)
    if scoreboard is not None:
        scoreboard.expect_eq("JTAG2AXI INBOUND0_CONFIG clear", st, J2A_STATUS_SUCCESS)


async def program_outbound0_pass_all(jtag, *, scoreboard: Any = None) -> None:
    """Program OUTBOUND0 pass-all via JTAG2AXI (best-effort under SEP=0)."""
    for addr, data, name in (
        (OUTBOUND0_START, 0, "OUTBOUND0_START"),
        (OUTBOUND0_END, PASS_ALL_END, "OUTBOUND0_END"),
        (OUTBOUND0_FILTER_CONFIG, PASS_RW_CONFIG, "OUTBOUND0_CONFIG"),
    ):
        st, _ = await jtag2axi_single_write(jtag, addr, data)
        if scoreboard is not None:
            scoreboard.expect_eq(f"JTAG2AXI {name} write", st, J2A_STATUS_SUCCESS)
