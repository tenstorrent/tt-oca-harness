# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
 I3C Random CCC Stress

Directed-random CCC ordering: repeatedly pick a CCC from the supported set in
random order and issue it, stressing the command FSM. SET values are drawn from
the full legal range, and SET/GET round-trips self-check.

Uses the shared constrained-random framework (constrained_random + i3c_rand):
seed from +seed=<n> / SEED=<n> / default, logged, so regression runs vary the
sequence and accumulate coverage. CCCs are picked by weight (GET-heavy, like
real read-mostly traffic) to bias the command-FSM ordering.
"""

import cocotb
from env.i3c_rand import RandMgr, rand_mrl, rand_mwl, weighted
from env.i3c_test_base import bring_up_and_assign, make_env

N_ITERS = 30


@cocotb.test(timeout_time=8000, timeout_unit="us")
async def test_random_ccc_stress(dut):
    tb, helper, ctrl, tgt = await make_env(dut)
    await bring_up_and_assign(ctrl, tgt)

    r = RandMgr(name="random_ccc")  # seed logged; +seed/SEED override

    # shadow model of the last programmed MWL/MRL for SET/GET self-checking
    shadow = {"mwl": None, "mrl": None}
    # Require at least one MWL and MRL comparison regardless of randomized ordering.
    compares = {"mwl": 0, "mrl": 0}

    async def ccc_getbcr():
        ok, _ = await ctrl.getbcr(dat_idx=0)
        assert ok, "GETBCR failed"

    async def ccc_setmwl():
        v = rand_mwl(r)  # full legal range 1..4095
        ok, _ = await ctrl.setmwl(v, dat_idx=0)
        assert ok, f"SETMWL({v}) failed"
        shadow["mwl"] = v

    async def ccc_getmwl():
        ok, got = await ctrl.getmwl(dat_idx=0)
        assert ok, "GETMWL failed"
        assert shadow["mwl"] is not None, "shadow MWL unseeded — see the seeding step"
        assert got == shadow["mwl"], f"MWL {got:#x} != set {shadow['mwl']:#x}"
        compares["mwl"] += 1

    async def ccc_setmrl():
        v = rand_mrl(r)
        ibi = weighted(r, [(0, 4), (0x08, 3), (0x10, 2), (0xFF, 1)])
        ok, _ = await ctrl.setmrl(v, ibi_payload_size=ibi, dat_idx=0)
        assert ok, f"SETMRL({v}) failed"
        shadow["mrl"] = v

    async def ccc_getmrl():
        ok, got, _ibi = await ctrl.getmrl(dat_idx=0)
        assert ok, "GETMRL failed"
        assert shadow["mrl"] is not None, "shadow MRL unseeded — see the seeding step"
        assert got == shadow["mrl"], f"MRL {got:#x} != set {shadow['mrl']:#x}"
        compares["mrl"] += 1

    # Seed the shadow with one directed SET of each so every GET the random loop draws
    # is a real comparison rather than a skipped one.
    await ccc_setmwl()
    await ccc_setmrl()

    # weighted CCC pool: GET-heavy ordering
    ccc_pool = [
        (ccc_getbcr, 3),
        (ccc_setmwl, 2),
        (ccc_getmwl, 3),
        (ccc_setmrl, 2),
        (ccc_getmrl, 3),
    ]

    for i in range(N_ITERS):
        op = weighted(r, ccc_pool)
        tb.log.info(f"[{i}] CCC -> {op.__name__}")
        await op()

    # Directed round-trip of each register after the random ordering, so the minimum
    # activity below is guaranteed by construction and not by what the seed happened
    # to draw.
    await ccc_getmwl()
    await ccc_getmrl()

    # Zero executed comparisons must be a failure, never a pass.
    assert compares["mwl"] >= 1 and compares["mrl"] >= 1, (
        f"zero-activity pass: MWL compares={compares['mwl']}, "
        f"MRL compares={compares['mrl']} (seed=0x{r.seed:08X})"
    )

    tb.log.info(
        f"Random CCC stress ({N_ITERS} iters, seed=0x{r.seed:08X}) complete; "
        f"MWL compares={compares['mwl']}, MRL compares={compares['mrl']}"
    )
