# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Port point-to-point mode: handshake FSMs, recovery, inversion.

Scenarios (expectations from the architecture spec's sender/receiver state
machine tables and the interface signal table):

1. Pad enable matrix — P2P drives CT_Req_out/CT_Ack_out and listens on
   CT_Req_in/CT_Ack_in; the shared-wire input is disabled.
2. Sender handshake — ct_src asserts CT_Req_out, which holds until CT_Ack_in
   asserts; BUSY covers the whole four-phase exchange, releasing only after
   CT_Ack_in deasserts.
3. Receiver handshake — a CT_Req_in rising edge produces one single-cycle
   ct_dst pulse and asserts CT_Ack_out until CT_Req_in deasserts.
4. Full duplex — the sender and receiver state machines run independently.
5. Deadlock recovery — CONFIG.RESET force-clears a stuck request and the
   port completes a normal handshake afterwards.
6. INVERT sense — with CONFIG.INVERT=1 the pad data pins idle high and
   assert low while the STATUS readouts keep the logical sense.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge
from ctp_base_test import (
    GPIO_SYNC_LATENCY,
    CtpTb,
    random_seed,
)

N_HANDSHAKE_ITER = 16


async def _check_stable(tb, signal, level: int, cycles: int, what: str) -> None:
    """Require ``signal`` to hold ``level`` for ``cycles`` falling edges."""
    for cycle in range(cycles):
        await FallingEdge(tb.dut.clk)
        observed = int(signal.value)
        assert observed == level, (
            f"{what}: expected stable level {level}, observed {observed} after {cycle} cycles"
        )


@cocotb.test()
async def ctp_p2p_test(dut) -> None:
    tb = CtpTb(dut, name="ctp_p2p_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()
    tb.start_ct_dst_watcher()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: pad enable matrix in point-to-point mode")
    tb.log.info("=" * 70)
    await tb.write_config(mode=1)
    await tb.settle()
    tb.check_pad_enables("p2p")
    dout = int(dut.ct_req_out_dout.value)
    assert dout == 0, f"P2P idle: CT_Req_out data expected 0 (INVERT=0), observed {dout}"

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: sender handshake (%d randomized iterations)", N_HANDSHAKE_ITER)
    tb.log.info("=" * 70)
    for index in range(N_HANDSHAKE_ITER):
        hold = random.randrange(2, 21)
        tb.log.info("iter %d: pulse ct_src, hold un-acked for %d cycles", index, hold)
        await tb.pulse_ct_src()
        await tb.wait_level(
            dut.ct_req_out_dout, 1, GPIO_SYNC_LATENCY, f"sender iter {index}: REQ assert"
        )
        # Spec sender FSM: the request holds until CT_Ack_in asserts.
        await _check_stable(
            tb, dut.ct_req_out_dout, 1, hold, f"sender iter {index}: REQ un-acked hold"
        )
        status = await tb.read_status()
        assert status["req_out"] == 1, f"sender iter {index}: STATUS.REQ_OUT expected 1"
        assert status["busy"] == 1, f"sender iter {index}: STATUS.BUSY expected 1"

        tb.log.info("iter %d: assert CT_Ack_in, expect REQ deassert", index)
        dut.ct_ack_in_din.value = 1
        await tb.wait_level(
            dut.ct_req_out_dout, 0, GPIO_SYNC_LATENCY, f"sender iter {index}: REQ deassert"
        )
        status = await tb.read_status()
        assert status["ack_in"] == 1, f"sender iter {index}: STATUS.ACK_IN expected 1"
        assert status["req_out"] == 0, f"sender iter {index}: STATUS.REQ_OUT expected 0"
        # Spec: BUSY covers the whole exchange; the sender FSM leaves its
        # wait state only after CT_Ack_in deasserts.
        assert int(dut.busy.value) == 1, (
            f"sender iter {index}: busy must stay set until CT_Ack_in deasserts"
        )

        tb.log.info("iter %d: deassert CT_Ack_in, expect BUSY release", index)
        dut.ct_ack_in_din.value = 0
        await tb.wait_level(dut.busy, 0, GPIO_SYNC_LATENCY, f"sender iter {index}: idle")
    pulses = tb.ct_dst_pulses()
    assert pulses == 0, f"sender-only traffic must not pulse ct_dst (observed {pulses})"

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: receiver handshake (%d randomized iterations)", N_HANDSHAKE_ITER)
    tb.log.info("=" * 70)
    for index in range(N_HANDSHAKE_ITER):
        hold = random.randrange(3, 21)
        before = tb.ct_dst_pulses()
        tb.log.info("iter %d: assert CT_Req_in, hold %d cycles", index, hold)
        dut.ct_req_in_din.value = 1
        await tb.wait_level(
            dut.ct_dst, 1, GPIO_SYNC_LATENCY, f"receiver iter {index}: ct_dst pulse"
        )
        await tb.wait_level(
            dut.ct_ack_out_dout, 1, GPIO_SYNC_LATENCY, f"receiver iter {index}: ACK assert"
        )
        status = await tb.read_status()
        assert status["req_in"] == 1, f"receiver iter {index}: STATUS.REQ_IN expected 1"
        assert status["ack_out"] == 1, f"receiver iter {index}: STATUS.ACK_OUT expected 1"
        assert status["busy"] == 1, f"receiver iter {index}: STATUS.BUSY expected 1"
        await ClockCycles(dut.clk, hold)

        tb.log.info("iter %d: deassert CT_Req_in, expect ACK release and idle", index)
        dut.ct_req_in_din.value = 0
        await tb.wait_level(
            dut.ct_ack_out_dout, 0, GPIO_SYNC_LATENCY, f"receiver iter {index}: ACK deassert"
        )
        await tb.wait_level(dut.busy, 0, GPIO_SYNC_LATENCY, f"receiver iter {index}: idle")
        observed = tb.ct_dst_pulses() - before
        assert observed == 1, (
            f"receiver iter {index}: expected exactly 1 ct_dst pulse per request, "
            f"observed {observed}"
        )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: full duplex (concurrent sender and receiver exchange)")
    tb.log.info("=" * 70)
    before = tb.ct_dst_pulses()
    await tb.pulse_ct_src()
    dut.ct_req_in_din.value = 1
    await tb.wait_level(dut.ct_req_out_dout, 1, GPIO_SYNC_LATENCY, "duplex: REQ assert")
    await tb.wait_level(dut.ct_ack_out_dout, 1, GPIO_SYNC_LATENCY, "duplex: ACK assert")
    status = await tb.read_status()
    assert status["req_out"] == 1 and status["ack_out"] == 1, (
        "duplex: both FSMs must be active at once "
        f"(req_out={status['req_out']} ack_out={status['ack_out']})"
    )
    # Complete the outgoing exchange first; the receiver side must be
    # unaffected (its ACK still tracks CT_Req_in).
    dut.ct_ack_in_din.value = 1
    await tb.wait_level(dut.ct_req_out_dout, 0, GPIO_SYNC_LATENCY, "duplex: REQ deassert")
    assert int(dut.ct_ack_out_dout.value) == 1, (
        "duplex: completing the sender exchange must not release the receiver ACK"
    )
    dut.ct_ack_in_din.value = 0
    dut.ct_req_in_din.value = 0
    await tb.wait_level(dut.ct_ack_out_dout, 0, GPIO_SYNC_LATENCY, "duplex: ACK deassert")
    await tb.wait_level(dut.busy, 0, GPIO_SYNC_LATENCY, "duplex: idle")
    observed = tb.ct_dst_pulses() - before
    assert observed == 1, f"duplex: expected exactly 1 ct_dst pulse, observed {observed}"

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 5: deadlock recovery via CONFIG.RESET")
    tb.log.info("=" * 70)
    tb.log.info("Step 1: start a handshake and withhold CT_Ack_in")
    await tb.pulse_ct_src()
    await tb.wait_level(dut.ct_req_out_dout, 1, GPIO_SYNC_LATENCY, "recovery: REQ assert")
    await _check_stable(tb, dut.ct_req_out_dout, 1, 30, "recovery: REQ stuck without ACK")

    tb.log.info("Step 2: CONFIG.RESET=1 force-clears the request")
    await tb.write_config(mode=1, reset=1)
    await tb.wait_level(dut.ct_req_out_dout, 0, GPIO_SYNC_LATENCY, "recovery: forced REQ clear")
    await tb.wait_level(dut.busy, 0, GPIO_SYNC_LATENCY, "recovery: forced idle")
    status = await tb.read_status()
    assert status["req_out"] == 0 and status["busy"] == 0, (
        f"recovery: STATUS must show idle after RESET (req_out={status['req_out']} "
        f"busy={status['busy']})"
    )

    tb.log.info("Step 3: release RESET and prove a normal handshake completes")
    await tb.write_config(mode=1, reset=0)
    await tb.pulse_ct_src()
    await tb.wait_level(dut.ct_req_out_dout, 1, GPIO_SYNC_LATENCY, "recovery: new REQ assert")
    dut.ct_ack_in_din.value = 1
    await tb.wait_level(dut.ct_req_out_dout, 0, GPIO_SYNC_LATENCY, "recovery: new REQ deassert")
    dut.ct_ack_in_din.value = 0
    await tb.wait_level(dut.busy, 0, GPIO_SYNC_LATENCY, "recovery: idle after recovery")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 6: INVERT sense in point-to-point mode")
    tb.log.info("=" * 70)
    # Park both P2P inputs at the inverted-idle raw level (1 = logical 0)
    # before checks start; the sense flip itself makes the receiver see a
    # transient logical request, so settle() and re-park cover the swap.
    await tb.write_config(mode=1, invert=1)
    dut.ct_req_in_din.value = 1
    dut.ct_ack_in_din.value = 1
    await tb.settle()
    await tb.wait_level(dut.busy, 0, GPIO_SYNC_LATENCY * 2, "invert: quiesce after sense flip")
    tb.clear_ct_dst_pulses()

    tb.log.info("Step 1: inverted sender — pads idle high, assert low")
    dout = int(dut.ct_req_out_dout.value)
    assert dout == 1, f"invert: CT_Req_out data must idle high, observed {dout}"
    await tb.pulse_ct_src()
    await tb.wait_level(
        dut.ct_req_out_dout, 0, GPIO_SYNC_LATENCY, "invert: REQ assert (active-low)"
    )
    status = await tb.read_status()
    assert status["req_out"] == 1, (
        "invert: STATUS.REQ_OUT keeps the logical sense (expected 1 while the pad is low)"
    )
    dut.ct_ack_in_din.value = 0  # logical ACK assert
    await tb.wait_level(
        dut.ct_req_out_dout, 1, GPIO_SYNC_LATENCY, "invert: REQ deassert (back to idle-high)"
    )
    dut.ct_ack_in_din.value = 1  # logical ACK deassert
    await tb.wait_level(dut.busy, 0, GPIO_SYNC_LATENCY, "invert: sender idle")

    tb.log.info("Step 2: inverted receiver — request low, ACK drives low")
    before = tb.ct_dst_pulses()
    dut.ct_req_in_din.value = 0  # logical REQ assert
    await tb.wait_level(dut.ct_dst, 1, GPIO_SYNC_LATENCY, "invert: ct_dst pulse")
    await tb.wait_level(
        dut.ct_ack_out_dout, 0, GPIO_SYNC_LATENCY, "invert: ACK assert (active-low)"
    )
    status = await tb.read_status()
    assert status["req_in"] == 1 and status["ack_out"] == 1, (
        "invert: STATUS keeps the logical sense "
        f"(req_in={status['req_in']} ack_out={status['ack_out']})"
    )
    dut.ct_req_in_din.value = 1  # logical REQ deassert
    await tb.wait_level(
        dut.ct_ack_out_dout, 1, GPIO_SYNC_LATENCY, "invert: ACK deassert (back to idle-high)"
    )
    await tb.wait_level(dut.busy, 0, GPIO_SYNC_LATENCY, "invert: receiver idle")
    observed = tb.ct_dst_pulses() - before
    assert observed == 1, f"invert: expected exactly 1 ct_dst pulse, observed {observed}"

    # Restore the non-inverted quiescent state.
    dut.ct_req_in_din.value = 0
    dut.ct_ack_in_din.value = 0
    await tb.write_config(mode=0, invert=0)
    await tb.settle()

    tb.log.info("ctp_p2p_test PASSED (seed=%d)", seed)
