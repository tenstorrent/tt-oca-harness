# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross-bridge JTAG2AXI robustness scenarios."""

from __future__ import annotations

from env.dtp_types import (
    ABORT_ESCAPE_CHECK_ID,
    ABORT_FSM_CHECK_ID,
    ABORT_MIDFLIGHT_CHECK_ID,
    ABORT_RECOVERY_CHECK_ID,
    CDC_CLEAR_CHECK_ID,
    FAULT_STATUS_CHECK_ID,
    STALL_BUSY_CHECK_ID,
    STALL_FSM_CHECK_ID,
    DtpJtag2AxiOp,
    DtpJtag2AxiStatus,
    unpack_single_op,
)

from .dtp_jtag2axi_base_test_seq import (
    AXI_RESP_DECERR,
    AXI_RESP_SLVERR,
    dtp_jtag2axi_base_test_seq,
)

AXI_DECERR = 3
ROBUST_TARGETS = ("smc_axi", "smc_otp", "sep_otp")
ROBUST_BASE = 0x3800
# Series-corner windows: one 0x400 window per bridge, one 0x100 leg per series.
SERIES_CORNER_BASE = 0x5000
# Reset-abort stimulus: the READY stall outlasts everything and is released
# after the reset, so the write sits on the bus throughout the reset pulse.
ABORT_HOLD_CYCLES = 100_000
# TCK cycles for the bridge's state machine to leave idle after the SINGLE_OP
# Update-DR, and to return to idle after the reset. The state machine and the
# CDC's TCK side advance only while TCK runs, so the waits step the TAP in
# Run-Test/Idle.
ABORT_MIDFLIGHT_TCK = 64
ABORT_SETTLE_TCK = 128
ABORT_RECOVERY_POLLS = 8
# TCK cycles after a reset pulse for the CDC controller to run its TCK-side
# isolate-and-clear on an idle bridge.
ABORT_CDC_CLEAR_TCK = 32


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

    async def _observe_stall(self, target: str, *, read: bool, context: str) -> None:
        """The READY stall seen from the DUT.

        The bridge's state machine has left idle onto the stalled path
        (CHK-J2A-STALL-FSM) and the first status poll reads BUSY_OR_FULL
        (CHK-J2A-STALL-BUSY). Both need the stall to outlast the poll, so
        callers size it with ``_stall_beyond_scan_tail``.
        """
        cfg = self.target_cfg(target)
        idle = await self._wait_bridge_fsm(target, idle=False, tck_cycles=ABORT_MIDFLIGHT_TCK)
        self._record_abort_check(
            STALL_FSM_CHECK_ID,
            f"{context}.stall_fsm",
            self.cfg.tb_if.bridge_fsm_on_path(target, read=read),
            1,
            f"idle={idle} under the {'read' if read else 'write'} READY stall",
        )
        first, _ = unpack_single_op(await self.read_tdr(cfg.single_op_reg), target=cfg)
        self._record_abort_check(
            STALL_BUSY_CHECK_ID,
            f"{context}.stall_busy",
            int(first),
            int(DtpJtag2AxiStatus.BUSY_OR_FULL),
            "first status poll under the READY stall",
        )

    async def _write_with_backpressure(
        self,
        target: str,
        *,
        channels: tuple[str, ...],
        stall_cycles: int,
        context: str,
    ) -> None:
        """Backpressured checked single write.

        The READY stall outlasts the first status poll, so the bridge is
        observed on the stalled path before the write settles at SUCCESS with
        the memory matching the stimulus intent and the request on the bus.
        """
        cfg = self.target_cfg(target)
        size = cfg.default_size
        wstrb = self.target_full_wstrb(target, size)
        addr = self._target_addr(target, self.operation_count + 1)
        data = (0x1020_3040_5060_7080 ^ addr) & self.data_mask(size)
        self.configure_target_backpressure(target, channels=channels, stall_cycles=stall_cycles)
        try:
            before = await self.target_activity_counts(target)
            self.log_target_jtag2axi_op(
                target, context, addr=addr, data=data, size=size, wstrb=wstrb
            )
            await self.write_target_single_raw(
                target, DtpJtag2AxiOp.WRITE, addr, data=data, wstrb=wstrb, size=size
            )
            await self._observe_stall(target, read=False, context=context)
            await self.finish_target_single_write(
                target, addr, data, size=size, wstrb=wstrb, context=context
            )
            await self.expect_target_activity(target, before=before, read=False, context=context)
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
            self.log_target_jtag2axi_op(target, context, addr=addr, size=size)
            await self.write_target_single_raw(target, DtpJtag2AxiOp.READ, addr, size=size)
            await self._observe_stall(target, read=True, context=context)
            await self.finish_target_single_read(target, addr, data, size=size, context=context)
            await self.expect_target_activity(target, before=before, read=True, context=context)
        finally:
            self.clear_target_backpressure(target)
        self.operation_count += 1

    async def run_backpressure_aw_before_w(self) -> None:
        self.log_banner("JTAG2AXI backpressure: AW accepted before delayed W")
        await self.reset_tap()
        rng = self.rng("backpressure_aw_before_w")
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            # WREADY held past the first status poll (seeded margin): the
            # bridge is observed waiting on the write path while AW is
            # already accepted.
            stall = self._stall_beyond_scan_tail(rng, target, scans=2)
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
                stall_cycles=self._stall_beyond_scan_tail(rng, target, scans=2),
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

    def _record_abort_check(
        self, check_id: str, name: str, observed: int, expected: int, context: str = ""
    ) -> bool:
        """Log and record one judgement on the AXI scoreboard without raising."""
        suffix = f" ({context})" if context else ""
        self.log.info(
            "CHECK %-36s expected=0x%x observed=0x%x%s", name, int(expected), int(observed), suffix
        )
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            scoreboard.expect_equal(
                check_id, int(observed), int(expected), context=f"{name}{suffix}"
            )
        return int(observed) == int(expected)

    async def _wait_bridge_fsm(self, target: str, *, idle: bool, tck_cycles: int) -> int:
        """Step TCK in Run-Test/Idle until the bridge's state machine leaves or reaches
        idle, bounded; returns the idle flag last sampled."""
        is_idle = self.cfg.tb_if.bridge_fsm_idle(target)
        for _ in range(tck_cycles):
            if bool(is_idle) == idle:
                break
            await self.tms_step(0)
            is_idle = self.cfg.tb_if.bridge_fsm_idle(target)
        return int(is_idle)

    async def _poll_status_bounded(self, target: str, polls: int) -> int:
        status = int(DtpJtag2AxiStatus.BUSY_OR_FULL)
        for _ in range(polls):
            status, _ = await self.poll_target_single_status(target)
            if status != DtpJtag2AxiStatus.BUSY_OR_FULL:
                break
        return status

    async def _reset_abort_mid_flight(
        self,
        target: str,
        rng,
        *,
        channel: str,
        reset_cycles: int,
        addr_idx: int,
        recovery_xor: int,
        context: str,
    ) -> bool:
        """System reset while the bridge is observed mid-flight on a held write.

        Every judgement is recorded rather than raised so all three bridges
        leave evidence; returns True when the bridge's status settled to
        SUCCESS afterwards and the recovery write ran.
        """
        tb_if = self.cfg.tb_if
        size = self.target_cfg(target).default_size
        addr = self._target_addr(target, addr_idx)
        data = rng.getrandbits(64) & self.data_mask(size)
        before = self.read_target_mem_int(target, addr, size)
        self.configure_target_backpressure(
            target, channels=(channel,), stall_cycles=ABORT_HOLD_CYCLES
        )
        await self.write_target_single_raw(
            target,
            DtpJtag2AxiOp.WRITE,
            addr,
            data=data,
            wstrb=self.target_full_wstrb(target, size),
            size=size,
        )
        idle = await self._wait_bridge_fsm(target, idle=False, tck_cycles=ABORT_MIDFLIGHT_TCK)
        mid_flight = not idle and tb_if.bridge_op_pending(target) == 1
        self._record_abort_check(
            ABORT_MIDFLIGHT_CHECK_ID,
            f"{context}.mid_flight",
            int(mid_flight),
            1,
            f"idle={idle} write_path={tb_if.bridge_fsm_on_path(target, read=False)}",
        )
        tb_if.set_cdc_clear_seen_clear(1)
        await self.wait_sys_cycles(1)
        tb_if.set_cdc_clear_seen_clear(0)
        await self.pulse_system_reset(cycles=reset_cycles)
        self.clear_target_backpressure(target)
        recovered = await self._judge_abort_aftermath(target, addr, before, context=context)
        if recovered:
            await self.verify_target_recovery(
                target, addr=addr + 0x200, data=data ^ recovery_xor, read=False, context=context
            )
        self.operation_count += 1
        return recovered

    async def _judge_abort_aftermath(
        self, target: str, addr: int, before: int, *, context: str
    ) -> bool:
        """Record the idle, CDC-clear, escape, and recovery judgements after the reset."""
        tb_if = self.cfg.tb_if
        size = self.target_cfg(target).default_size
        idle = await self._wait_bridge_fsm(target, idle=True, tck_cycles=ABORT_SETTLE_TCK)
        self._record_abort_check(
            ABORT_FSM_CHECK_ID,
            f"{context}.fsm_idle",
            idle,
            1,
            "after the mid-flight reset",
        )
        self._record_abort_check(
            CDC_CLEAR_CHECK_ID, f"{context}.cdc_clear", tb_if.cdc_clear_seen(target), 1
        )
        self._record_abort_check(
            ABORT_ESCAPE_CHECK_ID,
            f"{context}.no_escape",
            self.read_target_mem_int(target, addr, size),
            before,
            f"addr=0x{addr:x}",
        )
        status = await self._poll_status_bounded(target, ABORT_RECOVERY_POLLS)
        self.scoreboard_expect_completion(target, status, context=f"{context}.recovery")
        recovered = self._record_abort_check(
            ABORT_RECOVERY_CHECK_ID,
            f"{context}.recovery_status",
            status,
            DtpJtag2AxiStatus.SUCCESS,
            f"polls={ABORT_RECOVERY_POLLS} after the mid-flight reset",
        )
        self.status = DtpJtag2AxiStatus(status)
        return recovered

    async def _run_reset_abort(
        self, label: str, *, channel: str, reset_cycles_hi: int, recovery_xor: int, addr_offset: int
    ) -> None:
        """Abort a held write on every bridge, then judge the pass on the collected evidence."""
        await self.reset_tap()
        rng = self.rng(label)
        stuck = []
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            self.log_iteration(
                idx, len(ROBUST_TARGETS), "target=%s system reset while %s is held", target, channel
            )
            recovered = await self._reset_abort_mid_flight(
                target,
                rng,
                channel=channel,
                reset_cycles=rng.randint(1, reset_cycles_hi),
                addr_idx=idx + addr_offset,
                recovery_xor=recovery_xor,
                context=f"{label}.{target}",
            )
            if not recovered:
                stuck.append(target)
        if stuck:
            raise AssertionError(
                f"{label}: {', '.join(stuck)} stayed BUSY_OR_FULL after the mid-flight reset"
            )

    async def run_backpressure_abort_at_data_w(self) -> None:
        self.log_banner("JTAG2AXI system reset while a write is held on the W channel")
        await self._run_reset_abort(
            "abort_w", channel="w", reset_cycles_hi=3, recovery_xor=0x1111, addr_offset=0
        )

    async def run_cdc_clear_abort_narrow_reset_mid_xaction(self) -> None:
        self.log_banner(
            "JTAG2AXI single-cycle system reset while a write is held on the AW channel"
        )
        await self._run_reset_abort(
            "narrow_reset", channel="aw", reset_cycles_hi=1, recovery_xor=0x2222, addr_offset=8
        )

    async def run_cdc_clear_abort_back_to_back_reset(self) -> None:
        self.log_banner("JTAG2AXI back-to-back reset recovery")
        await self.reset_tap()
        rng = self.rng("cdc_back_to_back_reset")
        tb_if = self.cfg.tb_if
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            addr = self._target_addr(target, idx + 16)
            # Seeded per-pass payload and pulse widths: each loop stresses a
            # different back-to-back reset spacing.
            data = rng.getrandbits(64) & self.target_data_mask(target)
            self.log_iteration(idx, len(ROBUST_TARGETS), "target=%s back-to-back reset", target)
            tb_if.set_cdc_clear_seen_clear(1)
            await self.wait_sys_cycles(1)
            tb_if.set_cdc_clear_seen_clear(0)
            await self.pulse_system_reset(cycles=rng.randint(1, 2))
            await self.pulse_system_reset(cycles=rng.randint(1, 3))
            # The CDC's TCK-side isolate-and-clear runs only while TCK runs.
            for _ in range(ABORT_CDC_CLEAR_TCK):
                await self.tms_step(0)
            self._record_abort_check(
                CDC_CLEAR_CHECK_ID,
                f"back_to_back_reset.{target}.cdc_clear",
                tb_if.cdc_clear_seen(target),
                1,
                "tck-side isolate-and-clear after two resets",
            )
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
            size = self.target_cfg(target).default_size
            expected = self.configure_target_error(target, addr, AXI_DECERR, read=False, write=True)
            before = self.read_target_mem_int(target, addr, size)
            status, _ = await self.write_target_single_expect_status(
                target,
                addr,
                rng.getrandbits(32) ^ idx,
                expected,
                context=f"decerr_write.{target}",
            )
            self.assert_equal(f"decerr_write.{target}.status", status, DtpJtag2AxiStatus.DECERR)
            # The responder drops an armed write beat, so the error slot keeps
            # its prior value.
            self.assert_equal(
                f"decerr_write.{target}.no_write_side_effect",
                self.read_target_mem_int(target, addr, size),
                before,
                f"addr=0x{addr:x}",
            )
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
            cfg = self.target_cfg(target)
            # A nonzero preload keeps the slot's word distinguishable from the
            # errored beat's RDATA.
            preload = rng.randrange(1, 1 << cfg.data_width)
            self.write_target_mem_int(target, addr, preload, cfg.default_size)
            expected = self.configure_target_error(target, addr, AXI_DECERR, read=True, write=False)
            status, rdata = await self.read_target_single_expect_status(
                target,
                addr,
                expected,
                context=f"decerr_read.{target}",
            )
            self.assert_equal(f"decerr_read.{target}.status", status, DtpJtag2AxiStatus.DECERR)
            self.check_error_rdata(
                target,
                addr,
                rdata,
                resp=AXI_DECERR,
                preload=preload,
                size=cfg.default_size,
                context=f"decerr_read.{target}",
            )
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
            await self.write_target_single_and_check(
                target, good_addr, good_data, context=f"mixed.good_write.{target}"
            )
            expected = self.configure_target_error(
                target, bad_addr, AXI_DECERR, read=True, write=True
            )
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

    @staticmethod
    def _series_corner_base(target_idx: int, leg: int) -> int:
        """Aligned base of one series leg's window."""
        return SERIES_CORNER_BASE + target_idx * 0x400 + leg * 0x100

    def _record_series_status(
        self, target: str, observed: int, expected: DtpJtag2AxiStatus, *, context: str
    ) -> None:
        """CHK-J2A-FAULT-STATUS on a SERIES_CTRL capture, recorded and asserted."""
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            scoreboard.expect_equal(
                FAULT_STATUS_CHECK_ID,
                DtpJtag2AxiStatus(observed).name,
                DtpJtag2AxiStatus(expected).name,
                context=f"{context} target={target}",
            )
        self.assert_equal(f"{context}.status", observed, expected)

    async def _series_corner_beat(
        self, target: str, addr: int, data: int, *, size: int, increment: int, context: str
    ) -> None:
        """Land one write beat of a programmed series and compare the word it wrote."""
        before = await self.target_activity_counts(target)
        if increment:
            await self.series_data_incr(data, size=size, target=target, back_to_rti=True)
        else:
            await self.series_data_no_incr(data, size=size, target=target, back_to_rti=True)
        await self.wait_for_target_activity(target, before=before, read=False, context=context)
        self.assert_equal(
            f"{context}.mem", self.read_target_mem_int(target, addr, size), data, f"addr=0x{addr:x}"
        )
        self.operation_count += 1

    async def _series_corner_progressions(
        self, target: str, target_idx: int, beats: int, rng
    ) -> None:
        """An incrementing then a fixed-address series: the captured address follows the mode."""
        cfg = self.target_cfg(target)
        size = cfg.default_size
        base = self._series_corner_base(target_idx, 0)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.NOP, 0, reset=1, size=size, target=target)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size, target=target)
        for beat in range(beats):
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            await self._series_corner_beat(
                target,
                base + beat * cfg.beat_bytes,
                data,
                size=size,
                increment=1,
                context=f"series_corner.incr.{target}.{beat}",
            )
        status = await self.check_series_addr(
            target, base + beats * cfg.beat_bytes, size=size, context=f"series_corner.incr.{target}"
        )
        self._record_series_status(
            target, status, DtpJtag2AxiStatus.SUCCESS, context=f"series_corner.incr.{target}"
        )
        addr = self._series_corner_base(target_idx, 1)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, addr, size=size, target=target)
        for beat in range(beats):
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            await self._series_corner_beat(
                target,
                addr,
                data,
                size=size,
                increment=0,
                context=f"series_corner.fixed.{target}.{beat}",
            )
        status = await self.check_series_addr(
            target, addr, size=size, context=f"series_corner.fixed.{target}"
        )
        self._record_series_status(
            target, status, DtpJtag2AxiStatus.SUCCESS, context=f"series_corner.fixed.{target}"
        )
        self.status = status

    async def _series_corner_sticky_status(
        self, target: str, target_idx: int, beats: int, rng
    ) -> None:
        """One faulted beat sets the series status, which holds across the clean beats
        after it until SERIES_CTRL.reset starts a fresh series."""
        cfg = self.target_cfg(target)
        size = cfg.default_size
        base = self._series_corner_base(target_idx, 2)
        # At least one clean beat follows the fault, so the held status is observed
        # after a beat the responder accepted.
        fault_beat = rng.randrange(0, beats - 1)
        resp = rng.choice((AXI_RESP_SLVERR, AXI_RESP_DECERR))
        fault_addr = base + fault_beat * cfg.beat_bytes
        expected = self.configure_target_error(target, fault_addr, resp, read=False, write=True)
        fault_before = self.read_target_mem_int(target, fault_addr, size)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size, target=target)
        for beat in range(beats):
            addr = base + beat * cfg.beat_bytes
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            context = f"series_corner.sticky.{target}.{beat}"
            before = await self.target_activity_counts(target)
            await self.series_data_incr(data, size=size, target=target, back_to_rti=True)
            await self.wait_for_target_activity(target, before=before, read=False, context=context)
            observed = self.read_target_mem_int(target, addr, size)
            if beat == fault_beat:
                self.assert_equal(
                    f"{context}.mem_dropped", observed, fault_before, f"addr=0x{addr:x}"
                )
                # The capture right after the faulted beat carries the code.
                status = await self.check_series_addr(
                    target, addr + cfg.beat_bytes, size=size, context=f"{context}.faulted"
                )
                self._record_series_status(target, status, expected, context=f"{context}.faulted")
            else:
                self.assert_equal(f"{context}.mem", observed, data, f"addr=0x{addr:x}")
            self.operation_count += 1
        # The code holds across the clean beats that followed the fault.
        status = await self.check_series_addr(
            target,
            base + beats * cfg.beat_bytes,
            size=size,
            context=f"series_corner.sticky.{target}",
        )
        self._record_series_status(
            target, status, expected, context=f"series_corner.sticky.{target}.held"
        )
        self.clear_target_errors(target)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.NOP, 0, reset=1, size=size, target=target)
        clear_addr = base + (beats + 1) * cfg.beat_bytes
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, clear_addr, size=size, target=target)
        await self._series_corner_beat(
            target,
            clear_addr,
            rng.getrandbits(cfg.data_width) & self.data_mask(size),
            size=size,
            increment=1,
            context=f"series_corner.sticky.{target}.cleared",
        )
        status = await self.check_series_addr(
            target,
            clear_addr + cfg.beat_bytes,
            size=size,
            context=f"series_corner.sticky.{target}.cleared",
        )
        self._record_series_status(
            target,
            status,
            DtpJtag2AxiStatus.SUCCESS,
            context=f"series_corner.sticky.{target}.cleared",
        )
        self.status = status

    async def _series_corner_interleaved(self, beats: int, rng) -> None:
        """Beats of the three bridges' series landed in seeded interleaved order leave every
        bridge's address progression and every word exact."""
        bases: dict[str, int] = {}
        words: dict[str, list[int]] = {}
        for target_idx, target in enumerate(ROBUST_TARGETS, start=1):
            cfg = self.target_cfg(target)
            size = cfg.default_size
            bases[target] = self._series_corner_base(target_idx, 3)
            words[target] = [
                rng.getrandbits(cfg.data_width) & self.data_mask(size) for _ in range(beats)
            ]
            await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.NOP, 0, reset=1, size=size, target=target)
            await self.jtag2axi_series_ctrl(
                DtpJtag2AxiOp.WRITE, bases[target], size=size, target=target
            )
        for beat in range(beats):
            order = list(ROBUST_TARGETS)
            rng.shuffle(order)
            for target in order:
                cfg = self.target_cfg(target)
                await self._series_corner_beat(
                    target,
                    bases[target] + beat * cfg.beat_bytes,
                    words[target][beat],
                    size=cfg.default_size,
                    increment=1,
                    context=f"series_corner.interleaved.{target}.{beat}",
                )
        for target in ROBUST_TARGETS:
            cfg = self.target_cfg(target)
            size = cfg.default_size
            status = await self.check_series_addr(
                target,
                bases[target] + beats * cfg.beat_bytes,
                size=size,
                context=f"series_corner.interleaved.{target}",
            )
            self._record_series_status(
                target,
                status,
                DtpJtag2AxiStatus.SUCCESS,
                context=f"series_corner.interleaved.{target}",
            )
            for beat in range(beats):
                addr = bases[target] + beat * cfg.beat_bytes
                self.assert_equal(
                    f"series_corner.interleaved.{target}.final#{beat}",
                    self.read_target_mem_int(target, addr, size),
                    words[target][beat],
                    f"addr=0x{addr:x}",
                )
            self.status = status

    async def run_series_corner_all_bridges(self) -> None:
        self.log_banner("JTAG2AXI series corner coverage across all bridges")
        await self.reset_tap()
        rng = self.rng("series_corner_all_bridges")
        # Seeded per-pass beat count, above the two beats a progression needs.
        beats = rng.randint(3, 6)
        self.log_step(1, "Incrementing and fixed-address series on each bridge, %d beats", beats)
        for target_idx, target in enumerate(ROBUST_TARGETS, start=1):
            await self._series_corner_progressions(target, target_idx, beats, rng)
        self.log_step(
            2, "One faulted beat per bridge: the series status holds until SERIES_CTRL.reset"
        )
        for target_idx, target in enumerate(ROBUST_TARGETS, start=1):
            await self._series_corner_sticky_status(target, target_idx, beats, rng)
        self.log_step(3, "Interleaved beats across the three bridges")
        await self._series_corner_interleaved(beats, rng)

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
