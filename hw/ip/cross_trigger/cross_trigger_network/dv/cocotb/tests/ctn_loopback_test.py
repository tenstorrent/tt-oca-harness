# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Network loopback: full paths over chip-to-chip wiring.

Where the routing test judges one matrix hop per scenario, these scenarios
wire chiplets together in the bench and judge complete multi-hop paths:

1. Wire-OR chain — CTP[i] --matrix--> CTP[j] --shared wire--> CTP[k] and
   CTP[l] --matrix--> internal wire-OR CT[m] and CT[n]: one pull of i's wire
   by its chiplet arrives at m and at n exactly once, having crossed two
   matrix hops and the open-drain wire j, k and l share. Every port fires
   CT_DST_LATENCY cycles after the wire it listens to is pulled, and the
   repeater's own pull is the one assertion the wire carries.
2. External P2P pair — CTP[i] (sender) cross-coupled with CTP[j] (receiver)
   by pad mirrors (push-pull point-to-point pads): the four-phase handshake
   completes autonomously, the received trigger lands on an internal
   observable exactly once, and both CTPs report BUSY==0 through the CSR
   crossbar afterwards.
3. Internal P2P duplex — two internal P2P CTs routed at each other complete
   simultaneous handshakes in both directions.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge
from ctn_base_test import (
    CT_DST_LATENCY,
    CTP_STATUS_BUSY_BIT,
    E2E_LATENCY,
    EXT_WIRE_OR_STRETCH,
    NUM_CTP,
    NUM_INT_CT,
    NUM_INT_CT_WIRE_OR,
    BitWatcher,
    CtnTb,
    int_ct_matrix_port,
    random_seed,
)


class PadMirror:
    """Mirror pad outputs onto pad inputs each cycle (point-to-point wiring).

    Each connection maps one bit of a DUT output vector onto one bit of a
    driven input vector, standing in for the board/package wire between two
    chiplets' push-pull pads.
    """

    def __init__(self, tb: CtnTb, connections: list[tuple[str, int, str, int]]) -> None:
        # connections: (output signal name, output bit, input name, input bit)
        self._tb = tb
        self._connections = connections
        self._stop = False
        self._task = None

    def start(self) -> "PadMirror":
        self._stop = False
        self._task = cocotb.start_soon(self._run())
        return self

    async def _run(self) -> None:
        while not self._stop:
            await FallingEdge(self._tb.dut.clk)
            for out_name, out_bit, in_name, in_bit in self._connections:
                level = (int(getattr(self._tb.dut, out_name).value) >> out_bit) & 1
                self._tb.set_input_bit(in_name, in_bit, level)

    async def stop(self) -> None:
        self._stop = True
        await self._task
        for _, _, in_name, in_bit in self._connections:
            self._tb.set_input_bit(in_name, in_bit, 0)


@cocotb.test()
async def ctn_loopback_test(dut) -> None:
    """Multi-hop paths over a shared wire-OR wire and point-to-point pad mirrors."""
    tb = CtnTb(dut, name="ctn_loopback_test")
    seed = random_seed()
    rng = random.Random(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()
    for index in range(NUM_CTP):
        await tb.config_ctp(index, mode=0, stretch=EXT_WIRE_OR_STRETCH)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: wire-OR chain over a shared wire with two listeners")
    tb.log.info("=" * 70)
    i, j, k, q = rng.sample(range(NUM_CTP), 4)
    m, n = rng.sample(range(NUM_INT_CT_WIRE_OR), 2)
    tb.log.info(
        "chain: CTP[%d] -> matrix -> CTP[%d] -> shared wire -> CTP[%d], CTP[%d] -> matrix -> "
        "int CT[%d], int CT[%d]",
        i,
        j,
        k,
        q,
        m,
        n,
    )
    await tb.route(j, 1 << i)
    await tb.route(int_ct_matrix_port(m), 1 << k)
    await tb.route(int_ct_matrix_port(n), 1 << q)
    tb.share_wire((1 << j) | (1 << k) | (1 << q))
    i_dst = BitWatcher(tb, dut.ctp_ct_dst, i, f"CTP[{i}] ct_dst").start()
    j_watch = BitWatcher(tb, dut.ctp_req_out_dout_en, j, f"CTP[{j}] window").start()
    listeners = {
        idx: BitWatcher(tb, dut.ctp_ct_dst, idx, f"CTP[{idx}] ct_dst").start() for idx in (j, k, q)
    }
    m_watch = BitWatcher(tb, dut.ctm_src_req, m, f"int CT[{m}] pulse").start()
    n_watch = BitWatcher(tb, dut.ctm_src_req, n, f"int CT[{n}] pulse").start()

    pulled_at = await tb.assert_wire(i)
    await tb.wait_bit(dut.ctm_src_req, m, 1, 2 * E2E_LATENCY, "chain: arrival at int CT m")
    await tb.wait_bit(dut.ctm_src_req, n, 1, 2 * E2E_LATENCY, "chain: arrival at int CT n")
    await ClockCycles(dut.clk, E2E_LATENCY)

    for watch in (i_dst, j_watch, m_watch, n_watch, *listeners.values()):
        await watch.stop()
    assert i_dst.rise_cycles == [pulled_at + CT_DST_LATENCY], (
        f"chain: CTP[{i}] wire pulled at cycle {pulled_at}, expected one ct_dst at "
        f"{pulled_at + CT_DST_LATENCY}, observed {i_dst.rise_cycles}"
    )
    assert j_watch.pulses == 1, (
        f"chain: CTP[{j}] repeater fired {j_watch.pulses} windows, expected exactly 1"
    )
    assert j_watch.high_samples == EXT_WIRE_OR_STRETCH + 1, (
        f"chain: CTP[{j}] window {j_watch.high_samples} cycles != "
        f"STRETCH_MULT+1 = {EXT_WIRE_OR_STRETCH + 1}"
    )
    # The repeater's enable pulls the shared wire in the cycle it rises; the
    # repeater and both listeners receive that one assertion together.
    wire_pulled_at = j_watch.rise_cycles[0]
    for idx, watch in listeners.items():
        assert watch.rise_cycles == [wire_pulled_at + CT_DST_LATENCY], (
            f"chain: shared wire pulled at cycle {wire_pulled_at}, expected CTP[{idx}] ct_dst "
            f"once at {wire_pulled_at + CT_DST_LATENCY}, observed {watch.rise_cycles}"
        )
    for idx, watch in ((m, m_watch), (n, n_watch)):
        assert watch.pulses == 1, (
            f"chain: internal CT[{idx}] fired {watch.pulses} pulses, expected exactly 1 "
            "for one external trigger"
        )
    await tb.route(j, 0)
    await tb.route(int_ct_matrix_port(m), 0)
    await tb.route(int_ct_matrix_port(n), 0)
    await tb.quiesce()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: external P2P pair with autonomous four-phase handshake")
    tb.log.info("=" * 70)
    i, j = rng.sample(range(NUM_CTP), 2)
    a = rng.randrange(NUM_INT_CT_WIRE_OR)
    m = (a + 1) % NUM_INT_CT_WIRE_OR
    tb.log.info(
        "pair: int CT[%d] -> matrix -> CTP[%d](sender) <-> CTP[%d](receiver) -> "
        "matrix -> int CT[%d]",
        a,
        i,
        j,
        m,
    )
    await tb.config_ctp(i, mode=1)
    await tb.config_ctp(j, mode=1)
    await tb.route(i, 1 << int_ct_matrix_port(a))
    await tb.route(int_ct_matrix_port(m), 1 << j)
    mirror = PadMirror(
        tb,
        [
            ("ctp_req_out_dout", i, "ctp_req_in_din", j),
            ("ctp_ack_out_dout", j, "ctp_ack_in_din", i),
        ],
    ).start()
    m_watch = BitWatcher(tb, dut.ctm_src_req, m, f"int CT[{m}] pulse").start()

    await tb.pulse_input_bit("ctm_dst_req", a, 4)
    await tb.wait_bit(dut.ctp_req_out_dout, i, 1, 2 * E2E_LATENCY, "pair: sender REQ")
    # The mirrored receiver ack must retire the request without any bench
    # intervention (spec four-phase sequence).
    await tb.wait_bit(dut.ctp_req_out_dout, i, 0, 3 * E2E_LATENCY, "pair: REQ retired")
    await tb.wait_bit(dut.ctp_ack_out_dout, j, 0, 3 * E2E_LATENCY, "pair: ACK retired")
    await tb.wait_bit(dut.ctm_src_req, m, 0, 3 * E2E_LATENCY, "pair: observable idle")

    await m_watch.stop()
    await mirror.stop()
    assert m_watch.pulses == 1, (
        f"pair: internal CT[{m}] fired {m_watch.pulses} pulses, expected exactly 1 "
        "for one delivered P2P trigger"
    )
    for index, role in ((i, "sender"), (j, "receiver")):
        status = await tb.read_ctp_status(index)
        busy = (status >> CTP_STATUS_BUSY_BIT) & 1
        assert busy == 0, (
            f"pair: CTP[{index}] ({role}) STATUS.BUSY still set after the handshake "
            f"(STATUS=0x{status:02x})"
        )
    await tb.route(i, 0)
    await tb.route(int_ct_matrix_port(m), 0)
    await tb.config_ctp(i, mode=0, stretch=EXT_WIRE_OR_STRETCH)
    await tb.config_ctp(j, mode=0, stretch=EXT_WIRE_OR_STRETCH)
    await tb.quiesce()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: internal P2P duplex (both directions at once)")
    tb.log.info("=" * 70)
    a, b = rng.sample(range(NUM_INT_CT_WIRE_OR, NUM_INT_CT), 2)
    tb.log.info("duplex: int CT[%d] <-> int CT[%d]", a, b)
    await tb.route(int_ct_matrix_port(b), 1 << int_ct_matrix_port(a))
    await tb.route(int_ct_matrix_port(a), 1 << int_ct_matrix_port(b))

    tb.set_input_bit("ctm_dst_req", a, 1)
    tb.set_input_bit("ctm_dst_req", b, 1)
    await tb.wait_bit(dut.ctm_dst_ack, a, 1, E2E_LATENCY, "duplex: ack to CLA a")
    await tb.wait_bit(dut.ctm_dst_ack, b, 1, E2E_LATENCY, "duplex: ack to CLA b")
    await tb.wait_bit(dut.ctm_src_req, b, 1, 2 * E2E_LATENCY, "duplex: request to CLA b")
    await tb.wait_bit(dut.ctm_src_req, a, 1, 2 * E2E_LATENCY, "duplex: request to CLA a")

    tb.set_input_bit("ctm_src_ack", a, 1)
    tb.set_input_bit("ctm_src_ack", b, 1)
    await tb.wait_bit(dut.ctm_src_req, a, 0, E2E_LATENCY, "duplex: request a retired")
    await tb.wait_bit(dut.ctm_src_req, b, 0, E2E_LATENCY, "duplex: request b retired")

    tb.set_input_bit("ctm_dst_req", a, 0)
    tb.set_input_bit("ctm_dst_req", b, 0)
    await tb.wait_bit(dut.ctm_dst_ack, a, 0, E2E_LATENCY, "duplex: ack a retired")
    await tb.wait_bit(dut.ctm_dst_ack, b, 0, E2E_LATENCY, "duplex: ack b retired")
    await tb.route(int_ct_matrix_port(a), 0)
    await tb.route(int_ct_matrix_port(b), 0)
    await tb.quiesce()

    tb.log.info("ctn_loopback_test PASSED (seed=%d)", seed)
