# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_sep_secure_tm_test. SEP=1, no Force.

``secure_tm_req_i`` is a strap, not a level that reaches ``secure_tm_o``: the
SEP eFuse wrapper latches it once per cold reset. The RTL states both windows
(``sep_efuse_wrapper.sv``)::

    else if (security_disable && (reset_cycle_cnt == 2'd1)) secure_tm_n0_scan <= secure_tm_req_i;
    else if (fuse_sense_done_posedge)                       secure_tm_n0_scan <= secure_tm_req_i;

and ``assign secure_tm_o = secure_tm_n0_scan;``.

So the claim under test is a sample-and-hold, and the test is a pair of cold
resets with the strap held at a different value across each:

S1  With the strap low, ``secure_tm_o`` is low after a cold reset that has
    re-run the SEP fuse sense, and stays low while the strap is raised
    afterwards -- which is what separates a latch from a wire.
S2  Taking the strap through the next cold reset latches it, so
    ``secure_tm_o`` comes up high, and is then held while the strap drops.
S3  A third cold reset with the strap low clears it again.

``sep_fuse_sense_done_o`` is the wrapper output whose rising edge is the
sampling instant, so each leg waits for it to fall and rise rather than
guessing a delay.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

RESET_HOLD_REF_CYCLES = 64
FUSE_DONE_BOUND = 20000
SETTLE_CYCLES = 64
HOLD_CYCLES = 512


class smu_sep_secure_tm_seq:
    """The SEP secure-test-mode strap latched across cold reset."""

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

    async def _cold_reset_with_strap(self, strap: int) -> int:
        """One cold reset with the strap held; returns the fuse-sense latency."""
        dut = self.dut
        dut.tb_secure_tm_req.value = strap
        dut.rst_cold_ni.value = 0
        dut.jtag_trst.value = 0
        for cycle in range(FUSE_DONE_BOUND):
            await RisingEdge(dut.clk_ref_i)
            if self._bit("sep_fuse_sense_done_o") == 0:
                break
        else:
            raise AssertionError(
                f"TIMEOUT sep_fuse_sense_done_o never cleared under cold reset: "
                f"bound={FUSE_DONE_BOUND} clk_ref"
            )
        await ClockCycles(dut.clk_ref_i, RESET_HOLD_REF_CYCLES)
        self.sb.expect_eq(
            f"secure_tm_o clears under cold reset (strap={strap})",
            self._bit("tb_secure_tm"),
            0,
            evidence="CHK-SMU-SECURE-TM",
        )
        dut.rst_cold_ni.value = 1
        dut.jtag_trst.value = 1
        await self.test.jtag_tap_reset(16)
        for cycle in range(FUSE_DONE_BOUND):
            await RisingEdge(dut.clk_smu_i)
            if self._bit("sep_fuse_sense_done_o"):
                break
        else:
            raise AssertionError(
                f"TIMEOUT sep_fuse_sense_done_o never rose after release: "
                f"bound={FUSE_DONE_BOUND} clk_smu strap={strap}"
            )
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        return cycle

    async def _hold(self, name: str, want: int, label: str, evidence: str) -> None:
        held = 0
        for _ in range(HOLD_CYCLES):
            await RisingEdge(self.dut.clk_smu_i)
            held += self._bit(name) == want
        self.sb.expect_eq(label, held, HOLD_CYCLES, evidence=evidence)

    async def run(self) -> None:
        dut = self.dut
        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)

        self.sb.expect_eq(
            "the bench holds the secure test-mode strap low at bring-up",
            self._bit("tb_secure_tm_req"),
            0,
            evidence="CHK-SMU-SECURE-TM",
        )

        # S1: strap low across a cold reset, and raising it afterwards must not
        # reach the output.
        cycles = await self._cold_reset_with_strap(0)
        self.log.info("fuse sense completed %d clk_smu after release (strap low)", cycles)
        self.sb.expect_eq(
            "secure_tm_o stays low when the strap was low at the sampling edge",
            self._bit("tb_secure_tm"),
            0,
            evidence="CHK-SMU-SECURE-TM",
        )
        dut.tb_secure_tm_req.value = 1
        await self._hold(
            "tb_secure_tm",
            0,
            "raising the strap outside the sampling window does not reach secure_tm_o",
            "CHK-SMU-SECURE-TM",
        )

        # S2: the same strap value taken through a cold reset is latched.
        cycles = await self._cold_reset_with_strap(1)
        self.log.info("fuse sense completed %d clk_smu after release (strap high)", cycles)
        self.sb.expect_eq(
            "secure_tm_o carries the strap sampled at the fuse-sense edge",
            self._bit("tb_secure_tm"),
            1,
            evidence="CHK-SMU-SECURE-TM",
        )
        dut.tb_secure_tm_req.value = 0
        await self._hold(
            "tb_secure_tm",
            1,
            "dropping the strap outside the sampling window does not clear secure_tm_o",
            "CHK-SMU-SECURE-TM",
        )

        # S3: and the next cold reset re-samples it low.
        await self._cold_reset_with_strap(0)
        self.sb.expect_eq(
            "the next cold reset re-samples the strap and clears secure_tm_o",
            self._bit("tb_secure_tm"),
            0,
            evidence="CHK-SMU-SECURE-TM",
        )
