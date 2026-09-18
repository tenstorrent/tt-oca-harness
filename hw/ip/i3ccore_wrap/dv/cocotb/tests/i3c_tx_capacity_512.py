# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Target-TX Capacity Test

Transfer start requires the complete response to fit in the 64-word TX queue
plus the width converter's pending word. The test checks the 256-byte control
case, the 260-byte boundary, and larger word-aligned and unaligned responses.
Every response must complete with its full byte-exact payload.
"""

import logging

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotbext.axi import AxiLiteBus, AxiLiteMaster
from env.i3c_api import (
    I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR,
    PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
    I3CController,
    I3CHelper,
    I3CTarget,
)

CTRL_BASE = 0x0000
TGT_BASE = 0x1000
TARGET_STATIC_ADDR = 0x10
TARGET_DYNAMIC_ADDR = 0x10

# TTI TX data queue capacity: TTI_TX_FIFO_DEPTH(=64 DWORD) + 1 word in the
# Nto8 converter = 65 words = 260 bytes (see module docstring).
QUEUE_WORDS = 64
STARTABLE_BYTES = (QUEUE_WORDS + 1) * 4  # 260

LEGS = [
    ("A_fits_256B", 256),  # < capacity   -> control, PASS
    ("B_edge_260B", STARTABLE_BYTES),  # == capacity  -> edge, PASS
    ("C_over_512B", 512),  # > capacity   -> exposes the gate
    ("D_over_515B", 515),  # > capacity AND non-word-aligned tail:
    # streaming + byte_counter + Nto8 partial-word
    # flush (descriptor_tx tx_queue_flush_o) combo
]


class TB:
    """AXI-Lite testbench wrapper for the target-TX capacity test."""

    def __init__(self, dut):
        self.dut = dut
        self.log = logging.getLogger("cocotb.tb")
        self.log.setLevel(logging.DEBUG)
        self.axi_master = None

    async def setup_axi_master(self):
        await Timer(100, units="ns")
        bus = AxiLiteBus.from_prefix(self.dut, "axi")
        self.axi_master = AxiLiteMaster(bus, self.dut.clk, self.dut.rst_n, reset_active_level=False)
        self.axi_master.write_if.log.setLevel(logging.ERROR)
        self.axi_master.read_if.log.setLevel(logging.ERROR)
        self.log.info("AXI-Lite master connected")

    async def wait_for_reset(self):
        while self.dut.rst_n.value == 0:
            await RisingEdge(self.dut.clk)
        await ClockCycles(self.dut.clk, 5)
        self.log.info("Reset released")


async def clear_leg_state(h, ctrl, tgt, log, tag):
    """Clear sticky controller and target interrupt status between legs.

    Uncleared completion status can terminate the next leg before it transfers
    data.
    """
    tgt_st = await h.read(tgt.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)
    if tgt_st:
        await h.write(tgt.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR, tgt_st)
    ctrl_st = await h.read(ctrl.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR)
    if ctrl_st:
        await h.write(ctrl.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, ctrl_st)
    log.info(f"[{tag}] cleared sticky status: tgt=0x{tgt_st:08X} ctrl=0x{ctrl_st:08X}")


@cocotb.test(timeout_time=10000, timeout_unit="us")
async def test_tx_capacity_512(dut):
    """Target-TX response size sweep across the tx_start capacity gate."""
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info("I3C Target-TX Capacity Limit Test (256 / 260 / 512 bytes)")
    tb.log.info("=" * 60)

    await Timer(500, units="ns")
    await tb.setup_axi_master()
    await tb.wait_for_reset()

    helper = I3CHelper(tb.axi_master, dut, tb.log)
    ctrl = I3CController(CTRL_BASE, helper)
    tgt = I3CTarget(TGT_BASE, helper)

    tb.log.info("Initializing controller...")
    await ctrl.initialize()
    await ctrl.configure_timing_od_i3c()
    await ctrl.configure_timing_pp()
    await ctrl.configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0)

    tb.log.info("Initializing target...")
    await tgt.initialize(TARGET_STATIC_ADDR)
    await tgt.configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0)

    tb.log.info(
        f"Sending SETDASA (static=0x{TARGET_STATIC_ADDR:02X}, "
        f"dynamic=0x{TARGET_DYNAMIC_ADDR:02X})..."
    )
    ok, resp = await ctrl.send_setdasa(TARGET_STATIC_ADDR, TARGET_DYNAMIC_ADDR)
    tb.log.info(f"  Response: 0x{resp:08X}, success={ok}")
    assert ok, f"SETDASA failed with response 0x{resp:08X}"

    ok, dyn_addr = await tgt.wait_dynamic_addr()
    assert ok and dyn_addr == TARGET_DYNAMIC_ADDR, "Target did not take dynamic address"

    # Allow reads up to the largest leg (SETMRL caps the target's read length).
    max_len = max(n for _, n in LEGS)
    ok, resp = await ctrl.setmrl(max_len, ibi_payload_size=0xFF, dat_idx=0)
    tb.log.info(f"SETMRL({max_len}) response: 0x{resp:08X}, success={ok}")
    assert ok, f"SETMRL failed with response 0x{resp:08X}"

    results = {}
    for leg_idx, (name, n) in enumerate(LEGS, start=1):
        tb.log.info("-" * 60)
        await clear_leg_state(helper, ctrl, tgt, tb.log, name)
        tb.log.info(
            f"[{name}] private read of {n} bytes "
            f"({n // 4} words vs startable {QUEUE_WORDS + 1} words)"
        )
        # Distinct per-leg pattern so stale bytes from a previous leg are
        # visible as such (leg index in the top 2 bits).
        tx_data = [((leg_idx << 6) | (i & 0x3F)) & 0xFF for i in range(n)]

        ok, resp, rx_data = await ctrl.private_read(tgt, tx_data)

        got = len(rx_data)
        match = (rx_data[:n] == tx_data) if got >= n else False
        first_bad = next((i for i in range(min(got, n)) if rx_data[i] != tx_data[i]), None)
        tb.log.info(
            f"[{name}] ok={ok} resp=0x{resp:08X} received={got}/{n} "
            f"match={match} first_mismatch_idx={first_bad}"
        )
        if not match and got:
            lo = 0 if first_bad is None else max(first_bad - 2, 0)
            tb.log.info(
                f"[{name}]   expected[{lo}:{lo + 8}]={[hex(b) for b in tx_data[lo : lo + 8]]}"
            )
            tb.log.info(
                f"[{name}]   received[{lo}:{lo + 8}]={[hex(b) for b in rx_data[lo : lo + 8]]}"
            )
        results[name] = (ok, got, match)

    tb.log.info("=" * 60)
    for name, (ok, got, match) in results.items():
        tb.log.info(f"  {name}: ok={ok} received={got} match={match}")
    tb.log.info("=" * 60)

    # Every leg must complete with its full byte-exact payload.
    for name, n in LEGS:
        ok, got, match = results[name]
        assert ok, f"[{name}] read did not complete cleanly (got {got}/{n})"
        assert got >= n, f"[{name}] short read: {got}/{n} bytes"
        assert match, f"[{name}] data mismatch ({n} bytes)"

    tb.log.info("All legs byte-exact: every response completed at its full length")
