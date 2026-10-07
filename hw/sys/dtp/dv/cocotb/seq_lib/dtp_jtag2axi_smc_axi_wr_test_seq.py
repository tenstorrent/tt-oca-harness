# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC fabric JTAG2AXI write-side scenarios."""

from __future__ import annotations

import random

from env.dtp_types import DtpJtag2AxiOp, DtpJtag2AxiStatus

from .dtp_jtag2axi_base_test_seq import AXI_BEAT_BYTES, dtp_jtag2axi_base_test_seq

DEFAULT_AXI_ADDR = 0x40
DEFAULT_AXI_DATA = 0x0123_4567_89AB_CDEF


class dtp_jtag2axi_smc_axi_wr_test_seq(dtp_jtag2axi_base_test_seq):
    """Run one focused SMC fabric JTAG2AXI write-side scenario.

    Each scenario is organized as reset/setup, stimulus, observe/check, cleanup,
    and summary. Random choices are made from the deterministic sequence RNG so
    failures can be replayed with the runner seed.
    """

    def __init__(
        self,
        name: str = "dtp_jtag2axi_smc_axi_wr_test_seq",
        *,
        scenario: str = "single_write",
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self.scenario = scenario
        self.status = DtpJtag2AxiStatus.SUCCESS
        self.operation_count = 0

    def bus_ledger_target(self) -> str | None:
        return None if "security_gating" in self.scenario else "smc_axi"

    def directed_cases(self) -> list[tuple[int, int, int, int]]:
        """Return deterministic address, size, data, wstrb cases.

        Covers all legal SMC fabric single-op SIZE encodings and a walking byte-lane
        pattern. Addresses are spaced by 0x40 to avoid accidental overlap.
        """
        cases = []
        for idx, size in enumerate((0, 1, 2, 3)):
            addr = DEFAULT_AXI_ADDR + (idx * 0x40)
            data = (DEFAULT_AXI_DATA ^ (0x1111_1111_1111_1111 * idx)) & self.data_mask(size)
            wstrb = self.full_wstrb(size)
            cases.append((addr, size, data, wstrb))
        cases.append((DEFAULT_AXI_ADDR + 0x140, 3, 0xA5A5_5A5A_C3C3_3C3C, 0x55))
        cases.append((DEFAULT_AXI_ADDR + 0x180, 3, 0x5A5A_A5A5_3C3C_C3C3, 0xAA))
        # The strobe classes below a full beat at every size: no lane, the top
        # lane alone (2 bytes and wider), and the low half of a 4-byte beat.
        for size in (0, 1, 2, 3):
            data = (DEFAULT_AXI_DATA ^ (0x2222_2222_2222_2222 * size)) & self.data_mask(size)
            cases.append((DEFAULT_AXI_ADDR + 0x200 + size * 0x40, size, data, 0x00))
            if size > 0:
                top_lane = 1 << (self.size_bytes(size) - 1)
                cases.append((DEFAULT_AXI_ADDR + 0x400 + size * 0x40, size, data, top_lane))
        cases.append((DEFAULT_AXI_ADDR + 0x600, 2, 0x0BAD_F00D, 0x03))
        # Seeded per-pass random cases on top of the deterministic sweep:
        # every loop drives different address/size/data/strobe values.
        rng = self.rng("smc_axi_directed_cases")
        for _ in range(self.random_count):
            size = rng.choice([0, 1, 2, 3])
            addr = self.random_upper_addr("smc_axi", rng) | self.random_target_aligned_addr(
                "smc_axi", rng
            )
            data = rng.getrandbits(64) & self.data_mask(size)
            wstrb = rng.randint(1, self.full_wstrb(size))
            cases.append((addr, size, data, wstrb))
        return cases

    async def run_single_write(self) -> None:
        self.log_banner("SMC_AXI_SINGLE_OP Directed Write")
        await self.reset_tap()
        self.log_step(1, "Run deterministic size and strobe sweep")
        cases = self.directed_cases()
        for idx, (addr, size, data, wstrb) in enumerate(cases, start=1):
            self.log_iteration(
                idx,
                len(cases),
                "single write addr=0x%08x size=%d data=0x%x wstrb=0x%02x",
                addr,
                size,
                data,
                wstrb,
            )
            self.status, _ = await self.write_target_single_and_check(
                "smc_axi",
                addr,
                data,
                size=size,
                wstrb=wstrb,
                context=f"single_write#{idx}",
            )
            self.operation_count += 1
        # SINGLE_OP status polls shift a NOP image. Neither they nor the
        # SINGLE_OP completions reach the series status or its BUSY_OR_FULL flag.
        self.log_step(2, "Capture SERIES_CTRL after SINGLE_OP polls")
        _, _, _, _, status = await self.read_series_ctrl(size=3)
        self.check_bridge_status("smc_axi", status, context="single_write.series_ctrl")
        self.status = status

    async def run_single_write_data_verify(self) -> None:
        self.log_banner("SMC_AXI_SINGLE_OP Write With Readback")
        await self.reset_tap()
        self.log_step(1, "Write non-trivial data, then read it back through JTAG2AXI")
        self.status, _, _ = await self.write_neighbour_then_read(
            "smc_axi",
            DEFAULT_AXI_ADDR + 0x200,
            self.rng("smc_axi_write_readback"),
            context="write_readback",
        )
        self.operation_count += 3

    async def run_series_write_incr(self) -> None:
        self.log_banner("SMC_AXI_SERIES_DATA_INCR Write Sweep")
        await self.reset_tap()
        rng = self.rng("series_write_incr")
        size = 3
        stride = self.size_bytes(size)
        beats = max(2, min(self.random_count, 6))
        base = self.random_series_base("smc_axi", rng, span=beats * stride, straddle=True)
        self.log_step(1, "Program SERIES_CTRL for incrementing writes")
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size)
        for idx in range(beats):
            addr = base + (idx * stride)
            data = rng.getrandbits(64) & self.data_mask(size)
            self.log_iteration(
                idx + 1,
                beats,
                "series incr write addr=0x%014x data=0x%x",
                addr,
                data,
            )
            await self.series_write_beat(
                "smc_axi", data, addr=addr, size=size, increment=True, context=f"series_incr#{idx}"
            )
            self.operation_count += 1
        self.status = await self.check_series_end(
            "smc_axi", base + beats * stride, size=size, context="series_incr"
        )

    async def run_series_write_incr_narrow(self) -> None:
        self.log_banner("SMC_AXI_SERIES_DATA_INCR 32-bit Write Sweep at Beat Offset +4")
        await self.reset_tap()
        rng = self.rng("series_write_incr_narrow")
        size = 2
        stride = self.size_bytes(size)
        beats = max(2, min(self.random_count, 6))
        # The whole 64-bit beats the stream's words touch.
        span = (4 + beats * stride + AXI_BEAT_BYTES - 1) // AXI_BEAT_BYTES * AXI_BEAT_BYTES
        base = self.random_series_base("smc_axi", rng, span=span, straddle=True) + 4
        # The low word of the first beat's slot is outside the stream; a
        # sentinel there catches a beat driven on the wrong lanes.
        sentinel_addr = base - stride
        sentinel = rng.getrandbits(8 * stride)
        self.write_mem_int(sentinel_addr, sentinel, size)
        self.log_step(1, "Program SERIES_CTRL for 32-bit incrementing writes at +4")
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size)
        words: list[tuple[int, int]] = []
        for idx in range(beats):
            addr = base + (idx * stride)
            data = rng.getrandbits(64) & self.data_mask(size)
            # Expected strobes: a narrow beat lands on the lanes its address selects.
            wstrb = self.full_wstrb(size) << (addr % AXI_BEAT_BYTES)
            self.log_iteration(
                idx + 1,
                beats,
                "series incr narrow write addr=0x%014x data=0x%x wstrb=0x%02x",
                addr,
                data,
                wstrb,
            )
            self.scoreboard_arm_strobes("smc_axi", wstrb, addr, context=f"series_incr_narrow#{idx}")
            await self.series_write_beat(
                "smc_axi",
                data,
                addr=addr,
                size=size,
                increment=True,
                context=f"series_incr_narrow#{idx}",
            )
            # A NOP SERIES_CTRL capture leaves the latched stream running.
            await self.check_series_end(
                "smc_axi", addr + stride, size=size, context=f"series_incr_narrow.beat#{idx}"
            )
            words.append((addr, data))
            self.operation_count += 1
        self.log_step(2, "Verify the stream footprint: every word intact, sentinel untouched")
        self._check_narrow_footprint(sentinel_addr, sentinel, words, size=size)
        self.status = await self.check_series_end(
            "smc_axi", base + beats * stride, size=size, context="series_incr_narrow"
        )

    def _check_narrow_footprint(
        self, sentinel_addr: int, sentinel: int, words: list[tuple[int, int]], *, size: int
    ) -> None:
        """After the stream: no beat spilled onto the sentinel word or a neighbour's word."""
        self.check_target_word(
            "smc_axi", sentinel_addr, sentinel, size=size, context="series_incr_narrow.sentinel"
        )
        for idx, (addr, data) in enumerate(words):
            self.check_target_word(
                "smc_axi", addr, data, size=size, context=f"series_incr_narrow.final#{idx}"
            )

    async def run_series_write_no_incr(self) -> None:
        self.log_banner("SMC_AXI_SERIES_DATA_NO_INCR Write Sweep")
        await self.reset_tap()
        rng = self.rng("series_write_no_incr")
        size = 3
        beats = max(2, min(self.random_count, 6))
        addr = self.random_upper_addr("smc_axi", rng) | self.random_target_aligned_addr(
            "smc_axi", rng
        )
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, addr, size=size)
        for idx in range(beats):
            data = rng.getrandbits(64) & self.data_mask(size)
            self.log_iteration(
                idx + 1,
                beats,
                "series no-incr write addr=0x%014x data=0x%x",
                addr,
                data,
            )
            await self.series_write_beat(
                "smc_axi",
                data,
                addr=addr,
                size=size,
                increment=False,
                context=f"series_no_incr#{idx}",
            )
            self.operation_count += 1
        self.status = await self.check_series_end(
            "smc_axi", addr, size=size, context="series_no_incr"
        )

    async def run_series_write_incr_with_error(self) -> None:
        self.log_banner("SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS Write Mode")
        await self.reset_tap()
        rng = self.rng("series_write_with_status")
        plan = self.arm_series_status_fault(
            self.plan_series_status("smc_axi", rng), rng, read=False
        )
        words = [rng.getrandbits(64) & self.data_mask(plan.size) for _ in plan.increments]
        self.log_step(
            1,
            "Write the with-status series; beat %d returns %s",
            plan.fault_idx,
            plan.expected.name,
        )
        await self.run_series_status_write(plan, words, context="series_status")
        self.log_step(2, "Recover with a legal single write outside the stream")
        self.status = await self.verify_target_recovery(
            "smc_axi",
            addr=self.series_status_recovery_addr(plan),
            data=rng.getrandbits(64),
            read=False,
            context="series_status",
        )
        self.operation_count += plan.beats + 1
        self.emit_series_status_nonvacuity(
            "series_write_incr_with_error", plan, self.operation_count
        )

    async def run_random_ops(self) -> None:
        self.log_banner("SMC_AXI_SINGLE_OP Randomized Writes")
        await self.reset_tap()
        rng = self.rng("random_write_ops")
        image: dict[int, int] = {}
        for idx in range(1, self.random_count + 1):
            size = rng.choice([0, 1, 2, 3])
            offset = rng.randrange(0, AXI_BEAT_BYTES >> size) << size
            addr = self.random_upper_addr("smc_axi", rng) | (
                self.random_target_aligned_addr("smc_axi", rng) + offset
            )
            data = rng.getrandbits(64) & self.data_mask(size)
            wstrb = rng.randint(1, self.full_wstrb(size))
            self.log_iteration(
                idx,
                self.random_count,
                "random write addr=0x%014x size=%d data=0x%x wstrb=0x%02x",
                addr,
                size,
                data,
                wstrb,
            )
            self.snapshot_target_word("smc_axi", image, addr, size)
            self.status, _ = await self.write_target_single_and_check(
                "smc_axi",
                addr,
                data,
                size=size,
                wstrb=wstrb,
                context=f"random_write#{idx}",
            )
            self.image_write("smc_axi", image, addr, data, wstrb=wstrb, size=size)
            self.operation_count += 1
        self.check_memory_image("smc_axi", image, context="random_write")

    async def run_write_security_gating(self) -> None:
        self.log_banner("SMC_AXI_SINGLE_OP Write Security Gating")
        await self.reset_tap()
        addr = DEFAULT_AXI_ADDR + 0x300
        # One payload serves the baseline, gated, and restore writes.
        data = self.rng("smc_axi_write_gate").getrandbits(64)
        writes_start = self.port_history("smc_axi").count(read=False)
        self.log_step(1, "Establish baseline write and AXI activity")
        before = await self.target_activity_counts("smc_axi")
        await self.write_target_single_and_check("smc_axi", addr, data, context="gate.baseline")
        await self.expect_target_activity(
            "smc_axi", before=before, read=False, context="gate.baseline"
        )

        # Two assert/release passes of the one direct disable prove the gate
        # is repeatable, not a one-shot POR effect.
        image_rng = self.rng("smc_axi_write_gate_image")
        for idx in (1, 2):
            self.log_step(idx + 1, "Gate SMC fabric write with smc_jtag2axi (pass %d)", idx)
            await self._gate_pass(idx, addr, data, image_rng)
        self.log_step(4, "Gate SMC fabric write with series beats queued behind one on the bus")
        await self.run_queued_write_drop(
            "smc_axi",
            self.rng("smc_axi_queued_drop"),
            addr=addr + 0x100,
            context="gate.queued_drop",
        )
        self.status = await self.verify_target_recovery(
            "smc_axi",
            addr=addr + 0x140,
            data=data ^ 0xA5A5,
            read=False,
            context="gate.queued_drop",
        )
        writes = self.port_history("smc_axi").count(read=False) - writes_start
        self.emit_nonvacuity(
            "smc_axi",
            writes >= 3,
            context=(
                f"gate.writes source=responder_burst_counts write_bursts={writes} "
                f"sanctioned>=3 (baseline+2 restores)"
            ),
        )

    async def _gate_pass(self, idx: int, addr: int, data: int, image_rng: random.Random) -> None:
        """One assert/release pass: gated attempt, release without replay, sanctioned restore."""
        bit_name = f"smc_jtag2axi_pass{idx}"
        # A full-strobe gated write over a sentinel: a leaked request
        # overwrites it. The gated write never reaches the bus, so it arms no
        # strobe credit.
        gate_before = await self.gated_attempt(
            "smc_axi",
            DtpJtag2AxiOp.WRITE,
            addr + (idx * AXI_BEAT_BYTES),
            data=data,
            image_rng=image_rng,
            context=f"gate.{bit_name}",
            sentinel=0x5EA1_0000_0000_0000 | idx,
        )
        self.status = await self.restore_after_gate(
            "smc_axi",
            read=False,
            addr=addr + (idx * 0x40),
            data=data ^ idx,
            gate_before=gate_before,
            context=f"gate.{bit_name}",
        )
        self.operation_count += 1

    async def body(self) -> None:
        await self.enable_all_debug()
        scenarios = {
            "single_write": self.run_single_write,
            "single_write_data_verify": self.run_single_write_data_verify,
            "series_write_incr": self.run_series_write_incr,
            "series_write_incr_narrow": self.run_series_write_incr_narrow,
            "series_write_no_incr": self.run_series_write_no_incr,
            "series_write_incr_with_error": self.run_series_write_incr_with_error,
            "random_ops": self.run_random_ops,
            "write_security_gating": self.run_write_security_gating,
        }
        if self.scenario not in scenarios:
            raise ValueError(f"unknown write-side JTAG2AXI scenario {self.scenario!r}")
        await scenarios[self.scenario]()
        await self.enable_all_debug()
        self.log_summary(
            "SMC fabric write-side scenario complete",
            scenario=self.scenario,
            operations=self.operation_count,
            status=DtpJtag2AxiStatus(self.status).name,
        )
