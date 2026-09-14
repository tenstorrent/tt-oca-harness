# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_gpio_multi_sample_test.

Three spaced SAMPLEs of the GPIO pad-output observables, consumed into a real
cross-sample property that a *dead* observable cannot pass.

The checked observable is not the ``tb_gpio_*_any`` aggregate. Those three are
OR-reductions over the whole pad bus (``tb_top.sv``), which also carries
idle-high LSIO pads such as UART TX: they read 1 from reset onward and no
frontdoor stimulus can drive any of them to 0. A cross-sample "it did not move"
compare on them is fail-capable against a moving aggregate but not against a
stuck-at-1, undriven or mis-bound net -- which passes all of them exactly as a
live quiet DUT does, and which no control can distinguish
(``[NEGATIVE-NEEDS-POSITIVE-CONTROL]``). All three are declared in
``env.smc_probe_liveness.UNBACKABLE_PROBES``: the scoreboard reports them
OBSERVED-ONLY and refuses a stated expectation on them.

The property lives on the raw pad-output vectors ``tb_core2pad_o`` /
``tb_core2pad_en_o`` (``tb_top.sv``, per-pad mirrors of the same
``u_dut.u_smc.core2pad*_o`` nets the aggregates reduce). Those *do* move under
real frontdoor GPIO CSR programming, so this sequence:

1. runs ``smc_probe_positive_control.prove_gpio_pad_bus_probe`` first (through
   ``ensure_gpio_pad_bus_control``), which programs GPIO wrap 0 as a TX output
   over SEP_IN AXI, requires exactly one new pad output-enable bit, requires that
   pad's value to track the register 1 -> 0, and requires a bit-for-bit restore of
   both vectors. Every leg is a bounded poll whose expiry is a failure;
2. then takes the three spaced samples. Sample 0 is the reference; samples
   1..N-1 carry its ``core2pad_en_vec`` as ``expect_core2pad_en_vec``, and the
   scoreboard books that exact compare as *checked* evidence because step 1
   credited the probe in this same run.

After the control restores DATA_CTRL nothing in the stimulus can move the pad
output-enable bus, so persistence across the window is a genuine expectation --
and one whose observable has been proven able to change.

Only the output-*enable* vector carries that claim. The pad *value* vector also
carries free-running DUT outputs (the AVSBus clock is ``core2pad_o[49]``,
tb_top.sv:818), so it changes with no GPIO stimulus and an exact cross-sample
expectation on it would be flaky rather than proof -- see
``env.smc_gpio_item.GPIO_STABLE_VECTOR_FIELDS``. It is reported as a diagnostic.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_gpio_item import (
    GPIO_SAMPLE_FIELDS,
    GPIO_STABLE_VECTOR_FIELDS,
    SmcGpioItem,
    SmcGpioOp,
)
from env.smc_probe_liveness import probe_alive, probe_evidence

from .smc_base_test_seq import smc_base_test_seq
from .smc_probe_positive_control import ensure_gpio_pad_bus_control


class smc_gpio_multi_sample_test_seq(smc_base_test_seq):
    SAMPLES = 3
    GAP_REF_CYCLES = 80

    def __init__(self, name: str = "smc_gpio_multi_sample_test_seq") -> None:
        super().__init__(name)
        self.samples: list[SmcGpioItem] = []

    async def body(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        # Positive control FIRST: it is what makes the cross-sample compares
        # below distinguish a quiet pad bus from a dead one. It programs and then
        # restores GPIO0 DATA_CTRL, so it must complete before the reference
        # sample is taken.
        await ensure_gpio_pad_bus_control(self)
        for probe in ("gpio_core2pad_vec", "gpio_core2pad_en_vec"):
            assert probe_alive(probe), (
                f"GPIO multi-sample: {probe} was not credited by the pad-bus "
                f"positive control, so a cross-sample compare on it cannot be "
                f"presented as checked evidence ({probe_evidence(probe)})"
            )
        seen_before = sb.gpio_samples_seen

        for i in range(self.SAMPLES):
            item = SmcGpioItem(f"sample_{i}")
            item.op = SmcGpioOp.SAMPLE
            stated: list[str] = []
            if self.samples:
                # Cross-sample expectation: not a golden==observed lock on the
                # same sample, but the pad-bus state a *previous* sample
                # established under a stimulus that cannot change it. Only the
                # backable vector fields are stated; a stated expectation on an
                # aggregate is refused by the scoreboard.
                ref = self.samples[0]
                for field in GPIO_STABLE_VECTOR_FIELDS:
                    setattr(item, "expect_" + field, getattr(ref, field))
                    stated.append(f"{field}=0x{getattr(ref, field):x}")
            await self.start_item(item)
            await self.finish_item(item)
            # finish_item returns after the driver's ap.write(), so the
            # scoreboard compares above have already run and passed here.
            assert item.resolvable, (
                f"GPIO sample {i}: a tb_gpio_*_any observability output is not "
                f"resolvable (X/Z) {self.GAP_REF_CYCLES * i} clk_ref_i cycles "
                f"after the first sample: {item}"
            )
            assert item.vec_width > 0, (
                f"GPIO sample {i}: the pad-bus vectors (tb_core2pad_o / "
                f"tb_core2pad_en_o) were not sampled, so this test's only "
                f"backable observable is missing: {item}"
            )
            self.samples.append(item)
            if stated:
                # Emitted only for a sample the scoreboard just exact-compared
                # against the reference on the credited pad output-enable vector
                # (a spurious pad-bus change fails it). Sample 0 states no
                # expectation, and its only gate -- resolvability -- cannot fail
                # under a 2-state simulator, so no CHK-
                # token is emitted for it: it is logged below as the reference it
                # is ([EVIDENCE-TOKEN-CONDITIONAL]).
                cocotb.log.info(
                    "CHK-GPIO-MULTI-SAMPLE-MATCHES-REF-%d: %s exact-compared by "
                    "the scoreboard against reference sample 0 on %s, %d "
                    "clk_ref_i cycles later; backed by this run's "
                    "pad-bus positive control (%s)",
                    i,
                    item,
                    ", ".join(stated),
                    i * self.GAP_REF_CYCLES,
                    probe_evidence("gpio_core2pad_en_vec"),
                )
            else:
                cocotb.log.info(
                    "GPIO multi-sample reference (observed only, no stated expectation): %s", item
                )
            if i < self.SAMPLES - 1:
                await ClockCycles(dut.clk_ref_i, self.GAP_REF_CYCLES)

        # The samples are evidence only if they actually reached the scoreboard.
        observed = sb.gpio_samples_seen - seen_before
        assert observed == self.SAMPLES, (
            f"GPIO multi-sample: scoreboard booked {observed} SAMPLE items, "
            f"expected {self.SAMPLES} (mis-bound analysis port would make the "
            f"cross-sample compare vacuous)"
        )

        ref = self.samples[0]
        for i, item in enumerate(self.samples[1:], start=1):
            for field in GPIO_STABLE_VECTOR_FIELDS:
                exp = getattr(ref, field)
                got = getattr(item, field)
                assert got == exp, (
                    f"GPIO {field} changed between sample 0 and sample {i} "
                    f"(0x{exp:x} -> 0x{got:x}) over {i * self.GAP_REF_CYCLES} "
                    f"clk_ref_i cycles, after the pad-bus control restored GPIO0 "
                    f"DATA_CTRL and with no further GPIO CSR programming or pad "
                    f"drive in this test: sample0={ref} sample{i}={item}"
                )
        cocotb.log.info(
            "CHK-GPIO-MULTI-SAMPLE-STABLE: %d samples %d clk_ref_i apart all "
            "held tb_core2pad_en_o=0x%x (%d pads), every leg backed by this "
            "run's pad-bus positive control. NOT checked evidence in this token: "
            "tb_core2pad_o (=0x%x at the reference) carries free-running pad "
            "outputs such as the AVSBus clock on bit 49, and the %d "
            "tb_gpio_*_any OR-aggregates (%d/%d/%d) admit no control at all -- "
            "both are diagnostics only.",
            self.SAMPLES,
            self.GAP_REF_CYCLES,
            ref.core2pad_en_vec,
            ref.vec_width,
            ref.core2pad_vec,
            len(GPIO_SAMPLE_FIELDS),
            ref.core2pad_any,
            ref.core2pad_en_any,
            ref.pad2core_en_any,
        )
