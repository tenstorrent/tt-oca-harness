# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Port mode switching between wire-OR and point-to-point.

The point-to-point pads sit behind a pad model: each of CT_Req_in and
CT_Ack_in presents the far end's level while its input enable is high and 0
while it is low, the level a GPIO pad cell reads with its input disabled.

Scenarios (expectations from the architecture spec's sender state machine
table and the CONFIG register description):

1. Wire-OR trigger, then point-to-point — a ct_src pulse sent in wire-OR
   mode leaves no request behind: CT_Req_out stays deasserted after MODE
   selects point-to-point, and a later handshake completes normally.
2. MODE and RESET in one write — selecting point-to-point with CONFIG.RESET
   set in the same write drives no request, not even for one cycle.
3. MODE and INVERT in one write — selecting active-low point-to-point
   against an idle far end raises no ct_dst pulse and no CT_Ack_out, and a
   later inverted request is received normally.
4. Point-to-point to wire-OR mid-handshake — leaving point-to-point with a
   request outstanding releases it, and returning to point-to-point drives
   no request until ct_src asks for one.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge
from ctp_base_test import (
    GPIO_SYNC_LATENCY,
    CtpTb,
    current_cycle,
)

# Cycles watched across a CONFIG write: the AXI-Lite write itself, the pad
# register, the synchronizers, and the handshake step, with margin.
SWITCH_WATCH_CYCLES = 6 * GPIO_SYNC_LATENCY


class P2pPadModel:
    """Far-end levels on CT_Req_in and CT_Ack_in, gated by the pad input enables."""

    def __init__(self, tb: CtpTb) -> None:
        self._tb = tb
        self.req_in = 0
        self.ack_in = 0
        self._task = None

    def start(self) -> None:
        if self._task is None:
            self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        dut = self._tb.dut
        while True:
            await FallingEdge(dut.clk)
            dut.ct_req_in_din.value = self.req_in if int(dut.ct_req_in_din_en.value) else 0
            dut.ct_ack_in_din.value = self.ack_in if int(dut.ct_ack_in_din_en.value) else 0


def _pad_asserted(dout_en, dout, invert: int) -> bool:
    return int(dout_en.value) == 1 and int(dout.value) == (1 ^ invert)


async def _watch_asserted(tb: CtpTb, invert: int, cycles: int) -> dict[str, list[int]]:
    """Record the cycles in which CT_Req_out or CT_Ack_out is driven asserted."""
    dut = tb.dut
    seen: dict[str, list[int]] = {"req_out": [], "ack_out": []}
    for _ in range(cycles):
        await FallingEdge(dut.clk)
        if _pad_asserted(dut.ct_req_out_dout_en, dut.ct_req_out_dout, invert):
            seen["req_out"].append(current_cycle())
        if _pad_asserted(dut.ct_ack_out_dout_en, dut.ct_ack_out_dout, invert):
            seen["ack_out"].append(current_cycle())
    return seen


async def _write_config_watched(
    tb: CtpTb, *, mode: int, invert: int = 0, reset: int = 0
) -> dict[str, list[int]]:
    """Write CONFIG while recording asserted pad outputs in the new sense."""
    watcher = cocotb.start_soon(_watch_asserted(tb, invert, SWITCH_WATCH_CYCLES))
    await tb.write_config(mode=mode, invert=invert, reset=reset)
    return await watcher


async def _expect_idle(tb: CtpTb, what: str) -> None:
    await tb.wait_level(tb.dut.busy, 0, GPIO_SYNC_LATENCY * 2, f"{what}: idle")
    status = await tb.read_status()
    assert status["req_out"] == 0 and status["busy"] == 0, (
        f"{what}: STATUS must show an idle sender "
        f"(req_out={status['req_out']} busy={status['busy']})"
    )


async def _sender_handshake(tb: CtpTb, pads: P2pPadModel, invert: int, what: str) -> None:
    """Complete one outgoing four-phase exchange with the far end."""
    dut = tb.dut
    await tb.pulse_ct_src()
    await tb.wait_level(dut.ct_req_out_dout, 1 ^ invert, GPIO_SYNC_LATENCY, f"{what}: REQ assert")
    pads.ack_in = 1 ^ invert
    await tb.wait_level(dut.ct_req_out_dout, invert, GPIO_SYNC_LATENCY * 2, f"{what}: REQ release")
    pads.ack_in = invert
    await _expect_idle(tb, what)


@cocotb.test()
async def ctp_mode_switch_test(dut) -> None:
    tb = CtpTb(dut, name="ctp_mode_switch_test")
    await tb.start()
    pads = P2pPadModel(tb)
    pads.start()
    tb.start_ct_dst_watcher()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: wire-OR trigger, then point-to-point")
    tb.log.info("=" * 70)
    await tb.write_config(mode=0)
    await tb.settle()
    await tb.pulse_ct_src()
    await tb.settle()
    seen = await _write_config_watched(tb, mode=1)
    assert not seen["req_out"], (
        "wire-OR trigger: CT_Req_out asserted after MODE selected point-to-point "
        f"with no ct_src pulse, in cycles {seen['req_out']}"
    )
    await _expect_idle(tb, "wire-OR trigger")
    await _sender_handshake(tb, pads, 0, "wire-OR trigger: later handshake")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: MODE and RESET in one write")
    tb.log.info("=" * 70)
    await tb.write_config(mode=0)
    await tb.settle()
    await tb.pulse_ct_src()
    await tb.settle()
    seen = await _write_config_watched(tb, mode=1, reset=1)
    assert not seen["req_out"], f"MODE+RESET write: CT_Req_out asserted in cycles {seen['req_out']}"
    await tb.write_config(mode=1)
    await _expect_idle(tb, "MODE+RESET write")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: MODE and INVERT in one write, active-low far end idle")
    tb.log.info("=" * 70)
    await tb.write_config(mode=0)
    pads.req_in = 1
    pads.ack_in = 1
    await tb.settle()
    before = tb.ct_dst_pulses()
    seen = await _write_config_watched(tb, mode=1, invert=1)
    received = tb.ct_dst_pulses() - before
    assert received == 0, f"MODE+INVERT write: {received} ct_dst pulse(s) with the far end idle"
    assert not seen["ack_out"], (
        f"MODE+INVERT write: CT_Ack_out asserted in cycles {seen['ack_out']} with the far end idle"
    )
    assert not seen["req_out"], (
        f"MODE+INVERT write: CT_Req_out asserted in cycles {seen['req_out']}"
    )
    await _expect_idle(tb, "MODE+INVERT write")

    before = tb.ct_dst_pulses()
    pads.req_in = 0
    await tb.wait_level(dut.ct_dst, 1, GPIO_SYNC_LATENCY, "MODE+INVERT write: ct_dst pulse")
    await tb.wait_level(dut.ct_ack_out_dout, 0, GPIO_SYNC_LATENCY, "MODE+INVERT write: ACK")
    pads.req_in = 1
    await tb.wait_level(dut.ct_ack_out_dout, 1, GPIO_SYNC_LATENCY, "MODE+INVERT write: ACK release")
    await tb.wait_level(dut.busy, 0, GPIO_SYNC_LATENCY, "MODE+INVERT write: receiver idle")
    received = tb.ct_dst_pulses() - before
    assert received == 1, f"MODE+INVERT write: expected 1 ct_dst pulse, observed {received}"

    await tb.write_config(mode=0)
    pads.req_in = 0
    pads.ack_in = 0
    await tb.settle()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: point-to-point to wire-OR mid-handshake")
    tb.log.info("=" * 70)
    await tb.write_config(mode=1)
    await tb.settle()
    await tb.pulse_ct_src()
    await tb.wait_level(dut.ct_req_out_dout, 1, GPIO_SYNC_LATENCY, "mid-handshake: REQ assert")
    await tb.write_config(mode=0)
    await tb.settle()
    await _expect_idle(tb, "mid-handshake: wire-OR")
    seen = await _write_config_watched(tb, mode=1)
    assert not seen["req_out"], (
        "mid-handshake: CT_Req_out asserted on returning to point-to-point "
        f"in cycles {seen['req_out']}"
    )
    await ClockCycles(dut.clk, GPIO_SYNC_LATENCY)
    await _expect_idle(tb, "mid-handshake: point-to-point")
    await _sender_handshake(tb, pads, 0, "mid-handshake: later handshake")

    await tb.write_config(mode=0)
    await tb.settle()
    tb.log.info("ctp_mode_switch_test PASSED")
