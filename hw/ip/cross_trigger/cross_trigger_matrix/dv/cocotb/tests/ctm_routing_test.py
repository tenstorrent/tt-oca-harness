# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Matrix routing: diagonal, broadcast, OR-combining, random.

Scenarios (contract from the architecture spec: each CT_Src selects any set
of CT_Dst inputs through its CONFIG_0.CT_DST_SELECT mask and ORs them
together, with a registered output):

1. Diagonal walk — CT_Src[i] selects exactly CT_Dst[i]; each one-hot input
   pulse yields exactly the matching one-hot output pulse.
2. Broadcast — every port selects the same CT_Dst; one input pulse fires
   every output together.
3. OR-combining with isolation — a random port selects a random multi-bit
   mask: every selected input fires it alone, and a non-selected input must
   NOT fire it while a full-mask control port proves the pulse was routable.
4. Randomized full-matrix — random masks on all ports against random
   multi-hot input vectors, checked as steady-state levels and as
   single-cycle pulses against the reference model.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from ctm_base_test import (
    NUM_CT_DST,
    NUM_CT_SRC,
    SELECT_MASK,
    CtmTb,
    expected_src_vector,
    random_seed,
)

N_RAND_ITER = 16


@cocotb.test()
async def ctm_routing_test(dut) -> None:
    tb = CtmTb(dut, name="ctm_routing_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: diagonal walk — CT_Dst[i] -> CT_Src[i] for all %d ports", NUM_CT_SRC)
    tb.log.info("=" * 70)
    diagonal = [1 << port for port in range(NUM_CT_SRC)]
    await tb.program_masks(diagonal, "diagonal")
    await ClockCycles(dut.clk, 2)
    for index in range(NUM_CT_DST):
        expected = (1 << index) if index < NUM_CT_SRC else 0
        await tb.pulse_and_expect(1 << index, expected, f"diagonal dst {index}")
    tb.log.info("diagonal walk: %d one-hot routes verified", NUM_CT_DST)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: broadcast — one CT_Dst fires every CT_Src")
    tb.log.info("=" * 70)
    broadcast_dst = random.randrange(NUM_CT_DST)
    await tb.program_masks([1 << broadcast_dst] * NUM_CT_SRC, "broadcast")
    await ClockCycles(dut.clk, 2)
    all_src = (1 << NUM_CT_SRC) - 1
    tb.log.info("broadcast source: CT_Dst[%d], expecting ct_src=0x%07x", broadcast_dst, all_src)
    await tb.pulse_and_expect(1 << broadcast_dst, all_src, "broadcast")
    # A different, unselected CT_Dst must stay silent everywhere.
    other_dst = (broadcast_dst + 1) % NUM_CT_DST
    await tb.pulse_and_expect(1 << other_dst, 0, "broadcast isolation")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: OR-combining with isolation (%d randomized iterations)", N_RAND_ITER)
    tb.log.info("=" * 70)
    for index in range(N_RAND_ITER):
        port = random.randrange(NUM_CT_SRC)
        control = (port + 1 + random.randrange(NUM_CT_SRC - 1)) % NUM_CT_SRC
        # A multi-bit mask that leaves at least one dst unselected.
        width = random.randrange(2, NUM_CT_DST - 1)
        mask = 0
        while bin(mask).count("1") < width:
            mask |= 1 << random.randrange(NUM_CT_DST)
        unselected = [bit for bit in range(NUM_CT_DST) if not (mask >> bit) & 1]
        masks = [0] * NUM_CT_SRC
        masks[port] = mask
        masks[control] = SELECT_MASK  # control port sees every dst
        await tb.program_masks(masks, f"or-combining iter {index} (port {port})")
        await ClockCycles(dut.clk, 2)

        selected_bit = random.choice([bit for bit in range(NUM_CT_DST) if (mask >> bit) & 1])
        tb.log.info(
            "iter %d: port %d mask=0x%07x control=%d, firing selected dst %d then "
            "unselected dst %d",
            index,
            port,
            mask,
            control,
            selected_bit,
            unselected[0],
        )
        expected = (1 << port) | (1 << control)
        await tb.pulse_and_expect(
            1 << selected_bit, expected, f"or-combining iter {index}: selected dst"
        )
        # Isolation with positive control: the unselected dst must fire ONLY
        # the full-mask control port — silence on `port` is meaningful
        # because the same pulse demonstrably reached the matrix.
        await tb.pulse_and_expect(
            1 << unselected[0], 1 << control, f"or-combining iter {index}: unselected dst"
        )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: randomized full-matrix (%d iterations)", N_RAND_ITER)
    tb.log.info("=" * 70)
    for index in range(N_RAND_ITER):
        masks = [random.getrandbits(NUM_CT_DST) for _ in range(NUM_CT_SRC)]
        dst_vector = random.getrandbits(NUM_CT_DST)
        expected = expected_src_vector(masks, dst_vector)
        await tb.program_masks(masks, f"full-matrix iter {index}")
        await ClockCycles(dut.clk, 2)
        tb.log.info("iter %d: dst=0x%07x, model expects src=0x%07x", index, dst_vector, expected)

        # Steady-state level check against the reference model.
        await tb.drive_dst_steady(dst_vector)
        tb.check_src(expected, f"full-matrix iter {index}: steady level")
        await tb.drive_dst_steady(0)
        tb.check_src(0, f"full-matrix iter {index}: release")

        # Single-cycle pulse fidelity against the same model.
        await tb.pulse_and_expect(dst_vector, expected, f"full-matrix iter {index}: pulse")

    await tb.clear_all_selects()
    tb.log.info("ctm_routing_test PASSED (seed=%d)", seed)
