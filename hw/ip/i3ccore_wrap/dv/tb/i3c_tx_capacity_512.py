# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Target-TX Capacity Limit Demonstration (DE evidence test)

Proves that a target response larger than the TTI TX data queue capacity can
NEVER be transmitted correctly, because `descriptor_tx.sv` gates transfer
start on the WHOLE payload being resident:

    // descriptor_tx.sv:105 (OCH line refs at 2026-07-03)
    tx_start = !tx_pending && descriptor_valid &&
               (tti_tx_queue_depth_i + 1 >= data_len_words);

With `TTI_TX_FIFO_DEPTH = 64` DWORDs (i3c_defines.svh) plus the one word held
in the Nto8 width converter, the largest startable response is 65 words =
260 bytes. For anything larger, `data_len_words > 65` and tx_start can never
assert -- even with a perfect streaming firmware that tops up the queue as
space frees (the gate compares against the FULL message length, so the queue
can never "catch up"). Meanwhile the bus FSM ACKs the controller's read as
soon as the TX DESCRIPTOR is visible (i3c_target_fsm gates the read-ACK on
tx_desc_avail, not on tx_start), so the read data phase runs with no valid
byte stream -> corrupted data instead of a clean NACK.

Four legs, identical flow, only the length changes:
  leg A: 256 bytes ( 64 words <= 65)  -> expect PASS   (control)
  leg B: 260 bytes ( 65 words == 65)  -> expect PASS   (exact capacity edge)
  leg C: 512 bytes (128 words  > 65)  -> expect PASS per spec; FAILED on the
         original RTL (first byte replayed x512 -- the bug evidence), PASSES
         with the OCH streaming fixes (descriptor_tx/i3c_target_fsm)
  leg D: 515 bytes (>capacity AND non-word-aligned) -> streaming path with a
         partial last word (byte_counter + Nto8 flush interaction)

All legs assert the spec-correct expectation (full-length, byte-exact data).
Do NOT weaken leg C to "expected failure" -- a FAIL here is the deliverable.

Related: chiplet-level smc_occp_undersize_body_test hit the small-response
flavor of the same ACK-before-tx_start hole (desc-first fw order, stale first
byte re-transmitted 7x on the bus); fw side is fixed by data-first ordering,
which works ONLY for <= 260 B. This test covers the > 260 B leg that no fw
ordering can fix. See I3C_TICKET_VERIFICATION_SUMMARY.md and
i3c_long_read_sanity (500 B, "Data mismatch" for the same root cause).
"""

import cocotb
import logging
from cocotb.triggers import RisingEdge, Timer, ClockCycles
from cocotbext.axi import AxiLiteBus, AxiLiteMaster

from i3c_api import (
    I3CHelper, I3CController, I3CTarget,
    I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR,
    PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
)

CTRL_BASE = 0x0000
TGT_BASE = 0x1000
TARGET_STATIC_ADDR = 0x10
TARGET_DYNAMIC_ADDR = 0x10

# TTI TX data queue capacity: TTI_TX_FIFO_DEPTH(=64 DWORD) + 1 word in the
# Nto8 converter = 65 words = 260 bytes (see module docstring).
QUEUE_WORDS = 64
STARTABLE_BYTES = (QUEUE_WORDS + 1) * 4          # 260

LEGS = [
    ("A_fits_256B", 256),              # < capacity   -> control, PASS
    ("B_edge_260B", STARTABLE_BYTES),  # == capacity  -> edge, PASS
    ("C_over_512B", 512),              # > capacity   -> exposes the gate
    ("D_over_515B", 515),              # > capacity AND non-word-aligned tail:
                                       # streaming + byte_counter + Nto8 partial-word
                                       # flush (descriptor_tx tx_queue_flush_o) combo
]


class TB:
    """Minimal testbench (same shape as i3c_write_read_sanity)."""

    def __init__(self, dut):
        self.dut = dut
        self.log = logging.getLogger("cocotb.tb")
        self.log.setLevel(logging.DEBUG)
        self.axi_master = None

    async def setup_axi_master(self):
        await Timer(100, units="ns")
        bus = AxiLiteBus.from_prefix(self.dut, "axi")
        self.axi_master = AxiLiteMaster(
            bus, self.dut.clk, self.dut.rst_n, reset_active_level=False
        )
        self.axi_master.write_if.log.setLevel(logging.ERROR)
        self.axi_master.read_if.log.setLevel(logging.ERROR)
        self.log.info("AXI-Lite master connected")

    async def wait_for_reset(self):
        while self.dut.rst_n.value == 0:
            await RisingEdge(self.dut.clk)
        await ClockCycles(self.dut.clk, 5)
        self.log.info("Reset released")


async def clear_leg_state(h, ctrl, tgt, log, tag):
    """W1C-clear sticky interrupt status on both sides between legs.

    private_read leaves TX_DESC_COMPLETE (and friends) set in the target's
    TTI INTERRUPT_STATUS; the next leg's main loop would break out on the
    STALE flag before transferring anything (observed: leg B "completed"
    400 ns after its descriptor write with 16/260 bytes written). The API
    never clears these, so the test does per-leg hygiene here.
    """
    tgt_st = await h.read(tgt.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)
    if tgt_st:
        await h.write(tgt.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR, tgt_st)
    ctrl_st = await h.read(ctrl.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR)
    if ctrl_st:
        await h.write(ctrl.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, ctrl_st)
    log.info(f"[{tag}] cleared sticky status: tgt=0x{tgt_st:08X} ctrl=0x{ctrl_st:08X}")


@cocotb.test(timeout_time=10000, timeout_unit='us')
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

    tb.log.info(f"Sending SETDASA (static=0x{TARGET_STATIC_ADDR:02X}, "
                f"dynamic=0x{TARGET_DYNAMIC_ADDR:02X})...")
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
        tb.log.info(f"[{name}] private read of {n} bytes "
                    f"({n // 4} words vs startable {QUEUE_WORDS + 1} words)")
        # Distinct per-leg pattern so stale bytes from a previous leg are
        # visible as such (leg index in the top 2 bits).
        tx_data = [((leg_idx << 6) | (i & 0x3F)) & 0xFF for i in range(n)]

        ok, resp, rx_data = await ctrl.private_read(tgt, tx_data)

        got = len(rx_data)
        match = (rx_data[:n] == tx_data) if got >= n else False
        first_bad = next((i for i in range(min(got, n))
                          if rx_data[i] != tx_data[i]), None)
        tb.log.info(f"[{name}] ok={ok} resp=0x{resp:08X} received={got}/{n} "
                    f"match={match} first_mismatch_idx={first_bad}")
        if not match and got:
            lo = 0 if first_bad is None else max(first_bad - 2, 0)
            tb.log.info(f"[{name}]   expected[{lo}:{lo + 8}]="
                        f"{[hex(b) for b in tx_data[lo:lo + 8]]}")
            tb.log.info(f"[{name}]   received[{lo}:{lo + 8}]="
                        f"{[hex(b) for b in rx_data[lo:lo + 8]]}")
        results[name] = (ok, got, match)

    tb.log.info("=" * 60)
    for name, (ok, got, match) in results.items():
        tb.log.info(f"  {name}: ok={ok} received={got} match={match}")
    tb.log.info("=" * 60)

    # Spec-correct expectation for EVERY leg: full-length, byte-exact data.
    # On current RTL leg C fails (tx_start can never fire for 128 words) --
    # that assertion failure is the evidence this test exists to produce.
    for name, n in LEGS:
        ok, got, match = results[name]
        assert ok, f"[{name}] read did not complete cleanly (got {got}/{n})"
        assert got >= n, f"[{name}] short read: {got}/{n} bytes"
        assert match, f"[{name}] data mismatch ({n} bytes)"

    tb.log.info("All legs byte-exact -- capacity gate not limiting (RTL fixed?)")
