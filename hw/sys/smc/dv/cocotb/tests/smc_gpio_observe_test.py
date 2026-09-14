# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM GPIO observe test.

Samples the tb_top GPIO observability outputs: the three OR-of-vector aggregates
(``tb_gpio_core2pad_any`` / ``tb_gpio_core2pad_en_any`` /
``tb_gpio_pad2core_en_any``) and the raw pad-output vectors they reduce
(``tb_core2pad_o`` / ``tb_core2pad_en_o``).

**This testcase's checker is the cross-sample pad-bus compare, and nothing else.**
Resolvability is a precondition, not the contract: under Verilator, a 2-state
simulator, ``sig.value.is_resolvable`` cannot be False, so ``assert
item.resolvable`` has no FAIL-ON path there.

The three aggregates are **not** checked here and carry no claim. They are
OR-reductions over the whole pad bus, which also carries idle-high LSIO pads (e.g.
UART TX): they read 1 from reset onward and no frontdoor stimulus can drive any of
them to 0, so a stuck-at-1, undriven or mis-bound net reads exactly like the real
aggregate and no positive control for them can exist
(``[NEGATIVE-NEEDS-POSITIVE-CONTROL]``). All three are declared in
``env.smc_probe_liveness.UNBACKABLE_PROBES``; the scoreboard logs their value as
an OBSERVED-ONLY diagnostic and refuses any stated expectation on them.

The fail-capable property is on the raw vectors instead, and it is backed in the
same run. ``SmcGpioAggregateStabilitySeq`` first runs
``smc_probe_positive_control.prove_gpio_pad_bus_probe`` -- GPIO wrap 0 programmed
as a register-driven TX output over SEP_IN AXI, requiring exactly one new pad
output-enable bit, that pad's value tracking the register 1 -> 0, and a
bit-for-bit restore of both vectors, every leg a bounded poll whose expiry fails
-- and then dispatches two further samples carrying the reference sample's
output-enable vector as ``expect_core2pad_en_vec``. Because the control credited
that probe, the scoreboard books the exact compare as checked evidence: a pad
output-enable bus that moved when it should not, or that cannot move at all,
fails. The expectation comes from an *earlier* sample under a stimulus that cannot
change it -- not from the sample being checked.

The pad *value* vector is reported but not compared across samples: it carries
free-running DUT outputs (the AVSBus clock is ``core2pad_o[49]``, tb_top.sv:818),
so an exact cross-sample expectation on it would be flaky rather than proof.

Per-pad *level* behaviour under GPIO CSR programming remains
``smc_gpio_output_driveback_test``'s proof; this testcase proves the observability
path exists, moves, and then holds.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_observe_test_seq import smc_gpio_observe_test_seq
from seq_lib.smc_probe_positive_control import SmcGpioAggregateStabilitySeq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_observe_test(smc_base_test):
    required_evidence = (
        "CHK-GPIO-PAD-BUS-STABLE",
        "CHK-PROBE-CONTROLS",
        "CHK-PROBE-GPIO-PAD-BUS-ALIVE",
    )
    min_evidence = 1

    # Number of further samples exact-compared against the reference sample, and
    # their spacing. Two samples over 160 clk_ref_i cycles keep the window long
    # enough for a spurious toggle to be visible without lengthening the run.
    STABILITY_SAMPLES = 2
    STABILITY_GAP_REF_CYCLES = 80

    async def run_scenario(self) -> None:
        seq = smc_gpio_observe_test_seq("gpio_observe_seq")
        await self.start_seq(seq, self.env.gpio_agent.sequencer)
        # Consume the reference sample the leaf sequence retained: it is the
        # right-hand side of this testcase's only fail-capable DUT assertion.
        stability = SmcGpioAggregateStabilitySeq(
            "gpio_observe_stability_seq",
            reference=seq.sample,
            samples=self.STABILITY_SAMPLES,
            gap_ref_cycles=self.STABILITY_GAP_REF_CYCLES,
        )
        await self.start_seq(stability, self.env.gpio_agent.sequencer)
