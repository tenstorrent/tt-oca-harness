# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
 I3C Max-Length / Boundary Transfer

Private write/read at boundary lengths around the FIFO capacity and large
transfers, after raising MWL/MRL. Validates multi-descriptor / FIFO-refill
handling at boundaries.

Directed + random: the fixed boundary list is always exercised (deterministic
coverage of the known corners), and a few random lengths drawn from the shared
constrained-random framework are added on top (seed from +seed/SEED/default).
Data is randomized every iteration; the built-in scoreboard checks each.
"""

import cocotb
from cocotb.triggers import ClockCycles
from env.i3c_rand import RandMgr, rand_bytes, rand_len
from env.i3c_test_base import bring_up_and_assign, make_env

MWL = 256
BOUNDARY_LENGTHS = [1, 31, 32, 33, 64, 256]  # directed corners (always run)
N_RANDOM = 4  # extra random lengths on top


@cocotb.test(timeout_time=10000, timeout_unit="us")
async def test_max_length_transfer(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)

    # MWL/MRL are what make the 256-byte boundary leg legal, so a silently failed CCC
    # would leave the boundary legs running against the target's reset envelope.
    # set_ccc reports failure only via a returned flag.
    ok, resp = await ctrl.setmwl(MWL, dat_idx=0)
    assert ok, f"SETMWL({MWL}) failed resp=0x{resp:08X}"
    ok, resp = await ctrl.setmrl(MWL, ibi_payload_size=0xFF, dat_idx=0)
    assert ok, f"SETMRL({MWL}) failed resp=0x{resp:08X}"

    r = RandMgr(name="max_length")  # seed logged; +seed/SEED override
    lengths = list(BOUNDARY_LENGTHS) + [rand_len(r, MWL) for _ in range(N_RANDOM)]

    for n in lengths:
        wr = rand_bytes(r, n)  # random data
        ok, resp, rx = await ctrl.private_write(wr, tgt, dat_idx=0)
        assert ok, f"{n}B write failed resp=0x{resp:08X}"
        assert rx == wr, f"{n}B write data mismatch"

        rd = rand_bytes(r, n)
        ok, resp, crx = await ctrl.private_read(tgt, rd, dat_idx=0)
        assert ok, f"{n}B read failed resp=0x{resp:08X}"
        assert crx == rd, f"{n}B read data mismatch"
        tb.log.info(f"length {n} ok")
        await ClockCycles(dut.clk, 50)

    tb.log.info(f"Max-length/boundary transfer complete (seed=0x{r.seed:08X})")
