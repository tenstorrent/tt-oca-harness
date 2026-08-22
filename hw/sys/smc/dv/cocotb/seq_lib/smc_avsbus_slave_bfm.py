# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Minimal AVSBus slave ACK BFM on ``tb_avs_sdata_ext`` (pad 51).

Timing matches ``avsbus_controller.sv``:
  * DUT samples sdata on avs_clk **negedge** (non-IDLE states)
  * BFM updates on avs_clk **posedge** (MSB-first)
  * Sync to master preamble (mdata falling to 0)
  * Idle through SHIFT_1ST+END_1ST (32 capture cycles), ACK in SHIFT_LAST+END_LAST

Fixed write ACK frame ``0x00FFFF06`` (CRC from ``avsbus_crc3.sv``).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge, Timer

AVS_WRITE_ACK_FRAME = 0x00FFFF06


def avs_crc3(msg: int) -> int:
    """Compute CRC3 with bits [2:0] treated as zero (generate path)."""
    i = msg & ~0x7

    def b(k: int) -> int:
        return (i >> k) & 1

    c2 = (
        b(30) ^ b(27) ^ b(26) ^ b(25) ^ b(23) ^ b(20) ^ b(19) ^ b(18)
        ^ b(16) ^ b(13) ^ b(12) ^ b(11) ^ b(9) ^ b(6) ^ b(5) ^ b(4) ^ b(2)
    )
    c1 = (
        b(31) ^ b(29) ^ b(26) ^ b(25) ^ b(24) ^ b(22) ^ b(19) ^ b(18)
        ^ b(17) ^ b(15) ^ b(12) ^ b(11) ^ b(10) ^ b(8) ^ b(5) ^ b(4)
        ^ b(3) ^ b(1)
    )
    c0 = (
        b(31) ^ b(28) ^ b(27) ^ b(26) ^ b(24) ^ b(21) ^ b(20) ^ b(19)
        ^ b(17) ^ b(14) ^ b(13) ^ b(12) ^ b(10) ^ b(7) ^ b(6) ^ b(5)
        ^ b(3) ^ b(0)
    )
    return ((c2 & 1) << 2) | ((c1 & 1) << 1) | (c0 & 1)


def make_write_ack_frame(
    ack: int = 0b00,
    status: int = 0,
    data: int = 0xFFFF,
) -> int:
    body = (
        ((ack & 0x3) << 30)
        | (0 << 29)
        | ((status & 0x1F) << 24)
        | ((data & 0xFFFF) << 8)
    )
    return body | avs_crc3(body)


async def _wait_mdata_preamble(dut, timeout_ns: int = 500_000) -> None:
    """Wait for master preamble: rising avs_clk with mdata==0."""
    clk = dut.tb_avs_clk_from_dut
    mdata = dut.tb_avs_mdata_from_dut
    elapsed = 0
    while elapsed < timeout_ns:
        await RisingEdge(clk)
        if mdata.value.is_resolvable and int(mdata.value) == 0:
            return
        elapsed += 1  # cycle count proxy; avs_clk period unknown
        if elapsed > 20000:
            break
    raise AssertionError("AVS mdata preamble (0) never observed on pad50")


async def drive_write_ack(
    dut,
    frame: int = AVS_WRITE_ACK_FRAME,
    first_window_cycles: int = 30,
) -> None:
    """Drive ACK in the second capture window after mdata preamble.

    ``first_window_cycles=30`` was measured on VCS: IDLE launch already
    presents preamble bit31, then 30 idle edges before the ACK window
    yields ``AVS_LATEST==0x00FFFF06``.
    """
    assert hasattr(dut, "tb_avs_sdata_ext"), "tb_avs_sdata_ext port missing"
    dut.tb_avs_sdata_ext.value = 1

    await _wait_mdata_preamble(dut)
    for _ in range(first_window_cycles):
        await RisingEdge(dut.tb_avs_clk_from_dut)
        dut.tb_avs_sdata_ext.value = 1

    for i in range(31, -1, -1):
        await RisingEdge(dut.tb_avs_clk_from_dut)
        dut.tb_avs_sdata_ext.value = (frame >> i) & 1

    await RisingEdge(dut.tb_avs_clk_from_dut)
    dut.tb_avs_sdata_ext.value = 1
    cocotb.log.info(
        "AVSBus slave ACK BFM done: frame=0x%08X (idle_window=%d)",
        frame,
        first_window_cycles,
    )


def start_write_ack_bfm(dut, frame: int = AVS_WRITE_ACK_FRAME):
    return cocotb.start_soon(drive_write_ack(dut, frame=frame))


__all__ = [
    "AVS_WRITE_ACK_FRAME",
    "avs_crc3",
    "drive_write_ack",
    "make_write_ack_frame",
    "start_write_ack_bfm",
]
