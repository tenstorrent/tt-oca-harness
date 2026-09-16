# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Network routing: cross-mode matrix routes with isolation.

Every scenario programs one CTM route (target matrix port selects one source
matrix port), fires the source, and judges the target observable — while a
BitWatcher on an unrouted external CTP proves the trigger did not leak
(isolation with the routed target as the positive control).

Source kinds (how a trigger enters the matrix):

* ``ext_wo``  — external CTP in wire-OR mode, pulsed on its CT_Req_out pad
  input;
* ``ext_p2p`` — external CTP in P2P mode, requested on its CT_Req_in pad
  (its receiver FSM also acks on CT_Ack_out);
* ``int_wo``  — internal wire-OR CT port, pulsed on ctm_dst_req;
* ``int_p2p`` — internal P2P CT port, requested on ctm_dst_req with the
  ctm_dst_ack handshake checked.

Target kinds (how a routed trigger leaves the matrix):

* ``ext_wo``  — stretched CT_Req_out enable window of exactly
  STRETCH_MULT+1 cycles;
* ``ext_p2p`` — CT_Req_out data asserts and holds until acked on CT_Ack_in;
* ``int_wo``  — 2-cycle ctm_src_req pulse (the RTL's fixed internal stretch);
* ``int_p2p`` — ctm_src_req asserts and holds until acked on ctm_src_ack.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from ctn_base_test import (
    E2E_LATENCY,
    EXT_WIRE_OR_STRETCH,
    INT_WIRE_OR_STRETCH,
    NUM_CTP,
    NUM_INT_CT,
    NUM_INT_CT_WIRE_OR,
    BitWatcher,
    CtnTb,
    int_ct_matrix_port,
    random_seed,
)

N_RAND_ITER = 12


async def _fire_source(tb: CtnTb, kind: str, index: int, what: str) -> None:
    """Inject one trigger into the matrix through the chosen source."""
    dut = tb.dut
    if kind == "ext_wo":
        # Wire-OR receive: a logical rising edge on the shared-wire input.
        await tb.pulse_input_bit("ctp_req_out_din", index, 4)
    elif kind == "ext_p2p":
        # P2P receive: request in, receiver FSM acks autonomously.
        tb.set_input_bit("ctp_req_in_din", index, 1)
        await tb.wait_bit(dut.ctp_ack_out_dout, index, 1, E2E_LATENCY, f"{what}: source ack")
        tb.set_input_bit("ctp_req_in_din", index, 0)
        await tb.wait_bit(dut.ctp_ack_out_dout, index, 0, E2E_LATENCY, f"{what}: source ack drop")
    elif kind == "int_wo":
        await tb.pulse_input_bit("ctm_dst_req", index, 4)
    elif kind == "int_p2p":
        tb.set_input_bit("ctm_dst_req", index, 1)
        await tb.wait_bit(dut.ctm_dst_ack, index, 1, E2E_LATENCY, f"{what}: source ack")
        tb.set_input_bit("ctm_dst_req", index, 0)
        await tb.wait_bit(dut.ctm_dst_ack, index, 0, E2E_LATENCY, f"{what}: source ack drop")
    else:
        raise ValueError(kind)


async def _expect_target(tb: CtnTb, kind: str, index: int, what: str) -> None:
    """Judge the routed observable for the chosen target."""
    dut = tb.dut
    if kind == "ext_wo":
        await tb.wait_bit(dut.ctp_req_out_dout_en, index, 1, E2E_LATENCY, f"{what}: window")
        window = await tb.measure_bit_high(dut.ctp_req_out_dout_en, index, 100, f"{what}: window")
        expected = EXT_WIRE_OR_STRETCH + 1
        assert window == expected, (
            f"{what}: stretched window {window} cycles != STRETCH_MULT+1 = {expected}"
        )
    elif kind == "ext_p2p":
        await tb.wait_bit(dut.ctp_req_out_dout, index, 1, E2E_LATENCY, f"{what}: REQ")
        tb.set_input_bit("ctp_ack_in_din", index, 1)
        await tb.wait_bit(dut.ctp_req_out_dout, index, 0, E2E_LATENCY, f"{what}: REQ drop")
        tb.set_input_bit("ctp_ack_in_din", index, 0)
    elif kind == "int_wo":
        await tb.wait_bit(dut.ctm_src_req, index, 1, E2E_LATENCY, f"{what}: pulse")
        window = await tb.measure_bit_high(dut.ctm_src_req, index, 100, f"{what}: pulse")
        expected = INT_WIRE_OR_STRETCH + 1
        assert window == expected, (
            f"{what}: internal pulse {window} cycles != fixed stretch+1 = {expected}"
        )
    elif kind == "int_p2p":
        await tb.wait_bit(dut.ctm_src_req, index, 1, E2E_LATENCY, f"{what}: REQ")
        tb.set_input_bit("ctm_src_ack", index, 1)
        await tb.wait_bit(dut.ctm_src_req, index, 0, E2E_LATENCY, f"{what}: REQ drop")
        tb.set_input_bit("ctm_src_ack", index, 0)
    else:
        raise ValueError(kind)


def _matrix_port(kind: str, index: int) -> int:
    return index if kind.startswith("ext") else int_ct_matrix_port(index)


def _pick_index(kind: str) -> int:
    if kind.startswith("ext"):
        return random.randrange(NUM_CTP)
    if kind == "int_wo":
        return random.randrange(NUM_INT_CT_WIRE_OR)
    return random.randrange(NUM_INT_CT_WIRE_OR, NUM_INT_CT)


@cocotb.test()
async def ctn_routing_test(dut) -> None:
    tb = CtnTb(dut, name="ctn_routing_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # All external CTPs start in wire-OR with the bench's standard stretch;
    # P2P participants are reconfigured per scenario.
    for index in range(NUM_CTP):
        await tb.config_ctp(index, mode=0, stretch=EXT_WIRE_OR_STRETCH)

    source_kinds = ("ext_wo", "ext_p2p", "int_wo", "int_p2p")
    target_kinds = ("ext_wo", "ext_p2p", "int_wo", "int_p2p")

    # Deterministic corners ahead of the random sweep: mixed wire-OR/P2P
    # pairs in both directions, plus one external wire-OR to wire-OR route.
    scenarios: list[tuple[str, int, str, int]] = [
        ("ext_wo", 0, "ext_p2p", 2),
        ("ext_p2p", 2, "ext_wo", 1),
        ("ext_wo", 0, "int_p2p", NUM_INT_CT_WIRE_OR),
        ("int_wo", 0, "ext_p2p", 3),
        ("int_p2p", NUM_INT_CT_WIRE_OR, "ext_wo", 0),
        ("int_wo", 1, "int_p2p", NUM_INT_CT - 1),
        ("int_p2p", NUM_INT_CT - 1, "int_wo", 2),
        ("ext_wo", 5, "ext_wo", 9),
    ]
    n_directed = len(scenarios)
    while len(scenarios) < n_directed + N_RAND_ITER:
        src_kind = random.choice(source_kinds)
        tgt_kind = random.choice(target_kinds)
        src_index = _pick_index(src_kind)
        tgt_index = _pick_index(tgt_kind)
        if _matrix_port(src_kind, src_index) == _matrix_port(tgt_kind, tgt_index):
            continue
        scenarios.append((src_kind, src_index, tgt_kind, tgt_index))

    for number, (src_kind, src_index, tgt_kind, tgt_index) in enumerate(scenarios):
        what = f"scenario {number}: {src_kind}[{src_index}] -> {tgt_kind}[{tgt_index}]"
        tb.log.info("=" * 70)
        tb.log.info(
            "SCENARIO %d: %s[%d] -> %s[%d]", number, src_kind, src_index, tgt_kind, tgt_index
        )
        tb.log.info("=" * 70)

        src_port = _matrix_port(src_kind, src_index)
        tgt_port = _matrix_port(tgt_kind, tgt_index)

        # Mode setup for the external participants of this scenario.
        if src_kind == "ext_p2p":
            await tb.config_ctp(src_index, mode=1)
        elif src_kind == "ext_wo":
            await tb.config_ctp(src_index, mode=0, stretch=EXT_WIRE_OR_STRETCH)
        if tgt_kind == "ext_p2p":
            await tb.config_ctp(tgt_index, mode=1)
        elif tgt_kind == "ext_wo":
            await tb.config_ctp(tgt_index, mode=0, stretch=EXT_WIRE_OR_STRETCH)

        # Isolation observer: an unrouted external wire-OR CTP must stay
        # silent while the routed target (positive control) fires.
        quiet_index = next(
            i
            for i in range(NUM_CTP)
            if i
            not in (
                src_index if src_kind.startswith("ext") else -1,
                tgt_index if tgt_kind.startswith("ext") else -1,
            )
        )
        await tb.config_ctp(quiet_index, mode=0, stretch=EXT_WIRE_OR_STRETCH)
        watcher = BitWatcher(
            tb, dut.ctp_req_out_dout_en, quiet_index, f"quiet CTP[{quiet_index}]"
        ).start()

        await tb.route(tgt_port, 1 << src_port)
        await ClockCycles(dut.clk, 2)

        # Fire and judge concurrently: the source handshake for P2P kinds
        # only completes once its own ack path settles, while the target
        # observable appears mid-flight.
        fire_task = cocotb.start_soon(_fire_source(tb, src_kind, src_index, what))
        await _expect_target(tb, tgt_kind, tgt_index, what)
        await fire_task

        await tb.route(tgt_port, 0)
        await tb.quiesce()
        await watcher.stop()
        assert watcher.pulses == 0, (
            f"{what}: unrouted CTP[{quiet_index}] fired {watcher.pulses} time(s) — "
            "trigger leaked past the programmed route"
        )
        tb.log.info("SCENARIO %d passed (quiet port stayed silent)", number)

    tb.log.info("ctn_routing_test PASSED (seed=%d)", seed)
