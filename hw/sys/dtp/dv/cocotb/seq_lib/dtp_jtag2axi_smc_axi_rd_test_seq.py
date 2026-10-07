# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC fabric JTAG2AXI read-side scenarios."""

from __future__ import annotations

from env.dtp_types import DtpJtag2AxiOp, DtpJtag2AxiStatus

from .dtp_jtag2axi_base_test_seq import AXI_BEAT_BYTES, dtp_jtag2axi_base_test_seq

DEFAULT_AXI_ADDR = 0x40
DEFAULT_AXI_DATA = 0x0123_4567_89AB_CDEF


class dtp_jtag2axi_smc_axi_rd_test_seq(dtp_jtag2axi_base_test_seq):
    """Run one focused SMC fabric JTAG2AXI read-side scenario."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_smc_axi_rd_test_seq",
        *,
        scenario: str = "single_write_read",
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self.scenario = scenario
        self.status = DtpJtag2AxiStatus.SUCCESS
        self.rdata = 0
        self.data = DEFAULT_AXI_DATA
        self.operation_count = 0

    def bus_ledger_target(self) -> str | None:
        return None if "security_gating" in self.scenario else "smc_axi"

    async def run_single_write_read(self) -> None:
        self.log_banner("SMC_AXI_SINGLE_OP Single Write-Read")
        await self.reset_tap()
        self.status, self.rdata, self.data = await self.write_neighbour_then_read(
            "smc_axi",
            DEFAULT_AXI_ADDR + 0x400,
            self.rng("smc_axi_single_wr_rd"),
            context="single_wr_rd",
        )
        self.operation_count += 3

    async def run_series_write_read_incr(self) -> None:
        self.log_banner("SMC_AXI Series Write-Read Incrementing")
        await self.reset_tap()
        rng = self.rng("series_read_incr")
        size = 3
        stride = self.size_bytes(size)
        beats = max(2, min(self.random_count, 6))
        base = self.random_series_base("smc_axi", rng, span=beats * stride, straddle=True)
        expected = []
        self.log_step(1, "Write incrementing series")
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size)
        for idx in range(beats):
            data = rng.getrandbits(64) & self.data_mask(size)
            expected.append(data)
            await self.series_write_beat(
                "smc_axi",
                data,
                addr=base + idx * stride,
                size=size,
                increment=True,
                context=f"series_wr_rd_incr.write#{idx}",
            )
        self.log_step(2, "Read incrementing series back")
        for idx, exp in enumerate(expected):
            addr = base + idx * stride
            obs = await self.series_read_beat(
                "smc_axi",
                addr=addr,
                size=size,
                increment=True,
                context=f"series_wr_rd_incr.read#{idx}",
            )
            self.log_iteration(idx + 1, beats, "series read incr addr=0x%014x obs=0x%x", addr, obs)
            self.check_bridge_rdata(
                "smc_axi", obs, exp, context=f"series_wr_rd_incr.rdata#{idx} addr=0x{addr:x}"
            )
            self.operation_count += 1
        # The last primed incrementing read advanced the series address by
        # one stride past the last beat.
        self.status = await self.check_series_end(
            "smc_axi", addr + stride, size=size, context="series_wr_rd_incr.final"
        )

    async def run_series_write_read_incr_narrow(self) -> None:
        self.log_banner("SMC_AXI Series Write-Read 32-bit Incrementing at Beat Offset +4")
        await self.reset_tap()
        rng = self.rng("series_read_incr_narrow")
        size = 2
        stride = self.size_bytes(size)
        beats = max(2, min(self.random_count, 6))
        # The whole 64-bit beats the stream's words touch.
        span = (4 + beats * stride + AXI_BEAT_BYTES - 1) // AXI_BEAT_BYTES * AXI_BEAT_BYTES
        base = self.random_series_base("smc_axi", rng, span=span, straddle=True) + 4
        # A read returns the whole beat, which the reference model predicts
        # from its shadow at the full address: whole-beat preloads give every
        # beat the stream touches a known word on the lanes it does not write.
        first_beat = base - base % AXI_BEAT_BYTES
        for beat in range(first_beat, base + beats * stride, AXI_BEAT_BYTES):
            self.write_mem_int(beat, rng.getrandbits(64), 3)
        expected = []
        self.log_step(1, "Write 32-bit incrementing series at +4")
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size)
        for idx in range(beats):
            data = rng.getrandbits(64) & self.data_mask(size)
            expected.append(data)
            addr = base + idx * stride
            await self.series_write_beat(
                "smc_axi",
                data,
                addr=addr,
                size=size,
                increment=True,
                context=f"series_wr_rd_incr_narrow.write#{idx}",
            )
            # A NOP SERIES_CTRL capture leaves the latched stream running.
            await self.check_series_end(
                "smc_axi", addr + stride, size=size, context=f"series_wr_rd_incr_narrow.write#{idx}"
            )
        self.log_step(2, "Read 32-bit incrementing series back")
        for idx, exp in enumerate(expected):
            addr = base + idx * stride
            obs = await self.series_read_beat(
                "smc_axi",
                addr=addr,
                size=size,
                increment=True,
                context=f"series_wr_rd_incr_narrow.read#{idx}",
            )
            self.log_iteration(
                idx + 1, beats, "series read incr narrow addr=0x%014x obs=0x%x", addr, obs
            )
            self.check_bridge_rdata(
                "smc_axi", obs, exp, context=f"series_wr_rd_incr_narrow.rdata#{idx} addr=0x{addr:x}"
            )
            # The primed read advanced the series address by one stride.
            self.status = await self.check_series_end(
                "smc_axi", addr + stride, size=size, context=f"series_wr_rd_incr_narrow.read#{idx}"
            )
            self.operation_count += 1

    async def run_series_write_read_no_incr(self) -> None:
        self.log_banner("SMC_AXI Series Write-Read No-Increment")
        await self.reset_tap()
        rng = self.rng("series_read_no_incr")
        size = 3
        beats = max(2, min(self.random_count, 6))
        addr = self.random_upper_addr("smc_axi", rng) | self.random_target_aligned_addr(
            "smc_axi", rng
        )
        values = [rng.getrandbits(64) & self.data_mask(size) for _ in range(beats)]
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, addr, size=size)
        for idx, data in enumerate(values, start=1):
            self.log_iteration(
                idx, beats, "series no-incr write addr=0x%014x data=0x%x", addr, data
            )
            await self.series_write_beat(
                "smc_axi",
                data,
                addr=addr,
                size=size,
                increment=False,
                context=f"series_wr_rd_no_incr.write#{idx}",
            )
        self.status = await self.series_reread_fixed(
            "smc_axi",
            addr,
            last_word=values[-1],
            beats=beats,
            rng=rng,
            context="series_wr_rd_no_incr",
        )
        self.operation_count += beats

    async def run_series_write_read_incr_with_error(self) -> None:
        self.log_banner("SMC_AXI Series Write-Read With Error-Status Mode")
        await self.reset_tap()
        rng = self.rng("series_read_with_status")
        plan = self.plan_series_status("smc_axi", rng)
        words = [rng.getrandbits(64) & self.data_mask(plan.size) for _ in plan.increments]
        self.log_step(1, "Write the with-status series without a fault")
        await self.run_series_status_write(plan, words, context="series_wr_rd_status.write")
        plan = self.arm_series_status_fault(plan, rng, read=True)
        self.log_step(
            2, "Read the series back; beat %d returns %s", plan.fault_idx, plan.expected.name
        )
        await self.run_series_status_read(
            plan, plan.final_words(words), context="series_wr_rd_status.read"
        )
        self.log_step(3, "Recover with a legal single read outside the stream")
        self.status = await self.verify_target_recovery(
            "smc_axi",
            addr=self.series_status_recovery_addr(plan),
            data=rng.getrandbits(64),
            read=True,
            context="series_wr_rd_status",
        )
        self.operation_count += 2 * plan.beats + 1
        self.emit_series_status_nonvacuity(
            "series_write_read_incr_with_error", plan, self.operation_count
        )

    async def run_read_random_ops(self) -> None:
        self.log_banner("SMC_AXI_SINGLE_OP Randomized Reads")
        await self.reset_tap()
        rng = self.rng("random_read_ops")
        # Every pass reads each transfer size once before the drawn sizes.
        reads = 4 + self.random_count
        for idx in range(1, reads + 1):
            size = idx - 1 if idx <= 4 else rng.choice([0, 1, 2, 3])
            beat = self.random_upper_addr("smc_axi", rng) | self.random_target_aligned_addr(
                "smc_axi", rng
            )
            offset = rng.randrange(0, AXI_BEAT_BYTES >> size) << size
            addr = beat + offset
            # Whole-beat preload: the read returns the whole beat, and the
            # reference model predicts it from its shadow at the full address.
            word = rng.getrandbits(64)
            self.write_mem_int(beat, word, 3)
            data = (word >> (8 * offset)) & self.data_mask(size)
            self.log_iteration(
                idx,
                reads,
                "random read addr=0x%014x size=%d data=0x%x",
                addr,
                size,
                data,
            )
            self.status, self.rdata = await self.read_target_single_and_check(
                "smc_axi",
                addr,
                data,
                size=size,
                context=f"random_read#{idx}",
            )
            self.data = data
            self.operation_count += 1

    async def run_read_security_gating(self, *, require_no_activity_only: bool = False) -> None:
        title = (
            "SMC_AXI Read Security Gating No-Activity"
            if require_no_activity_only
            else "SMC_AXI Read Security Gating"
        )
        self.log_banner(title)
        await self.reset_tap()
        addr = DEFAULT_AXI_ADDR + 0x500
        # One payload serves the baseline and restore reads.
        data = self.rng("smc_axi_read_gate").getrandbits(64)
        self.write_mem_int(addr, data, 3)
        reads_start = self.port_history("smc_axi").count(read=True)
        self.log_step(1, "Establish baseline read and AXI activity")
        before = await self.target_activity_counts("smc_axi")
        self.status, _ = await self.read_target_single_and_check(
            "smc_axi", addr, data, context="read_gate.baseline"
        )
        await self.expect_target_activity(
            "smc_axi", before=before, read=True, context="read_gate.baseline"
        )

        # Two assert/release passes of the one direct disable prove the gate
        # is repeatable, not a one-shot POR effect.
        image_rng = self.rng("smc_axi_read_gate_image")
        for idx in (1, 2):
            bit_name = f"smc_jtag2axi_pass{idx}"
            self.log_step(idx + 1, "Gate SMC fabric read with smc_jtag2axi (pass %d)", idx)
            gate_before = await self.gated_attempt(
                "smc_axi",
                DtpJtag2AxiOp.READ,
                addr + (idx * AXI_BEAT_BYTES),
                data=0,
                image_rng=image_rng,
                context=f"read_gate.{bit_name}",
            )
            self.status = await self.restore_after_gate(
                "smc_axi",
                read=True,
                addr=addr,
                data=data,
                gate_before=gate_before,
                context=f"read_gate.{bit_name}",
            )
            self.operation_count += 1
        # The read counts that stayed flat while gated move for real traffic,
        # so the no-activity evidence cannot pass on a dead or tied-off bus.
        reads = self.port_history("smc_axi").count(read=True) - reads_start
        self.emit_nonvacuity(
            "smc_axi",
            reads >= 3,
            context=(
                f"read_gate.reads source=responder_burst_counts read_bursts={reads} "
                f"sanctioned>=3 (baseline+2 restores)"
            ),
        )

    async def body(self) -> None:
        await self.enable_all_debug()
        scenarios = {
            "single_write_read": self.run_single_write_read,
            "series_write_read_incr": self.run_series_write_read_incr,
            "series_write_read_incr_narrow": self.run_series_write_read_incr_narrow,
            "series_write_read_no_incr": self.run_series_write_read_no_incr,
            "series_write_read_incr_with_error": self.run_series_write_read_incr_with_error,
            "read_random_ops": self.run_read_random_ops,
            "read_security_gating": self.run_read_security_gating,
            "read_security_gating_no_axi_activity": lambda: self.run_read_security_gating(
                require_no_activity_only=True,
            ),
        }
        if self.scenario not in scenarios:
            raise ValueError(f"unknown read-side JTAG2AXI scenario {self.scenario!r}")
        await scenarios[self.scenario]()
        await self.enable_all_debug()
        self.log_summary(
            "SMC fabric read-side scenario complete",
            scenario=self.scenario,
            operations=self.operation_count,
            status=DtpJtag2AxiStatus(self.status).name,
        )
