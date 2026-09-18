# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC fabric JTAG2AXI read-side scenarios."""

from __future__ import annotations

from env.dtp_types import DtpJtag2AxiOp, DtpJtag2AxiStatus, DtpJtagInstr, pack_single_op

from .dtp_jtag2axi_base_test_seq import dtp_jtag2axi_base_test_seq

DEFAULT_AXI_ADDR = 0x40
DEFAULT_AXI_DATA = 0x0123_4567_89AB_CDEF
AXI_BEAT_BYTES = 8


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

    async def run_single_write_read(self) -> None:
        self.log_banner("SMC_AXI_SINGLE_OP Single Write-Read")
        await self.reset_tap()
        addr = DEFAULT_AXI_ADDR + 0x400
        # Seeded per-pass payload: each loop writes and reads back different data.
        data = self.rng("smc_axi_single_wr_rd").getrandbits(64)
        write_item = await self.write_single_and_check(addr, data, context="single_wr_rd.write")
        read_item = await self.read_single_and_check(addr, data, context="single_wr_rd.read")
        self.status = (
            read_item.status if read_item.status != DtpJtag2AxiStatus.SUCCESS else write_item.status
        )
        self.rdata = read_item.rdata
        self.data = data
        self.operation_count += 2

    async def run_series_write_read_incr(self) -> None:
        self.log_banner("SMC_AXI Series Write-Read Incrementing")
        await self.reset_tap()
        rng = self.rng("series_read_incr")
        size = 3
        stride = self.size_bytes(size)
        beats = max(2, min(self.random_count, 6))
        base = self.random_aligned_addr(rng, size) & ~0x3F
        expected = []
        self.log_step(1, "Write incrementing series")
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size)
        for idx in range(beats):
            data = rng.getrandbits(64) & self.data_mask(size)
            expected.append(data)
            before = await self.axi_activity_counts()
            await self.series_data_incr(data, size=size, back_to_rti=True)
            await self.wait_for_smc_axi_activity(
                before=before,
                read=False,
                context=f"series_wr_rd_incr.write_axi#{idx}",
            )
            self.assert_equal(
                f"series_wr_rd_incr.mem#{idx}",
                self.read_mem_int(base + idx * stride, size),
                data,
            )
        self.log_step(2, "Read incrementing series back")
        for idx, exp in enumerate(expected):
            addr = base + idx * stride
            await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.READ, addr, size=size)
            before = await self.axi_activity_counts()
            await self.series_data_incr(0, size=size, back_to_rti=True)
            await self.wait_for_smc_axi_activity(
                before=before,
                read=True,
                context=f"series_wr_rd_incr.read_axi#{idx}",
            )
            raw = await self.series_data_incr(0, size=size, back_to_rti=True)
            obs, _ = self.__class__.unpack_series_value(raw, size)
            self.log_iteration(idx + 1, beats, "series read incr addr=0x%08x obs=0x%x", addr, obs)
            self.assert_equal(f"series_wr_rd_incr.rdata#{idx}", obs, exp, f"addr=0x{addr:x}")
            self.operation_count += 1
        # The last primed incrementing read advanced the series address by
        # one stride past the last beat.
        self.status = await self.check_series_addr(
            "smc_axi", addr + stride, size=size, context="series_wr_rd_incr.final"
        )

    async def run_series_write_read_incr_narrow(self) -> None:
        self.log_banner("SMC_AXI Series Write-Read 32-bit Incrementing at Beat Offset +4")
        await self.reset_tap()
        rng = self.rng("series_read_incr_narrow")
        size = 2
        stride = self.size_bytes(size)
        beats = max(2, min(self.random_count, 6))
        base = (self.random_aligned_addr(rng, 3) & ~0x3F) + 4
        expected = []
        self.log_step(1, "Write 32-bit incrementing series at +4")
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size)
        for idx in range(beats):
            data = rng.getrandbits(64) & self.data_mask(size)
            expected.append(data)
            before = await self.axi_activity_counts()
            await self.series_data_incr(data, size=size, back_to_rti=True)
            await self.wait_for_smc_axi_activity(
                before=before,
                read=False,
                context=f"series_wr_rd_incr_narrow.write_axi#{idx}",
            )
            self.assert_equal(
                f"series_wr_rd_incr_narrow.mem#{idx}",
                self.read_mem_int(base + idx * stride, size),
                data,
            )
        self.log_step(2, "Read 32-bit incrementing series back")
        for idx, exp in enumerate(expected):
            addr = base + idx * stride
            await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.READ, addr, size=size)
            before = await self.axi_activity_counts()
            await self.series_data_incr(0, size=size, back_to_rti=True)
            await self.wait_for_smc_axi_activity(
                before=before,
                read=True,
                context=f"series_wr_rd_incr_narrow.read_axi#{idx}",
            )
            raw = await self.series_data_incr(0, size=size, back_to_rti=True)
            obs, _ = self.__class__.unpack_series_value(raw, size)
            self.log_iteration(
                idx + 1, beats, "series read incr narrow addr=0x%08x obs=0x%x", addr, obs
            )
            self.assert_equal(f"series_wr_rd_incr_narrow.rdata#{idx}", obs, exp, f"addr=0x{addr:x}")
            self.operation_count += 1
        self.status = await self.check_series_addr(
            "smc_axi", addr + stride, size=size, context="series_wr_rd_incr_narrow.final"
        )

    async def run_series_write_read_no_incr(self) -> None:
        self.log_banner("SMC_AXI Series Write-Read No-Increment")
        await self.reset_tap()
        rng = self.rng("series_read_no_incr")
        size = 3
        beats = max(2, min(self.random_count, 6))
        addr = self.random_aligned_addr(rng, size)
        values = [rng.getrandbits(64) & self.data_mask(size) for _ in range(beats)]
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, addr, size=size)
        for idx, data in enumerate(values, start=1):
            self.log_iteration(idx, beats, "series no-incr write addr=0x%08x data=0x%x", addr, data)
            before = await self.axi_activity_counts()
            await self.series_data_no_incr(data, size=size, back_to_rti=True)
            await self.wait_for_smc_axi_activity(
                before=before,
                read=False,
                context=f"series_wr_rd_no_incr.write_axi#{idx}",
            )
        expected = values[-1]
        for idx in range(1, beats + 1):
            await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.READ, addr, size=size)
            before = await self.axi_activity_counts()
            await self.series_data_no_incr(0, size=size, back_to_rti=True)
            await self.wait_for_smc_axi_activity(
                before=before,
                read=True,
                context=f"series_wr_rd_no_incr.read_axi#{idx}",
            )
            raw = await self.series_data_no_incr(0, size=size, back_to_rti=True)
            obs, _ = self.__class__.unpack_series_value(raw, size)
            self.log_iteration(idx, beats, "series no-incr read addr=0x%08x obs=0x%x", addr, obs)
            self.assert_equal(f"series_wr_rd_no_incr.rdata#{idx}", obs, expected)
            self.operation_count += 1
        _, addr_after, _, _, status = await self.read_series_ctrl(size=size)
        self.assert_equal("series_wr_rd_no_incr.addr_after", addr_after, addr)
        self.status = status

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
        for idx in range(1, self.random_count + 1):
            size = rng.choice([0, 1, 2, 3])
            addr = self.random_aligned_addr(rng, size)
            data = rng.getrandbits(64) & self.data_mask(size)
            self.write_mem_int(addr, data, size)
            self.log_iteration(
                idx,
                self.random_count,
                "random read addr=0x%08x size=%d data=0x%x",
                addr,
                size,
                data,
            )
            item = await self.read_single_and_check(
                addr,
                data,
                size=size,
                context=f"random_read#{idx}",
            )
            self.status = item.status
            self.rdata = item.rdata
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
        # Seeded per-pass payload for the baseline/restore reads.
        data = self.rng("smc_axi_read_gate").getrandbits(64)
        self.write_mem_int(addr, data, 3)
        self.log_step(1, "Establish baseline read and AXI activity")
        before = await self.axi_activity_counts()
        item = await self.read_single_and_check(addr, data, context="read_gate.baseline")
        await self.expect_smc_axi_activity(before=before, read=True, context="read_gate.baseline")
        self.status = item.status

        # Two assert/release passes of the one direct disable prove the gate
        # is repeatable, not a one-shot POR effect.
        for idx in (1, 2):
            bit_name = f"smc_jtag2axi_pass{idx}"
            self.log_step(idx + 1, "Gate SMC fabric read with smc_jtag2axi (pass %d)", idx)
            await self.disable_debug_bits("smc_jtag2axi")
            # Snapshot BEFORE the gated attempt so a request pulse leaked at
            # shift time is caught, then hold a blocked window across it: any
            # monitored m_axi transaction inside the window fails.
            gate_before = await self.axi_activity_counts()
            self.scoreboard_begin_blocked("smc_axi")
            raw = pack_single_op(DtpJtag2AxiOp.READ, addr + (idx * AXI_BEAT_BYTES))
            await self.load_ir(DtpJtagInstr.SMC_AXI_SINGLE_OP, back_to_rti=True)
            await self.shift_dr(raw, 132, back_to_rti=True)
            await self.expect_no_smc_axi_activity(8, context=f"read_gate.{bit_name}.no_axi")
            if self.axi_scoreboard is not None:
                gate_after = await self.axi_activity_counts()
                self.axi_scoreboard.expect_no_activity(
                    before=gate_before,
                    after=gate_after,
                    context=(
                        f"read_gate.{bit_name} target=smc_axi "
                        f"source=tb_pulse_counters window=gated_attempt+8cyc"
                    ),
                )
            # Hold the blocked window ACROSS disable release: a bridge that
            # queued the gated request and replays it once the gate re-opens
            # is the exact leak this scenario must catch.
            await self.enable_all_debug()
            await self.wait_sys_cycles(8)
            self.scoreboard_end_blocked("smc_axi", context=f"read_gate.{bit_name}")
            before = await self.axi_activity_counts()
            item = await self.read_single_and_check(
                addr,
                data,
                context=f"read_gate.{bit_name}.restore",
            )
            await self.expect_smc_axi_activity(
                before=before,
                read=True,
                context=f"read_gate.{bit_name}.restore",
            )
            if self.axi_scoreboard is not None:
                # Exact-delta proof from BEFORE the gated attempt to AFTER the
                # restore read: only the sanctioned restore read may appear
                # (ar +1, aw/w +0). A delayed replay anywhere in the span
                # makes ar >= +2 and fails.
                final = await self.axi_activity_counts()
                expected_exact = {
                    "aw": gate_before["aw"],
                    "w": gate_before["w"],
                    "ar": gate_before["ar"] + 1,
                }
                self.axi_scoreboard.expect_no_activity(
                    before=expected_exact,
                    after=final,
                    context=(
                        f"read_gate.{bit_name} target=smc_axi "
                        f"source=tb_pulse_counters window=exact_delta "
                        f"sanctioned=restore_read(ar+1)"
                    ),
                )
            self.status = item.status
            self.operation_count += 1
        if self.axi_scoreboard is not None:
            # CHK-AXI-NONVAC: the same counters that stayed flat while gated
            # demonstrably move for real traffic (baseline + both restores), so
            # the no-activity evidence cannot pass on a dead or tied-off bus.
            final = await self.axi_activity_counts()
            self.axi_scoreboard.expect_nonvacuous(
                self.operation_count >= 2 and final["ar"] >= 3,
                context=(
                    f"gated_attempts={self.operation_count} ar_pulses={final['ar']} "
                    f"expected_ar>=3 (baseline+2 restores)"
                ),
            )

    @staticmethod
    def unpack_series_value(raw: int, size: int) -> tuple[int, int]:
        from env.dtp_types import unpack_series_data

        return unpack_series_data(raw, size)

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
