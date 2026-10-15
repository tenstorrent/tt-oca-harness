# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTP AXI-Lite JTAG2AXI scenarios."""

from __future__ import annotations

from env.dtp_types import DtpJtag2AxiOp, DtpJtag2AxiStatus

from .dtp_jtag2axi_base_test_seq import dtp_jtag2axi_base_test_seq

DEFAULT_OTP_ADDR = 0x80
DEFAULT_OTP_DATA = 0x0123_4567


class dtp_jtag2axi_otp_axi_test_seq(dtp_jtag2axi_base_test_seq):
    """Run one focused SMC/SEP OTP AXI-Lite JTAG2AXI scenario."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_otp_axi_test_seq",
        *,
        target: str = "smc_otp",
        scenario: str = "single_write",
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self.target = target
        self.scenario = scenario
        self.status = DtpJtag2AxiStatus.SUCCESS
        self.operation_count = 0

    def bus_ledger_target(self) -> str | None:
        return None if "security_gating" in self.scenario else self.target

    def directed_cases(self) -> list[tuple[int, int, int, int]]:
        """Return deterministic AXI-Lite address, size, data, strobe cases."""
        cases = []
        for idx, size in enumerate((0, 1, 2)):
            addr = DEFAULT_OTP_ADDR + (idx * 0x20)
            data = (DEFAULT_OTP_DATA ^ (0x1111_1111 * idx)) & self.data_mask(size)
            cases.append((addr, size, data, self.full_wstrb(size)))
        cases.append((DEFAULT_OTP_ADDR + 0x80, 2, 0xA5A5_5A5A, 0x5))
        cases.append((DEFAULT_OTP_ADDR + 0xA0, 2, 0x5A5A_A5A5, 0xA))
        # Seeded per-pass random cases on top of the deterministic sweep:
        # every loop drives different address/size/data/strobe values.
        rng = self.rng(f"{self.target}_directed_cases")
        for _ in range(self.random_count):
            size = rng.choice([0, 1, 2])
            addr = self.random_upper_addr(self.target, rng) | self.random_target_aligned_addr(
                self.target, rng, size
            )
            data = rng.getrandbits(32) & self.data_mask(size)
            wstrb = rng.randint(1, self.target_full_wstrb(self.target, size))
            cases.append((addr, size, data, wstrb))
        return cases

    async def run_single_write(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP Directed Write")
        await self.reset_tap()
        cases = self.directed_cases()
        for idx, (addr, size, data, wstrb) in enumerate(cases, start=1):
            self.log_iteration(
                idx,
                len(cases),
                "single write addr=0x%08x size=%d data=0x%x wstrb=0x%01x",
                addr,
                size,
                data,
                wstrb,
            )
            status, _ = await self.write_target_single_and_check(
                self.target,
                addr,
                data,
                size=size,
                wstrb=wstrb,
                context=f"single_write#{idx}",
            )
            self.status = status
            self.operation_count += 1

    async def run_single_write_data_verify(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP Write With Readback")
        await self.reset_tap()
        self.status, rdata, _ = await self.write_neighbour_then_read(
            self.target,
            DEFAULT_OTP_ADDR + 0x100,
            self.rng(f"{self.target}_write_readback"),
            context="write_readback",
        )
        self.operation_count += 3
        self.log.info("write_readback target=%s rdata=0x%08x", self.target, rdata)

    async def run_series_write_incr(self) -> None:
        self.log_banner(f"{self.target} SERIES_DATA_INCR Write Sweep")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_write_incr")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        stride = cfg.beat_bytes
        beats = max(2, min(self.random_count, 6))
        base = self.random_series_base(self.target, rng, span=beats * stride, straddle=True)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size, target=self.target)
        for idx in range(beats):
            addr = base + (idx * stride)
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            self.log_iteration(
                idx + 1, beats, "series incr write addr=0x%08x data=0x%x", addr, data
            )
            await self.series_write_beat(
                self.target,
                data,
                addr=addr,
                size=size,
                increment=True,
                context=f"series_incr#{idx}",
            )
            self.operation_count += 1
        self.status = await self.check_series_end(
            self.target, base + beats * stride, size=size, context="series_incr"
        )

    async def run_series_write_no_incr(self) -> None:
        self.log_banner(f"{self.target} SERIES_DATA_NO_INCR Write Sweep")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_write_no_incr")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        beats = max(2, min(self.random_count, 6))
        addr = self.random_series_base(self.target, rng, span=cfg.beat_bytes)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, addr, size=size, target=self.target)
        for idx in range(beats):
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            self.log_iteration(
                idx + 1,
                beats,
                "series no-incr write addr=0x%08x data=0x%x",
                addr,
                data,
            )
            await self.series_write_beat(
                self.target,
                data,
                addr=addr,
                size=size,
                increment=False,
                context=f"series_no_incr#{idx}",
            )
            self.operation_count += 1
        self.status = await self.check_series_end(
            self.target, addr, size=size, context="series_no_incr"
        )

    async def run_series_write_incr_with_error(self) -> None:
        self.log_banner(f"{self.target} SERIES_DATA_WITH_ERROR_STATUS Write Mode")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_write_with_status")
        cfg = self.target_cfg(self.target)
        plan = self.arm_series_status_fault(
            self.plan_series_status(self.target, rng), rng, read=False
        )
        words = [
            rng.getrandbits(cfg.data_width) & self.data_mask(plan.size) for _ in plan.increments
        ]
        self.log_step(
            1,
            "Write the with-status series; beat %d returns %s",
            plan.fault_idx,
            plan.expected.name,
        )
        await self.run_series_status_write(plan, words, context="series_status")
        self.log_step(2, "Recover with a legal single write outside the stream")
        self.status = await self.verify_target_recovery(
            self.target,
            addr=self.series_status_recovery_addr(plan),
            data=rng.getrandbits(cfg.data_width),
            read=False,
            context="series_status",
        )
        self.operation_count += plan.beats + 1
        self.emit_series_status_nonvacuity(
            "series_write_incr_with_error", plan, self.operation_count
        )

    async def run_random_ops(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP Randomized Writes")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.random_write_ops")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        image: dict[int, int] = {}
        for idx in range(1, self.random_count + 1):
            addr = self.random_upper_addr(self.target, rng) | self.random_target_aligned_addr(
                self.target, rng
            )
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            # Any non-empty legal strobe pattern; the per-write check judges
            # the enabled lanes, the end-state image every lane.
            wstrb = rng.randint(1, self.target_full_wstrb(self.target, size))
            self.log_iteration(
                idx,
                self.random_count,
                "random write addr=0x%08x data=0x%x wstrb=0x%x",
                addr,
                data,
                wstrb,
            )
            self.snapshot_target_word(self.target, image, addr, size)
            status, _ = await self.write_target_single_and_check(
                self.target,
                addr,
                data,
                size=size,
                wstrb=wstrb,
                context=f"random_write#{idx}",
            )
            self.image_write(self.target, image, addr, data, wstrb=wstrb, size=size)
            self.status = status
            self.operation_count += 1
        self.check_memory_image(self.target, image, context="random_write")

    async def run_write_security_gating(self) -> None:
        self.log_banner(f"{self.target} Write Security Gating")
        await self.reset_tap()
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        addr = DEFAULT_OTP_ADDR + 0x200
        # One payload serves the baseline, gated, and restore writes.
        data = self.rng(f"{self.target}_write_gate").getrandbits(32) & self.data_mask(size)
        writes_start = self.port_history(self.target).count(read=False)
        before = await self.target_activity_counts(self.target)
        await self.write_target_single_and_check(self.target, addr, data, context="gate.baseline")
        await self.expect_target_activity(
            self.target,
            before=before,
            read=False,
            context="gate.baseline",
        )
        # Two assert/release passes of the target's direct disable prove the
        # gate is repeatable, not a one-shot POR effect.
        image_rng = self.rng(f"{self.target}_write_gate_image")
        for idx in (1, 2):
            bit_name = f"{cfg.dbg_disable_bit}_pass{idx}"
            self.log_step(
                idx + 1, "Gate %s write with %s (pass %d)", self.target, cfg.dbg_disable_bit, idx
            )
            gate_before = await self.gated_attempt(
                self.target,
                DtpJtag2AxiOp.WRITE,
                addr + (idx * cfg.beat_bytes),
                data=data ^ idx,
                image_rng=image_rng,
                context=f"gate.{bit_name}",
                sentinel=0x5EA1_0000 | idx,
            )
            self.status = await self.restore_after_gate(
                self.target,
                read=False,
                addr=addr + (idx * 0x20),
                data=data ^ (idx << 8),
                gate_before=gate_before,
                context=f"gate.{bit_name}",
            )
            self.operation_count += 1
        self.log_step(
            4, "Gate %s write with series beats queued behind one on the bus", self.target
        )
        await self.run_queued_write_drop(
            self.target,
            self.rng(f"{self.target}_queued_drop"),
            addr=addr + 0x100,
            context="gate.queued_drop",
        )
        self.status = await self.verify_target_recovery(
            self.target,
            addr=addr + 0x140,
            data=data ^ 0xA5A5,
            read=False,
            context="gate.queued_drop",
        )
        writes = self.port_history(self.target).count(read=False) - writes_start
        self.emit_nonvacuity(
            self.target,
            writes >= 3,
            context=(
                f"gate.writes source=responder_burst_counts write_bursts={writes} "
                f"sanctioned>=3 (baseline+2 restores)"
            ),
        )

    async def run_single_write_read(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP Single Write-Read")
        await self.reset_tap()
        self.status, rdata, _ = await self.write_neighbour_then_read(
            self.target,
            DEFAULT_OTP_ADDR + 0x300,
            self.rng(f"{self.target}_single_wr_rd"),
            context="single_wr_rd",
        )
        self.operation_count += 3
        self.log.info("single_wr_rd target=%s rdata=0x%08x", self.target, rdata)

    async def _series_write_values(
        self, base: int, values: list[int], *, increment: bool, size: int | None = None
    ) -> None:
        cfg = self.target_cfg(self.target)
        if size is None:
            size = cfg.default_size
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size, target=self.target)
        for idx, data in enumerate(values):
            await self.series_write_beat(
                self.target,
                data,
                addr=base + idx * cfg.beat_bytes if increment else base,
                size=size,
                increment=increment,
                context=f"series_write_values#{idx}",
            )

    async def run_series_write_read_incr(self) -> None:
        self.log_banner(f"{self.target} Series Write-Read Incrementing")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_read_incr")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        stride = cfg.beat_bytes
        beats = max(2, min(self.random_count, 6))
        base = self.random_series_base(self.target, rng, span=beats * stride, straddle=True)
        values = [rng.getrandbits(cfg.data_width) & self.data_mask(size) for _ in range(beats)]
        await self._series_write_values(base, values, increment=True)
        for idx, exp in enumerate(values):
            addr = base + idx * stride
            obs = await self.series_read_beat(
                self.target,
                addr=addr,
                size=size,
                increment=True,
                context=f"series_wr_rd_incr.read#{idx}",
            )
            self.check_bridge_rdata(
                self.target, obs, exp, context=f"series_wr_rd_incr.rdata#{idx} addr=0x{addr:x}"
            )
            self.operation_count += 1
        # The last primed incrementing read advanced the series address by
        # one stride past the last beat.
        self.status = await self.check_series_end(
            self.target, addr + stride, size=size, context="series_wr_rd_incr.final"
        )

    async def run_series_write_read_incr_oversize(self) -> None:
        self.log_banner(f"{self.target} Series Write-Read With An Oversized Size Field")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_read_incr_oversize")
        cfg = self.target_cfg(self.target)
        size = (1 << cfg.size_bits) - 1
        if size <= cfg.data_size:
            raise ValueError(f"{self.target} size field cannot exceed the bus width")
        eff = cfg.axsize(size)
        stride = cfg.beat_bytes
        beats = max(2, min(self.random_count, 6))
        base = self.random_series_base(self.target, rng, span=beats * stride, straddle=True)
        values = [rng.getrandbits(cfg.data_width) & self.data_mask(eff) for _ in range(beats)]
        await self._series_write_values(base, values, increment=True, size=size)
        for idx, exp in enumerate(values):
            addr = base + idx * stride
            obs = await self.series_read_beat(
                self.target,
                addr=addr,
                size=size,
                increment=True,
                context=f"series_wr_rd_incr_oversize.read#{idx}",
            )
            self.check_bridge_rdata(
                self.target,
                obs,
                exp,
                context=f"series_wr_rd_incr_oversize.rdata#{idx} addr=0x{addr:x}",
            )
            self.operation_count += 1
        self.status = await self.check_series_end(
            self.target, addr + stride, size=size, context="series_wr_rd_incr_oversize.final"
        )

    async def run_series_write_read_no_incr(self) -> None:
        self.log_banner(f"{self.target} Series Write-Read No-Increment")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_read_no_incr")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        beats = max(2, min(self.random_count, 6))
        addr = self.random_series_base(self.target, rng, span=cfg.beat_bytes)
        values = [rng.getrandbits(cfg.data_width) & self.data_mask(size) for _ in range(beats)]
        await self._series_write_values(addr, values, increment=False)
        self.status = await self.series_reread_fixed(
            self.target,
            addr,
            last_word=values[-1],
            beats=beats,
            rng=rng,
            context="series_wr_rd_no_incr",
        )
        self.operation_count += beats

    async def run_series_write_read_incr_with_error(self) -> None:
        self.log_banner(f"{self.target} Series Write-Read With Error-Status Mode")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_read_with_status")
        cfg = self.target_cfg(self.target)
        plan = self.plan_series_status(self.target, rng)
        words = [
            rng.getrandbits(cfg.data_width) & self.data_mask(plan.size) for _ in plan.increments
        ]
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
            self.target,
            addr=self.series_status_recovery_addr(plan),
            data=rng.getrandbits(cfg.data_width),
            read=True,
            context="series_wr_rd_status",
        )
        self.operation_count += 2 * plan.beats + 1
        self.emit_series_status_nonvacuity(
            "series_write_read_incr_with_error", plan, self.operation_count
        )

    async def run_read_random_ops(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP Randomized Reads")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.random_read_ops")
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        for idx in range(1, self.random_count + 1):
            addr = self.random_upper_addr(self.target, rng) | self.random_target_aligned_addr(
                self.target, rng
            )
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            self.write_target_mem_int(self.target, addr, data, size)
            self.log_iteration(
                idx, self.random_count, "random read addr=0x%08x data=0x%x", addr, data
            )
            status, _ = await self.read_target_single_and_check(
                self.target,
                addr,
                data,
                size=size,
                context=f"random_read#{idx}",
            )
            self.status = status
            self.operation_count += 1

    async def run_read_security_gating(self) -> None:
        self.log_banner(f"{self.target} Read Security Gating")
        await self.reset_tap()
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        addr = DEFAULT_OTP_ADDR + 0x400
        # One payload serves the baseline and restore reads.
        data = self.rng(f"{self.target}_read_gate").getrandbits(32) & self.data_mask(size)
        self.write_target_mem_int(self.target, addr, data, size)
        reads_start = self.port_history(self.target).count(read=True)
        before = await self.target_activity_counts(self.target)
        self.status, _ = await self.read_target_single_and_check(
            self.target,
            addr,
            data,
            context="read_gate.baseline",
        )
        await self.expect_target_activity(
            self.target,
            before=before,
            read=True,
            context="read_gate.baseline",
        )
        # Two assert/release passes of the target's direct disable prove the
        # gate is repeatable, not a one-shot POR effect.
        image_rng = self.rng(f"{self.target}_read_gate_image")
        for idx in (1, 2):
            bit_name = f"{cfg.dbg_disable_bit}_pass{idx}"
            self.log_step(
                idx + 1, "Gate %s read with %s (pass %d)", self.target, cfg.dbg_disable_bit, idx
            )
            gate_before = await self.gated_attempt(
                self.target,
                DtpJtag2AxiOp.READ,
                addr + (idx * cfg.beat_bytes),
                data=0,
                image_rng=image_rng,
                context=f"read_gate.{bit_name}",
            )
            self.status = await self.restore_after_gate(
                self.target,
                read=True,
                addr=addr,
                data=data,
                gate_before=gate_before,
                context=f"read_gate.{bit_name}",
            )
            self.operation_count += 1
        reads = self.port_history(self.target).count(read=True) - reads_start
        self.emit_nonvacuity(
            self.target,
            reads >= 3,
            context=(
                f"read_gate.reads source=responder_burst_counts read_bursts={reads} "
                f"sanctioned>=3 (baseline+2 restores)"
            ),
        )

    async def body(self) -> None:
        await self.enable_all_debug()
        scenarios = {
            "single_write": self.run_single_write,
            "single_write_data_verify": self.run_single_write_data_verify,
            "series_write_incr": self.run_series_write_incr,
            "series_write_no_incr": self.run_series_write_no_incr,
            "series_write_incr_with_error": self.run_series_write_incr_with_error,
            "random_ops": self.run_random_ops,
            "write_security_gating": self.run_write_security_gating,
            "single_write_read": self.run_single_write_read,
            "series_write_read_incr": self.run_series_write_read_incr,
            "series_write_read_incr_oversize": self.run_series_write_read_incr_oversize,
            "series_write_read_no_incr": self.run_series_write_read_no_incr,
            "series_write_read_incr_with_error": self.run_series_write_read_incr_with_error,
            "read_random_ops": self.run_read_random_ops,
            "read_security_gating": self.run_read_security_gating,
        }
        if self.target not in ("smc_otp", "sep_otp"):
            raise ValueError(f"unsupported OTP JTAG2AXI target {self.target!r}")
        if self.scenario not in scenarios:
            raise ValueError(f"unknown OTP JTAG2AXI scenario {self.scenario!r}")
        await scenarios[self.scenario]()
        await self.enable_all_debug()
        self.log_summary(
            "OTP AXI-Lite JTAG2AXI scenario complete",
            target=self.target,
            scenario=self.scenario,
            operations=self.operation_count,
            status=DtpJtag2AxiStatus(self.status).name,
        )
