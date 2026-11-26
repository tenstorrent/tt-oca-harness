# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTBN runs correctly at each ``PKA_CLK_DIV`` ratio, and its run time follows the ratio.

RAND-REP, no_cpu on ``lsu_stub_all_live`` with ``+skip_fuse_sense +esrc_noise_force``.
Contract (``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc``, ``PKA_CLK_DIV``;
``hw/sys/sep/doc/otbn.adoc``, OCAH Modifications):

* ``PKA_CLK_DIV.div`` resets to 2.
* OTBN runs on the SEP clock divided by ``div``; 0 and 1 run it undivided.

The seed orders the ratios {0, 1, 2, 3, 4}. At each one the leaf writes ``div``
with OTBN idle, reads it back, then runs the ``loopi`` capability program twice,
with 10 and with 1000 iterations, and grades each run against the ISA golden.
Each run's EXECUTE-to-IDLE time is measured in ``clk_i`` cycles. The difference
between the two runs is the time of 990 iterations of the two-instruction loop
body; the URND reseed at the start of each EXECUTE and the secure wipe at its end
cancel out of it.

Checkers:
  CHK-CLKDIV-RESET  ``PKA_CLK_DIV`` reads 2 before any write.
  CHK-CLKDIV-RW     ``PKA_CLK_DIV`` reads back the ratio just written.
  CHK-CLKDIV-EXEC   every run ends at IDLE with ``ERR_BITS`` 0 and both result
                    words equal to the golden.
  CHK-CLKDIV-SCALE  the 990-iteration time at a ratio r other than 1, with
                    effective ratio e (0 counts as 1), is between 0.875 x e and
                    1.125 x e times its time at ratio 1. The band is half the gap
                    to the next ratio at e = 4, so a divide by e - 1 or e + 1 fails.
  INFO-CLKDIV-BASE  the 990-iteration time at ratio 1, the reference of the scale.
"""

from __future__ import annotations

import dataclasses

import pyuvm
from cocotb.utils import get_sim_time
from env.sep_chk_log import SepChkLog
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL
from seq_lib.sep_otbn_compute_seq import SepOtbnCapPlan, SepOtbnCompute, cap_golden, cap_prog
from seq_lib.sep_otbn_seq import OTBN_STATUS_IDLE

_NAME = "sep_otbn_clk_div_test"

PKA_CLK_DIV = SEP_CPU_CTRL.addr("PKA_CLK_DIV")
_DIV_RESET = SEP_CPU_CTRL.field_reset("PKA_CLK_DIV", "div")
_DIV_MASK = SEP_CPU_CTRL.field_mask("PKA_CLK_DIV", "div")
_RATIOS = (0, 1, 2, 3, 4)
_LOOP_SHORT = 10
_LOOP_LONG = 1000
_SCALE_TOL = 0.125


@pyuvm.test()
class sep_otbn_clk_div_test(sep_base_test):
    """Each ratio reads back, runs the loop program to its golden, and scales its run time."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=("aes", "hmac", "kmac"))
        await self.bring_up_entropy(
            strict=True, score_km=False, score_sinks={"otbn_urnd": "observe"}
        )
        self.start_fifo_drain()

        seed = self.random_seed()
        self.chk = SepChkLog(self, _NAME, seed)
        ratios = list(_RATIOS)
        SepSeededRng(seed).shuffle(ratios)
        self.chk.info("RANDCFG", ratios=ratios, loop_short=_LOOP_SHORT, loop_long=_LOOP_LONG)

        otbn = SepOtbnCompute(self)
        await otbn.wait_idle("post-wipe", timeout=8_000)

        reset_val = await otbn._rd(PKA_CLK_DIV) & _DIV_MASK
        self.chk.ok("CLKDIV-RESET", reset_val == _DIV_RESET, got=reset_val, exp=_DIV_RESET)

        plan = SepOtbnCapPlan.from_seed(seed)
        body_cycles: dict[int, int] = {}
        for ratio in ratios:
            await otbn._wr(PKA_CLK_DIV, ratio)
            got_ratio = await otbn._rd(PKA_CLK_DIV) & _DIV_MASK
            self.chk.ok("CLKDIV-RW", got_ratio == ratio, got=got_ratio, exp=ratio)
            short = await self._run_loop(otbn, plan, ratio, _LOOP_SHORT)
            long = await self._run_loop(otbn, plan, ratio, _LOOP_LONG)
            body_cycles[ratio] = long - short

        base = body_cycles[1]
        self.chk.info("CLKDIV-BASE", ratio=1, body_cycles=base)
        for ratio in ratios:
            if ratio == 1:
                continue
            eff = max(ratio, 1)
            scale = body_cycles[ratio] / base
            self.chk.ok(
                "CLKDIV-SCALE",
                (1 - _SCALE_TOL) * eff <= scale <= (1 + _SCALE_TOL) * eff,
                ratio=ratio,
                body_cycles=body_cycles[ratio],
                base_body_cycles=base,
                scale=f"{scale:.2f}",
            )

        await otbn._wr(PKA_CLK_DIV, _DIV_RESET)
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.chk.finish()

    async def _run_loop(
        self, otbn: SepOtbnCompute, plan: SepOtbnCapPlan, ratio: int, loop_n: int
    ) -> int:
        """Run the loop program once; grade it and return its run time in clk_i cycles."""
        plan = dataclasses.replace(plan, loop_n=loop_n)
        golden = cap_golden(plan, "loop")
        # Each result word starts at the complement of its golden, so a word the
        # program never stores cannot match.
        await otbn.stage_program(
            cap_prog(plan, "loop"), {off: w ^ 0xFFFF_FFFF for off, w in golden.items()}
        )
        t0 = get_sim_time("ps")
        status, polls = await otbn.execute_to_end()
        run_cycles = round((get_sim_time("ps") - t0) / (self.cfg.sys_clk_period_ns * 1000))
        err = await otbn.read_errbits()
        offs = sorted(golden)
        got = [await otbn.read_dmem(off) for off in offs]
        exp = [golden[off] for off in offs]
        self.chk.ok(
            "CLKDIV-EXEC",
            status == OTBN_STATUS_IDLE and err == 0 and got == exp,
            ratio=ratio,
            loop_n=loop_n,
            status=f"0x{status:02x}",
            polls=polls,
            err_bits=f"0x{err:08x}",
            got=[f"0x{w:08x}" for w in got],
            exp=[f"0x{w:08x}" for w in exp],
            cycles=run_cycles,
        )
        return run_cycles
