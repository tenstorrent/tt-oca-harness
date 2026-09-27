# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_sep_secure_tm_test. SEP=1, no Force.

``secure_tm_req_i`` is the TEST_EN strap. The specification latches it into
``secure_tm_o`` once per cold reset -- when SEP fuse sensing is done if SEC_DIS
is not asserted, on chiplet cold-reset release if it is -- and the latched
value is cleared only by a reset (``hw/sys/sep/doc/test_mode.adoc``, "Test
Mode Entry"; ``doc/integrator/src/smu.adoc``, the ``secure_tm_req_i`` bullet).

Each leg is one cold reset. The strap holds one value from before the reset
asserts until the SEP reset is observed asserted and ``sep_fuse_sense_done_o``
is observed low, then takes the value it is to hold at the fuse-sense-done
edge while the reset is still held. ``secure_tm_o`` is required to stay low
from that change until the edge, to carry the changed value after it, and to
ignore a change made after the edge, in both directions.

L1  0 when the reset asserts, 1 at the edge: ``secure_tm_o`` rises to 1 and
    stays 1 when the strap drops afterwards.
L2  1 when the reset asserts, 0 at the edge: the cold reset clears the 1 left
    by L1, ``secure_tm_o`` stays 0 after the edge and when the strap rises
    afterwards.
L3  1 held throughout: ``secure_tm_o`` rises to 1 with no strap change in the
    window.

On the ``+skip_fuse_sense`` path this leaf runs on, ``sep_fuse_sense_done_o``
rises on the first clock after the SEP reset releases, so the fuse-sense-done
edge and cold-reset release are one clock apart and the two windows the
specification names are not told apart here. What the legs bracket is the
sampling instant: after the last strap change under reset, no later than the
observed edge.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

RESET_HOLD_REF_CYCLES = 64
FUSE_DONE_BOUND = 20000
SETTLE_CYCLES = 64
HOLD_CYCLES = 512
EVIDENCE = "CHK-SMU-SECURE-TM"


class smu_sep_secure_tm_seq:
    """The SEP secure-test-mode strap latched at the fuse-sense-done edge of a cold reset."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard

    def _bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    async def _cold_reset(self, through: int, at_edge: int) -> int:
        """One cold reset with the strap at ``through`` as it asserts and ``at_edge`` at the edge.

        Returns the number of clk_smu between the release and the edge.
        """
        dut = self.dut
        sb = self.sb
        before = self._bit("tb_secure_tm")
        dut.tb_secure_tm_req.value = through
        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0
        for _ in range(FUSE_DONE_BOUND):
            await RisingEdge(dut.clk_ref_i)
            if self._bit("sep_fuse_sense_done_o") == 0 and self._bit("obs_sep_rst_n_o") == 0:
                break
        else:
            raise AssertionError(
                f"TIMEOUT cold reset never reached the SEP: bound={FUSE_DONE_BOUND} clk_ref "
                f"sep_fuse_sense_done_o={self._bit('sep_fuse_sense_done_o')} "
                f"obs_sep_rst_n_o={self._bit('obs_sep_rst_n_o')}"
            )
        await ClockCycles(dut.clk_ref_i, RESET_HOLD_REF_CYCLES)
        verb = "clears under" if before else "reads low under"
        sb.expect_eq(
            f"secure_tm_o {verb} cold reset (was {before} before it, strap={through})",
            self._bit("tb_secure_tm"),
            0,
            evidence=EVIDENCE,
        )
        change = (
            f"changes {through} -> {at_edge}" if through != at_edge else f"is held at {at_edge}"
        )
        sb.expect_eq(
            f"the strap {change} with the SEP reset asserted and sep_fuse_sense_done_o low",
            (self._bit("obs_sep_rst_n_o"), self._bit("sep_fuse_sense_done_o")),
            (0, 0),
            evidence=EVIDENCE,
        )
        dut.tb_secure_tm_req.value = at_edge
        pre_edge_high = 0
        pre_edge_samples = 0
        for _ in range(RESET_HOLD_REF_CYCLES):
            await RisingEdge(dut.clk_ref_i)
            pre_edge_high += self._bit("tb_secure_tm")
            pre_edge_samples += 1
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        await self.test.jtag_tap_reset(16)
        for cycle in range(FUSE_DONE_BOUND):
            await RisingEdge(dut.clk_smu_i)
            if self._bit("sep_fuse_sense_done_o"):
                break
            pre_edge_high += self._bit("tb_secure_tm")
            pre_edge_samples += 1
        else:
            raise AssertionError(
                f"TIMEOUT sep_fuse_sense_done_o never rose after release: "
                f"bound={FUSE_DONE_BOUND} clk_smu strap={at_edge}"
            )
        self.log.info(
            "sep_fuse_sense_done_o rose %d clk_smu after release; strap %d as the reset "
            "asserted, %d at the edge; %d samples between the strap change and the edge",
            cycle,
            through,
            at_edge,
            pre_edge_samples,
        )
        sb.expect_eq(
            f"secure_tm_o stays low across the {pre_edge_samples} samples between the strap "
            f"change and the fuse-sense-done edge (strap={at_edge})",
            pre_edge_high,
            0,
            evidence=EVIDENCE,
        )
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        return cycle

    async def _hold(self, want: int, label: str) -> None:
        held = 0
        for _ in range(HOLD_CYCLES):
            await RisingEdge(self.dut.clk_smu_i)
            held += self._bit("tb_secure_tm") == want
        self.sb.expect_eq(label, held, HOLD_CYCLES, evidence=EVIDENCE)

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)

        sb.expect_eq(
            "the bench holds the secure test-mode strap low at bring-up",
            self._bit("tb_secure_tm_req"),
            0,
            evidence=EVIDENCE,
        )

        # L1
        await self._cold_reset(through=0, at_edge=1)
        sb.expect_eq(
            "secure_tm_o carries the 1 present at the fuse-sense-done edge, "
            "not the 0 present when the reset asserted",
            self._bit("tb_secure_tm"),
            1,
            evidence=EVIDENCE,
        )
        dut.tb_secure_tm_req.value = 0
        await self._hold(1, "dropping the strap after the edge does not clear secure_tm_o")

        # L2
        await self._cold_reset(through=1, at_edge=0)
        sb.expect_eq(
            "secure_tm_o carries the 0 present at the fuse-sense-done edge, "
            "not the 1 present when the reset asserted",
            self._bit("tb_secure_tm"),
            0,
            evidence=EVIDENCE,
        )
        dut.tb_secure_tm_req.value = 1
        await self._hold(0, "raising the strap after the edge does not reach secure_tm_o")

        # L3
        await self._cold_reset(through=1, at_edge=1)
        sb.expect_eq(
            "secure_tm_o carries a strap held at 1 through the whole cold reset",
            self._bit("tb_secure_tm"),
            1,
            evidence=EVIDENCE,
        )
