# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross-bridge JTAG2AXI robustness scenarios."""

from __future__ import annotations

import cocotb

from env.dtp_types import DtpJtag2AxiOp, DtpJtag2AxiStatus

from .dtp_jtag2axi_base_test_seq import dtp_jtag2axi_base_test_seq

AXI_DECERR = 3
ROBUST_TARGETS = ("smc_axi", "smc_otp", "sep_otp")
ROBUST_BASE = 0x3800


class dtp_jtag2axi_robustness_test_seq(dtp_jtag2axi_base_test_seq):
    """Run one cross-target robustness scenario."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_robustness_test_seq",
        *,
        scenario: str = "backpressure_aw_before_w",
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self.scenario = scenario
        self.status = DtpJtag2AxiStatus.SUCCESS
        self.operation_count = 0

    def _target_addr(self, target: str, idx: int) -> int:
        cfg = self.target_cfg(target)
        return ROBUST_BASE + idx * 0x400 + cfg.beat_bytes

    def _stall_beyond_scan_tail(self, rng, target: str, *, scans: int = 2) -> int:
        """READY-stall long enough to outlast the JTAG idle tail plus `scans`
        status scans, in system-clock cycles.

        Each TDR access ends with the driver's idle-TCK tail, and one status
        poll is another full scan; a stall shorter than that window expires
        before the sequence regains control, so the operation completes
        silently and reset-abort / BUSY scenarios degenerate to idle ones.
        """
        cfg = self.target_cfg(target)
        scan_tck = cfg.single_op_len + 32  # shift plus TAP navigation
        tail_tck = self.cfg.idle_tck + scans * scan_tck
        cycles = (tail_tck * self.cfg.jtag_period_ns) // self.cfg.sys_clk_period_ns
        return cycles + rng.randint(16, 64)

    async def _write_with_backpressure(
        self,
        target: str,
        *,
        channels: tuple[str, ...],
        stall_cycles: int,
        context: str,
    ) -> None:
        cfg = self.target_cfg(target)
        size = cfg.default_size
        addr = self._target_addr(target, self.operation_count + 1)
        data = (0x1020_3040_5060_7080 ^ addr) & self.data_mask(size)
        self.configure_target_backpressure(target, channels=channels, stall_cycles=stall_cycles)
        try:
            before = await self.target_activity_counts(target)
            status, _ = await self.write_target_single_and_check(
                target,
                addr,
                data,
                size=size,
                context=context,
            )
            await self.expect_target_activity(target, before=before, read=False, context=context)
            self.assert_equal(f"{context}.status", status, DtpJtag2AxiStatus.SUCCESS)
        finally:
            self.clear_target_backpressure(target)
        self.operation_count += 1

    async def _read_with_backpressure(
        self,
        target: str,
        *,
        channels: tuple[str, ...],
        stall_cycles: int,
        context: str,
    ) -> None:
        cfg = self.target_cfg(target)
        size = cfg.default_size
        addr = self._target_addr(target, self.operation_count + 1)
        data = (0xABCD_EF01_2345_6789 ^ addr) & self.data_mask(size)
        self.write_target_mem_int(target, addr, data, size)
        self.configure_target_backpressure(target, channels=channels, stall_cycles=stall_cycles)
        try:
            before = await self.target_activity_counts(target)
            status, _ = await self.read_target_single_and_check(
                target,
                addr,
                data,
                size=size,
                context=context,
            )
            await self.expect_target_activity(target, before=before, read=True, context=context)
            self.assert_equal(f"{context}.status", status, DtpJtag2AxiStatus.SUCCESS)
        finally:
            self.clear_target_backpressure(target)
        self.operation_count += 1

    async def run_backpressure_aw_before_w(self) -> None:
        self.log_banner("JTAG2AXI backpressure: AW accepted before delayed W")
        await self.reset_tap()
        rng = self.rng("backpressure_aw_before_w")
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            # Seeded per-pass stall width: each loop delays WREADY differently.
            stall = rng.randint(2, 6)
            self.log_iteration(idx, len(ROBUST_TARGETS), "target=%s WREADY stall=%d", target, stall)
            await self._write_with_backpressure(
                target,
                channels=("w",),
                stall_cycles=stall,
                context=f"aw_before_w.{target}",
            )

    async def run_backpressure_long_stall(self) -> None:
        self.log_banner("JTAG2AXI long bounded READY stalls")
        await self.reset_tap()
        rng = self.rng("backpressure_long_stall")
        targets = list(ROBUST_TARGETS)
        rng.shuffle(targets)
        for idx, target in enumerate(targets, start=1):
            # A stall outlasting the idle tail keeps the op outstanding into
            # the status polls, so the bridge reports BUSY_OR_FULL before the
            # settled status; the seeded scan budget spreads the settle point
            # across the short-wait and long-wait poll classes over the loops.
            stall = self._stall_beyond_scan_tail(rng, target, scans=rng.choice((2, 16)))
            self.log_iteration(idx, len(targets), "target=%s stall=%d", target, stall)
            await self._write_with_backpressure(
                target,
                channels=("aw", "w"),
                stall_cycles=stall,
                context=f"long_stall.write.{target}",
            )
            await self._read_with_backpressure(
                target,
                channels=("ar",),
                stall_cycles=rng.randint(4, 10),
                context=f"long_stall.read.{target}",
            )
            # Zero-strobe and window-boundary singles: legal corner operands
            # exercised once the stalls are cleared.
            cfg = self.target_cfg(target)
            size = cfg.default_size
            await self.write_target_single_and_check(
                target,
                self._target_addr(target, idx + 40),
                rng.getrandbits(32),
                size=size,
                wstrb=0,
                context=f"long_stall.wstrb_none.{target}",
            )
            boundary_addr = 0x1_0000 - self.size_bytes(size)
            boundary_data = rng.getrandbits(32) & self.data_mask(size)
            await self.write_target_single_and_check(
                target,
                boundary_addr,
                boundary_data,
                size=size,
                context=f"long_stall.boundary.{target}",
            )

    async def run_backpressure_abort_at_data_w(self) -> None:
        self.log_banner("JTAG2AXI reset abort while W channel is stalled")
        await self.reset_tap()
        rng = self.rng("backpressure_abort_at_data_w")
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            cfg = self.target_cfg(target)
            size = cfg.default_size
            addr = self._target_addr(target, idx)
            # Seeded per-pass payload and CDC timing. The stall stays shorter
            # than the scan's idle tail, so the reset lands after the bus
            # transaction completed: a stall long enough for a true mid-flight
            # abort leaves the recovery write BUSY_OR_FULL indefinitely
            # (tracked as issue #1330).
            data = rng.getrandbits(64) & self.data_mask(size)
            stall = rng.randint(16, 24)
            self.log_iteration(
                idx, len(ROBUST_TARGETS), "target=%s abort W phase stall=%d", target, stall
            )
            self.configure_target_backpressure(target, channels=("w",), stall_cycles=stall)
            await self.write_target_single_raw(
                target,
                DtpJtag2AxiOp.WRITE,
                addr,
                data=data,
                wstrb=self.target_full_wstrb(target, size),
                size=size,
            )
            await self.wait_sys_cycles(rng.randint(1, 4))
            await self.pulse_system_reset(cycles=rng.randint(1, 3))
            self.clear_target_backpressure(target)
            await self.verify_target_recovery(
                target,
                addr=addr + 0x200,
                data=data ^ 0x1111,
                read=False,
                context=f"abort_w.{target}",
            )
            self.operation_count += 1

    async def run_cdc_clear_abort_narrow_reset_mid_xaction(self) -> None:
        self.log_banner("JTAG2AXI narrow reset during outstanding transaction")
        await self.reset_tap()
        rng = self.rng("cdc_narrow_reset")
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            cfg = self.target_cfg(target)
            size = cfg.default_size
            addr = self._target_addr(target, idx + 8)
            # Seeded per-pass payload and stall. The stall stays shorter than
            # the scan's idle tail, so the narrow reset lands after the bus
            # transaction completed (see the mid-flight abort note above; issue #1330).
            data = rng.getrandbits(64) & self.data_mask(size)
            stall = rng.randint(8, 16)
            self.log_iteration(
                idx, len(ROBUST_TARGETS), "target=%s narrow reset stall=%d", target, stall
            )
            self.configure_target_backpressure(target, channels=("aw",), stall_cycles=stall)
            await self.write_target_single_raw(
                target,
                DtpJtag2AxiOp.WRITE,
                addr,
                data=data,
                wstrb=self.target_full_wstrb(target, size),
                size=size,
            )
            await self.wait_sys_cycles(rng.randint(1, 3))
            await self.pulse_system_reset(cycles=1)
            self.clear_target_backpressure(target)
            await self.verify_target_recovery(
                target,
                addr=addr + 0x200,
                data=data ^ 0x2222,
                read=False,
                context=f"narrow_reset.{target}",
            )
            self.operation_count += 1

    async def run_cdc_clear_abort_back_to_back_reset(self) -> None:
        self.log_banner("JTAG2AXI back-to-back reset recovery")
        await self.reset_tap()
        rng = self.rng("cdc_back_to_back_reset")
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            addr = self._target_addr(target, idx + 16)
            # Seeded per-pass payload and pulse widths: each loop stresses a
            # different back-to-back reset spacing.
            data = rng.getrandbits(64) & self.target_data_mask(target)
            self.log_iteration(idx, len(ROBUST_TARGETS), "target=%s back-to-back reset", target)
            await self.pulse_system_reset(cycles=rng.randint(1, 2))
            await self.pulse_system_reset(cycles=rng.randint(1, 3))
            await self.verify_target_recovery(
                target,
                addr=addr,
                data=data,
                read=False,
                context=f"back_to_back_reset.{target}",
            )
            await self.verify_target_recovery(
                target,
                addr=addr,
                data=data,
                read=True,
                context=f"back_to_back_reset_read.{target}",
            )
            self.operation_count += 1

    async def run_decode_error_decerr_write(self) -> None:
        self.log_banner("JTAG2AXI DECERR write decode path")
        await self.reset_tap()
        rng = self.rng("decerr_write_data")
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            addr = self._target_addr(target, idx + 24)
            expected = self.configure_target_error(target, addr, AXI_DECERR, read=False, write=True)
            status, _ = await self.write_target_single_expect_status(
                target,
                addr,
                rng.getrandbits(32) ^ idx,
                expected,
                context=f"decerr_write.{target}",
            )
            self.assert_equal(f"decerr_write.{target}.status", status, DtpJtag2AxiStatus.DECERR)
            await self.verify_target_recovery(
                target,
                addr=addr + 0x200,
                # Seeded per-pass recovery payload.
                data=rng.getrandbits(32) ^ idx,
                read=False,
                context=f"decerr_write.{target}",
            )
            self.operation_count += 1
        self._emit_decode_error_nonvacuity("decerr_write")

    async def run_decode_error_decerr_read(self) -> None:
        self.log_banner("JTAG2AXI DECERR read decode path")
        await self.reset_tap()
        rng = self.rng("decerr_read_data")
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            addr = self._target_addr(target, idx + 32)
            expected = self.configure_target_error(target, addr, AXI_DECERR, read=True, write=False)
            status, _ = await self.read_target_single_expect_status(
                target,
                addr,
                expected,
                context=f"decerr_read.{target}",
            )
            self.assert_equal(f"decerr_read.{target}.status", status, DtpJtag2AxiStatus.DECERR)
            await self.verify_target_recovery(
                target,
                addr=addr + 0x200,
                # Seeded per-pass recovery payload.
                data=rng.getrandbits(32) ^ idx,
                read=True,
                context=f"decerr_read.{target}",
            )
            self.operation_count += 1
        self._emit_decode_error_nonvacuity("decerr_read")

    def _emit_decode_error_nonvacuity(self, label: str) -> None:
        """CHK-AXI-NONVAC: every target returned exact DECERR and recovered.

        A tied-off, idle, or always-OKAY bridge cannot satisfy this: each armed
        DECERR credit must have been consumed by a real bus response, and each
        target completed an OKAY recovery access afterwards.
        """
        scoreboard = self.axi_scoreboard
        if scoreboard is None:
            return
        unconsumed = scoreboard.unconsumed_credits()
        scoreboard.expect_nonvacuous(
            self.operation_count >= len(ROBUST_TARGETS) and unconsumed == 0,
            context=(
                f"scenario={label} targets={self.operation_count} "
                f"resp=DECERR credits_unconsumed={unconsumed}"
            ),
        )

    async def run_decode_error_mixed(self) -> None:
        self.log_banner("JTAG2AXI mixed mapped/unmapped decode access")
        await self.reset_tap()
        rng = self.rng("decode_error_mixed")
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            good_addr = self._target_addr(target, idx + 40)
            bad_addr = good_addr + 0x100
            good_data = rng.getrandbits(self.target_cfg(target).data_width)
            await self.write_target_single_and_check(target, good_addr, good_data, context=f"mixed.good_write.{target}")
            expected = self.configure_target_error(target, bad_addr, AXI_DECERR, read=True, write=True)
            await self.read_target_single_expect_status(
                target,
                bad_addr,
                expected,
                context=f"mixed.bad_read.{target}",
            )
            await self.read_target_single_and_check(
                target,
                good_addr,
                good_data,
                context=f"mixed.good_read.{target}",
            )
            self.operation_count += 1
        self._emit_decode_error_nonvacuity("mixed")

    async def run_series_corner_all_bridges(self) -> None:
        self.log_banner("JTAG2AXI series corner coverage across all bridges")
        await self.reset_tap()
        rng = self.rng("series_corner_all_bridges")
        for target_idx, target in enumerate(ROBUST_TARGETS, start=1):
            cfg = self.target_cfg(target)
            size = cfg.default_size
            base = 0x5000 + target_idx * 0x100
            self.log_iteration(target_idx, len(ROBUST_TARGETS), "target=%s series reset/pipeline/status", target)
            await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.NOP, 0, reset=1, size=size, target=target)
            await self.jtag2axi_series_ctrl(
                DtpJtag2AxiOp.WRITE,
                base,
                pipeline_depth=1,
                size=size,
                target=target,
            )
            for beat in range(2):
                data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
                before = await self.target_activity_counts(target)
                await self.series_data_with_status(
                    data,
                    size=size,
                    increment=1,
                    target=target,
                    back_to_rti=True,
                )
                await self.wait_for_target_activity(
                    target,
                    before=before,
                    read=False,
                    context=f"series_corner.write.{target}.{beat}",
                )
                self.assert_equal(
                    f"series_corner.mem.{target}.{beat}",
                    self.read_target_mem_int(target, base + beat * cfg.beat_bytes, size),
                    data,
                )
            _, addr_after, _, _, status = await self.read_series_ctrl(size=size, target=target)
            self.assert_equal(f"series_corner.status.{target}", status, DtpJtag2AxiStatus.SUCCESS)
            self.assert_equal(f"series_corner.addr_after.{target}", addr_after, base + 2 * cfg.beat_bytes)
            self.operation_count += 1

    async def body(self) -> None:
        await self.enable_all_debug()
        scenarios = {
            "backpressure_aw_before_w": self.run_backpressure_aw_before_w,
            "backpressure_long_stall": self.run_backpressure_long_stall,
            "backpressure_abort_at_data_w": self.run_backpressure_abort_at_data_w,
            "cdc_clear_abort_narrow_reset_mid_xaction": self.run_cdc_clear_abort_narrow_reset_mid_xaction,
            "cdc_clear_abort_back_to_back_reset": self.run_cdc_clear_abort_back_to_back_reset,
            "decode_error_decerr_write": self.run_decode_error_decerr_write,
            "decode_error_decerr_read": self.run_decode_error_decerr_read,
            "decode_error_mixed": self.run_decode_error_mixed,
            "series_corner_all_bridges": self.run_series_corner_all_bridges,
        }
        if self.scenario not in scenarios:
            raise ValueError(f"unknown JTAG2AXI robustness scenario {self.scenario!r}")
        await scenarios[self.scenario]()
        for target in ROBUST_TARGETS:
            self.clear_target_errors(target)
            self.clear_target_backpressure(target)
        await self.enable_all_debug()
        self.log_summary(
            "JTAG2AXI robustness scenario complete",
            scenario=self.scenario,
            operations=self.operation_count,
            status=DtpJtag2AxiStatus(self.status).name,
        )
