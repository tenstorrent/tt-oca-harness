# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Network loopback: full paths over emulated pad wiring.

Where the routing test judges one matrix hop per scenario, these scenarios
emulate the chip-to-chip wiring in the bench (pad output mirrored onto a pad
input every cycle) and judge complete multi-hop paths:

1. Wire-OR chain — CTP[i] --matrix--> CTP[j] --emulated wire--> CTP[k]
   --matrix--> internal wire-OR CT[m]: one external pulse into i must arrive
   at m exactly once, having crossed two matrix hops and one wire.
2. External P2P pair — CTP[i] (sender) cross-coupled with CTP[j] (receiver):
   the four-phase handshake completes autonomously through the mirrors, the
   received trigger lands on an internal observable exactly once, and both
   CTPs report BUSY==0 through the CSR crossbar afterwards.
3. Internal P2P duplex — two internal P2P CTs routed at each other complete
   simultaneous handshakes in both directions.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge
from ctn_base_test import (
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
    """Mirror pad outputs onto pad inputs each cycle (bench-emulated wiring).

    Each connection maps one bit of a DUT output vector onto one bit of a
    driven input vector, standing in for the board/package wire between two
    chiplets' pads.
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
    tb = CtnTb(dut, name="ctn_loopback_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()
    for index in range(NUM_CTP):
        await tb.config_ctp(index, mode=0, stretch=EXT_WIRE_OR_STRETCH)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: wire-OR chain over an emulated wire")
    tb.log.info("=" * 70)
    i, j, k = random.sample(range(NUM_CTP), 3)
    m = random.randrange(NUM_INT_CT_WIRE_OR)
    tb.log.info(
        "chain: CTP[%d] -> matrix -> CTP[%d] -> wire -> CTP[%d] -> matrix -> int CT[%d]",
        i,
        j,
        k,
        m,
    )
    await tb.route(j, 1 << i)
    await tb.route(int_ct_matrix_port(m), 1 << k)
    mirror = PadMirror(tb, [("ctp_req_out_dout_en", j, "ctp_req_out_din", k)]).start()
    j_watch = BitWatcher(tb, dut.ctp_req_out_dout_en, j, f"CTP[{j}] window").start()
    m_watch = BitWatcher(tb, dut.ctm_src_req, m, f"int CT[{m}] pulse").start()

    await tb.pulse_input_bit("ctp_req_out_din", i, 4)
    await tb.wait_bit(dut.ctm_src_req, m, 1, 3 * E2E_LATENCY, "chain: arrival at int CT")
    await ClockCycles(dut.clk, E2E_LATENCY)

    await mirror.stop()
    await j_watch.stop()
    await m_watch.stop()
    assert j_watch.pulses == 1, (
        f"chain: CTP[{j}] repeater fired {j_watch.pulses} windows, expected exactly 1"
    )
    assert j_watch.high_samples == EXT_WIRE_OR_STRETCH + 1, (
        f"chain: CTP[{j}] window {j_watch.high_samples} cycles != "
        f"STRETCH_MULT+1 = {EXT_WIRE_OR_STRETCH + 1}"
    )
    assert m_watch.pulses == 1, (
        f"chain: internal CT[{m}] fired {m_watch.pulses} pulses, expected exactly 1 "
        "for one external trigger"
    )
    await tb.route(j, 0)
    await tb.route(int_ct_matrix_port(m), 0)
    await tb.quiesce()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: external P2P pair with autonomous four-phase handshake")
    tb.log.info("=" * 70)
    i, j = random.sample(range(NUM_CTP), 2)
    a = random.randrange(NUM_INT_CT_WIRE_OR)
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
    a, b = random.sample(range(NUM_INT_CT_WIRE_OR, NUM_INT_CT), 2)
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
