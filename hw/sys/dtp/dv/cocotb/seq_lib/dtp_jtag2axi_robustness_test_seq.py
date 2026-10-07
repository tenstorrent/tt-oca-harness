# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross-bridge JTAG2AXI robustness scenarios."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from env.dtp_types import (
    ABORT_ESCAPE_CHECK_ID,
    ABORT_FSM_CHECK_ID,
    ABORT_MIDFLIGHT_CHECK_ID,
    ABORT_RECOVERY_CHECK_ID,
    CDC_CLEAR_CHECK_ID,
    CDC_PHASE_CHECK_ID,
    ORPHAN_DISCARD_CHECK_ID,
    ORPHAN_DRAIN_CHECK_ID,
    ORPHAN_ORDER_CHECK_ID,
    STALL_BUSY_CHECK_ID,
    STALL_FSM_CHECK_ID,
    STALL_HOLD_CHECK_ID,
    DtpJtag2AxiOp,
    DtpJtag2AxiStatus,
    DtpJtagInstr,
    unpack_single_op,
)
from ocah_axi_vip import RESP_DECERR, RESP_SLVERR
from ocah_jtag_vip import OcahJtagState
from ocah_lib import OcahKnobs

from .dtp_jtag2axi_base_test_seq import dtp_jtag2axi_base_test_seq

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
# SINGLE_OP captures within which the status leaves BUSY_OR_FULL after the
# reset; one capture is one Capture-DR from Run-Test/Idle, the instruction
# loaded once and no idle TCK after it.
ABORT_RECOVERY_POLLS = 8
# TCK cycles after a reset pulse for the CDC controller to run its TCK-side
# isolate-and-clear on an idle bridge.
ABORT_CDC_CLEAR_TCK = 32
# TCK-side clear with a request held on the fabric: TRST asserted with one to
# four TCK cycles clocked under it and held until the TAP leaves
# Test-Logic-Reset, or five TMS-high cycles into Test-Logic-Reset from any
# state.
ORPHAN_TRST_HOLD_TCK = (1, 4)
ORPHAN_TLR_WALK = 5
# System cycles from the last TCK cycle of the reset to a stall release inside
# the clear. The ACLK side starts its clear about two system cycles after the
# TCK-side reset and holds it until TCK clocks the clear's phases after the
# reset is released.
ORPHAN_IN_CLEAR_CYCLES = (6, 16)
# TCK cycles in Run-Test/Idle after Test-Logic-Reset for the CDC's four-phase
# isolate-and-clear to finish; each phase handshake costs a few cycles of each
# clock, and TCK is the slower one.
ORPHAN_CLEAR_TCK = (64, 96)
# System cycles a finished clear is probed for: a clear in progress sets the
# sticky clear-seen flag within them.
ORPHAN_CLEAR_PROBE_CYCLES = 4
# TCK cycles for the queued request's push into the CDC once the state machine
# has left idle, and system cycles for it to cross the three-stage pointer
# synchronizers into the destination spill register.
ORPHAN_QUEUE_TCK = 2
ORPHAN_QUEUE_CYCLES = 16
# Release offsets of the aligned leg, in system cycles after the TRST
# assertion (before it when negative). A pass starts at its scenario seed
# modulo the span and each bridge and direction takes the next offset, so
# consecutive passes walk every offset on every leg.
ORPHAN_ALIGN_MIN = -2
ORPHAN_ALIGN_SPAN = 6
# Each drain point takes three consecutive 0x400 slots, for its held, queued
# and follow-on requests; the recovery accesses take the slots after the last.
ORPHAN_SLOT_STRIDE = 3
# Negative validation: flips bit 0 of every CHK-J2A-ORPHAN-* expectation.
ORPHAN_NEGATIVE_KNOB = "DTP_J2A_ORPHAN_NEGATIVE"
# Phases of the ACLK-side clear sequence a system reset is placed in while the
# sequence runs: a bridge's pass takes the phase at its loop index plus the
# scenario seed, so the passes visit every phase on every bridge.
B2B_CLEAR_PHASES = ("clear", "wait_clear_phase_ack", "post_clear", "finished")
# TCK cycles stepped in Run-Test/Idle while waiting for the phase, and after
# the reset for the restarted sequence to complete: the four phase handshakes
# each cost a few cycles of each clock, and TCK is the slower one.
B2B_PHASE_TCK = 64
# TCK or system clock edges after the other side's reset at which a four-phase
# receiver spends one cycle waiting for its isolate acknowledge: the request
# crosses two synchronizer stages, and the acknowledge flop loads on the third
# edge while the receiver samples the value before it.
B2B_RECEIVER_WAIT_EDGES = 3
# First slot of the recovery accesses after the receiver legs; the per-bridge
# loop takes the slots below it.
B2B_RECOVERY_SLOT = 20


@dataclass
class _PhaseLanding:
    """A system reset deposited on the system clock edge after a phase is observed:
    ``fired`` once the phase is seen, ``landed`` once the pulse has been released."""

    seen: int = 0
    fired: bool = False
    landed: bool = False


class _OrphanDrain(Enum):
    """When the responder releases a request held across a TCK-side clear.

    IN_CLEAR: while the TAP still holds the bridge's TCK side in reset.
    AFTER_CLEAR: once the clear has finished.
    QUEUED: as AFTER_CLEAR, with a request of the new session waiting behind it.
    ALIGNED: a swept number of system cycles around the TRST assertion.
    """

    IN_CLEAR = "in_clear"
    AFTER_CLEAR = "after_clear"
    QUEUED = "queued"
    ALIGNED = "aligned"


@dataclass(frozen=True)
class _OrphanLeg:
    """One bridge and direction at one drain point, with its seeded choices.

    ``resp`` is the leg's error code: the held read's response and the queued
    write's. The follow-on operation gets the other one.
    """

    target: str
    read: bool
    drain: _OrphanDrain
    slot: int
    via_trst: bool
    trst_hold: int
    clear_tck: int
    in_clear_wait: int
    offset: int
    resp: int
    context: str

    @property
    def held(self) -> str:
        """The channel whose READY stall holds the request."""
        return "ar" if self.read else "aw"

    @property
    def landings(self) -> int:
        """Port completions of the direction once the stall is released."""
        return 2 if self.drain is _OrphanDrain.QUEUED else 1


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

    def _stall_beyond_scan_tail(self, rng: random.Random, target: str, *, scans: int = 2) -> int:
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
            target,
            STALL_FSM_CHECK_ID,
            f"{context}.stall_fsm",
            observed=self.cfg.tb_if.bridge_fsm_on_path(target, read=read),
            expected=1,
            context=f"idle={idle} under the {'read' if read else 'write'} READY stall",
        )
        first, _ = unpack_single_op(await self.read_tdr(cfg.single_op_reg), target=cfg)
        self._record_abort_check(
            target,
            STALL_BUSY_CHECK_ID,
            f"{context}.stall_busy",
            observed=int(first),
            expected=int(DtpJtag2AxiStatus.BUSY_OR_FULL),
            context="first status poll under the READY stall",
        )

    def _judge_stall_hold(
        self,
        target: str,
        before: dict[str, int],
        after: dict[str, int],
        *,
        op_channels: tuple[str, ...],
        stalled: tuple[str, ...],
        context: str,
    ) -> None:
        """The READY stall seen on the port across one operation (CHK-J2A-STALL-HOLD).

        Each channel in ``stalled`` held its VALID against a low READY for at
        least one cycle; every other channel of the operation was accepted on
        its first VALID cycle. The tb_top stall counters advance only while
        ``axi_sva_en`` is set, so a counted cycle is one the port's
        ``ocah_axi_sva`` stability rules evaluated.
        """
        for channel in op_channels:
            delta = after[channel] - before[channel]
            if channel in stalled:
                self._record_abort_check(
                    target,
                    STALL_HOLD_CHECK_ID,
                    f"{context}.{channel}_stall_hold",
                    observed=int(delta > 0),
                    expected=1,
                    context=f"{channel}_stall_delta={delta}",
                )
            else:
                self._record_abort_check(
                    target,
                    STALL_HOLD_CHECK_ID,
                    f"{context}.{channel}_accepted_unstalled",
                    observed=delta,
                    expected=0,
                    context=f"{channel}_stall_delta={delta}",
                )

    async def _write_with_backpressure(
        self,
        target: str,
        *,
        channels: tuple[str, ...],
        stall_cycles: int,
        context: str,
        judged: tuple[str, ...] = ("aw", "w"),
    ) -> None:
        """Backpressured checked single write.

        The READY stall outlasts the first status poll, so the bridge is
        observed on the stalled path before the write settles at SUCCESS with
        the memory matching the stimulus intent and the request on the bus;
        the port's stall counters show the stall on exactly the write channels
        in ``channels`` among the ``judged`` ones.
        """
        cfg = self.target_cfg(target)
        size = cfg.default_size
        wstrb = self.target_full_wstrb(target, size)
        addr = self._target_addr(target, self.operation_count + 1)
        data = (0x1020_3040_5060_7080 ^ addr) & self.data_mask(size)
        self.configure_target_backpressure(target, channels=channels, stall_cycles=stall_cycles)
        try:
            before = await self.target_activity_counts(target)
            stalls_before = await self.target_stall_counts(target)
            self.log_target_jtag2axi_op(
                target, context, addr=addr, data=data, size=size, wstrb=wstrb
            )
            await self.write_target_single_raw(
                target, DtpJtag2AxiOp.WRITE, addr, data=data, wstrb=wstrb, size=size
            )
            await self._observe_stall(target, read=False, context=context)
            status, _ = await self.finish_target_single_write(
                target, addr, data, size=size, wstrb=wstrb, context=context
            )
            self.check_target_word(target, addr, data, size=size, context=context)
            self.status = DtpJtag2AxiStatus(status)
            await self.expect_target_activity(target, before=before, read=False, context=context)
            self._judge_stall_hold(
                target,
                stalls_before,
                await self.target_stall_counts(target),
                op_channels=judged,
                stalled=channels,
                context=context,
            )
        finally:
            self.clear_target_backpressure(target)
        self.operation_count += 1

    async def _write_polled_after_completion(
        self, target: str, addr: int, data: int, *, context: str
    ) -> None:
        """Checked single write whose first status capture follows its completion.

        TCK steps in Run-Test/Idle until the bridge drops its pending flag,
        so the first capture already reads the settled status.
        """
        cfg = self.target_cfg(target)
        size = cfg.default_size
        wstrb = self.target_full_wstrb(target, size)
        data &= self.data_mask(size)
        self.log_target_jtag2axi_op(target, context, addr=addr, data=data, size=size, wstrb=wstrb)
        await self.write_target_single_raw(
            target, DtpJtag2AxiOp.WRITE, addr, data=data, wstrb=wstrb, size=size
        )
        for _ in range(ABORT_SETTLE_TCK):
            if not self.cfg.tb_if.bridge_op_pending(target):
                break
            await self.tms_step(0)
        status, _ = await self.finish_target_single_write(
            target, addr, data, size=size, wstrb=wstrb, context=context
        )
        self.status = DtpJtag2AxiStatus(status)
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
            stalls_before = await self.target_stall_counts(target)
            self.log_target_jtag2axi_op(target, context, addr=addr, size=size)
            await self.write_target_single_raw(target, DtpJtag2AxiOp.READ, addr, size=size)
            await self._observe_stall(target, read=True, context=context)
            status, _ = await self.finish_target_single_read(
                target, addr, data, size=size, context=context
            )
            self.status = DtpJtag2AxiStatus(status)
            await self.expect_target_activity(target, before=before, read=True, context=context)
            self._judge_stall_hold(
                target,
                stalls_before,
                await self.target_stall_counts(target),
                op_channels=("ar",),
                stalled=channels,
                context=context,
            )
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
            # settled status: the AW+W stall of sixteen scans settles in the
            # long-wait poll class, the AW-only and AR stalls of two scans in
            # the short-wait class.
            stall = self._stall_beyond_scan_tail(rng, target, scans=16)
            self.log_iteration(idx, len(targets), "target=%s stall=%d", target, stall)
            await self._write_with_backpressure(
                target,
                channels=("aw", "w"),
                stall_cycles=stall,
                context=f"long_stall.write.{target}",
            )
            # AW held alone, the responder taking the W beat during the AW
            # stall (W before AW); only AW is judged.
            self.arm_target_w_before_aw(target)
            await self._write_with_backpressure(
                target,
                channels=("aw",),
                stall_cycles=self._stall_beyond_scan_tail(rng, target, scans=2),
                context=f"long_stall.aw_only.{target}",
                judged=("aw",),
            )
            await self._read_with_backpressure(
                target,
                channels=("ar",),
                stall_cycles=self._stall_beyond_scan_tail(rng, target, scans=2),
                context=f"long_stall.read.{target}",
            )
            await self._write_polled_after_completion(
                target,
                self._target_addr(target, idx + 44),
                rng.getrandbits(self.target_cfg(target).data_width),
                context=f"long_stall.settled.{target}",
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
            status, _ = await self.write_target_single_and_check(
                target,
                boundary_addr,
                boundary_data,
                size=size,
                context=f"long_stall.boundary.{target}",
            )
            self.status = DtpJtag2AxiStatus(status)

    def _record_abort_check(
        self,
        target: str,
        check_id: str,
        name: str,
        *,
        observed: int,
        expected: int,
        context: str = "",
    ) -> bool:
        """Record one judgement of ``target`` without raising, so every bridge leaves evidence."""
        suffix = f" ({context})" if context else ""
        return self.target_evidence(target).expect_equal(
            check_id, int(observed), int(expected), context=f"{name}{suffix}"
        )

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

    async def _poll_status_bounded(self, target: str, polls: int) -> tuple[int, int, int]:
        """Capture SINGLE_OP from Run-Test/Idle up to ``polls`` times, the instruction
        loaded once, until the status leaves BUSY_OR_FULL; returns (status, data, captures)."""
        cfg = self.target_cfg(target)
        await self.load_ir(DtpJtagInstr[cfg.single_op_reg])
        status = int(DtpJtag2AxiStatus.BUSY_OR_FULL)
        rdata = 0
        captures = 0
        while captures < polls:
            item = await self.shift_dr(0, cfg.single_op_len)
            captures += 1
            status, rdata = unpack_single_op(item.result, target=cfg)
            if status != DtpJtag2AxiStatus.BUSY_OR_FULL:
                break
        self.log.info(
            "%s SINGLE_OP status=%s captures=%d/%d",
            target,
            DtpJtag2AxiStatus(status).name,
            captures,
            polls,
        )
        return status, rdata, captures

    async def _wait_held_on_bus(
        self, target: str, channel: str, stall_count: int, tck_cycles: int
    ) -> bool:
        """Step TCK in Run-Test/Idle until the port's ``channel`` stall counter has
        advanced past ``stall_count``: the request VALID waits on the bus against a low
        READY. The bridge pushes the request into its CDC only on TCK edges."""
        for step in range(tck_cycles + 1):
            if (await self.target_stall_counts(target))[channel] > stall_count:
                return True
            if step < tck_cycles:
                await self.tms_step(0)
        return False

    async def _reset_abort_mid_flight(
        self,
        target: str,
        rng: random.Random,
        *,
        channels: tuple[str, ...],
        reset_cycles: int,
        addr_idx: int,
        recovery_xor: int,
        context: str,
        second_reset_cycles: int = 0,
    ) -> bool:
        """System reset while the bridge is observed mid-flight on a held write.

        The reset lands once the first channel in ``channels`` holds its
        VALID on the bus against the low READY. A non-zero
        ``second_reset_cycles`` pulses the reset again once the first clear
        has completed, before the status is polled. With the AXI scoreboard
        attached every judgement is recorded rather than raised, so all three
        bridges leave evidence; without it the first failing judgement raises.
        Returns True when the bridge reported the discarded write as DECERR
        afterwards and the recovery write ran.
        """
        tb_if = self.cfg.tb_if
        size = self.target_cfg(target).default_size
        addr = self._target_addr(target, addr_idx)
        data = rng.getrandbits(64) & self.data_mask(size)
        before = self.read_target_mem_int(target, addr, size)
        self.configure_target_backpressure(
            target, channels=channels, stall_cycles=ABORT_HOLD_CYCLES
        )
        held = channels[0]
        stalls_before = await self.target_stall_counts(target)
        # The reset aborts this write, so it arms no strobe credit;
        # CHK-J2A-ABORT-ESCAPE judges its slot.
        await self.write_target_single_raw(
            target,
            DtpJtag2AxiOp.WRITE,
            addr,
            data=data,
            wstrb=self.target_full_wstrb(target, size),
            size=size,
            arm_strobes=False,
        )
        idle = await self._wait_bridge_fsm(target, idle=False, tck_cycles=ABORT_MIDFLIGHT_TCK)
        on_bus = await self._wait_held_on_bus(
            target, held, stalls_before[held], ABORT_MIDFLIGHT_TCK
        )
        mid_flight = not idle and tb_if.bridge_op_pending(target) == 1 and on_bus
        self._record_abort_check(
            target,
            ABORT_MIDFLIGHT_CHECK_ID,
            f"{context}.mid_flight",
            observed=int(mid_flight),
            expected=1,
            context=f"idle={idle} write_path={tb_if.bridge_fsm_on_path(target, read=False)} "
            f"{held}_held={int(on_bus)}",
        )
        await self._clear_cdc_clear_seen()
        await self.pulse_system_reset(cycles=reset_cycles)
        self.clear_target_backpressure(target)
        recovered = await self._judge_abort_aftermath(
            target, addr, before, context=context, second_reset_cycles=second_reset_cycles
        )
        if recovered:
            self.status = await self.verify_target_recovery(
                target, addr=addr + 0x200, data=data ^ recovery_xor, read=False, context=context
            )
            # A write the bridge holds across the reset lands only once it is
            # issued, which can follow the first sample, so the slot is
            # judged again.
            self._record_abort_check(
                target,
                ABORT_ESCAPE_CHECK_ID,
                f"{context}.no_escape_after_recovery",
                observed=self.read_target_mem_int(target, addr, size),
                expected=before,
                context=f"addr=0x{addr:x}",
            )
        self.operation_count += 1
        return recovered

    async def _second_reset(self, target: str, cycles: int, *, context: str) -> None:
        """Pulse the system reset again on an idle bridge whose first clear has
        completed, and record its CDC clear."""
        tb_if = self.cfg.tb_if
        for _ in range(ABORT_SETTLE_TCK):
            await self.tms_step(0)
        await self._clear_cdc_clear_seen()
        await self.pulse_system_reset(cycles=cycles)
        for _ in range(ABORT_CDC_CLEAR_TCK):
            await self.tms_step(0)
        self._record_abort_check(
            target,
            CDC_CLEAR_CHECK_ID,
            f"{context}.second_cdc_clear",
            observed=tb_if.cdc_clear_seen(target),
            expected=1,
            context="tck-side isolate-and-clear after the second reset",
        )

    async def _judge_abort_aftermath(
        self,
        target: str,
        addr: int,
        before: int,
        *,
        context: str,
        second_reset_cycles: int = 0,
    ) -> bool:
        """Record the idle, CDC-clear, escape, and recovery judgements after the reset."""
        tb_if = self.cfg.tb_if
        size = self.target_cfg(target).default_size
        idle = await self._wait_bridge_fsm(target, idle=True, tck_cycles=ABORT_SETTLE_TCK)
        self._record_abort_check(
            target,
            ABORT_FSM_CHECK_ID,
            f"{context}.fsm_idle",
            observed=idle,
            expected=1,
            context="after the mid-flight reset",
        )
        self._record_abort_check(
            target,
            CDC_CLEAR_CHECK_ID,
            f"{context}.cdc_clear",
            observed=tb_if.cdc_clear_seen(target),
            expected=1,
        )
        self._record_abort_check(
            target,
            ABORT_ESCAPE_CHECK_ID,
            f"{context}.no_escape",
            observed=self.read_target_mem_int(target, addr, size),
            expected=before,
            context=f"addr=0x{addr:x}",
        )
        if second_reset_cycles:
            await self._second_reset(target, second_reset_cycles, context=context)
        status, _, captures = await self._poll_status_bounded(target, ABORT_RECOVERY_POLLS)
        self.scoreboard_expect_completion(
            target, status, context=f"{context}.recovery", polls=ABORT_RECOVERY_POLLS
        )
        recovered = self._record_abort_check(
            target,
            ABORT_RECOVERY_CHECK_ID,
            f"{context}.recovery_status",
            observed=status,
            expected=DtpJtag2AxiStatus.DECERR,
            context=f"status={DtpJtag2AxiStatus(status).name} "
            f"captures={captures}/{ABORT_RECOVERY_POLLS} after the mid-flight reset",
        )
        self.status = DtpJtag2AxiStatus(status)
        return recovered

    async def _reset_abort_read_response(
        self, target: str, rng: random.Random, *, addr_idx: int, context: str
    ) -> bool:
        """System reset while a SINGLE_OP read's response is outstanding.

        tb_top asserts the reset from the clock edge that completes the read's
        AR handshake, so the R beat never reaches the bridge. The bridge
        discards the read: SINGLE_OP reads DECERR with a zero data field, and a
        read of the same slot then returns the preloaded word. Returns True
        when the discard was reported and the follow-on read ran.
        """
        tb_if = self.cfg.tb_if
        cfg = self.target_cfg(target)
        size = cfg.default_size
        addr = self._target_addr(target, addr_idx)
        word = self.random_distinct_word(rng, target)
        self.write_target_mem_int(target, addr, word, size)
        await self._clear_cdc_clear_seen()
        resets_before = tb_if.sample("sys_rst_assert_count")
        tb_if.arm_reset_on_read(target, cycles=1)
        await self.write_target_single_raw(target, DtpJtag2AxiOp.READ, addr, size=size)
        fired = False
        for step in range(ABORT_MIDFLIGHT_TCK + 1):
            if tb_if.sample("sys_rst_assert_count") != resets_before:
                fired = True
                break
            if step < ABORT_MIDFLIGHT_TCK:
                await self.tms_step(0)
        await self.wait_sys_cycles(4)
        tb_if.disarm_reset_on_read()
        self.check_reset_counted(
            "sys_rst_assert_count",
            resets_before,
            tb_if.sample("sys_rst_assert_count"),
            f"{context} armed on the AR handshake",
        )
        self._record_abort_check(
            target,
            ABORT_MIDFLIGHT_CHECK_ID,
            f"{context}.mid_flight",
            observed=int(fired),
            expected=1,
            context="reset asserted on the AR handshake",
        )
        idle = await self._wait_bridge_fsm(target, idle=True, tck_cycles=ABORT_SETTLE_TCK)
        self._record_abort_check(
            target,
            ABORT_FSM_CHECK_ID,
            f"{context}.fsm_idle",
            observed=idle,
            expected=1,
            context="after the read-response reset",
        )
        self._record_abort_check(
            target,
            CDC_CLEAR_CHECK_ID,
            f"{context}.cdc_clear",
            observed=tb_if.cdc_clear_seen(target),
            expected=1,
        )
        status, rdata, captures = await self._poll_status_bounded(target, ABORT_RECOVERY_POLLS)
        self.scoreboard_expect_completion(
            target, status, context=f"{context}.recovery", polls=ABORT_RECOVERY_POLLS
        )
        recovered = self._record_abort_check(
            target,
            ABORT_RECOVERY_CHECK_ID,
            f"{context}.recovery_status",
            observed=status,
            expected=DtpJtag2AxiStatus.DECERR,
            context=f"status={DtpJtag2AxiStatus(status).name} "
            f"captures={captures}/{ABORT_RECOVERY_POLLS} after the read-response reset",
        )
        self._record_abort_check(
            target,
            ABORT_RECOVERY_CHECK_ID,
            f"{context}.discarded_read_data",
            observed=rdata & self.target_data_mask(target),
            expected=0,
            context="data field of the discarded read",
        )
        self.status = DtpJtag2AxiStatus(status)
        if recovered:
            status, _ = await self.read_target_single_and_check(
                target, addr, word, size=size, context=f"{context}.recover_read"
            )
            self.status = DtpJtag2AxiStatus(status)
        self.operation_count += 1
        return recovered

    async def _run_read_response_abort(self, label: str, *, addr_offset: int) -> None:
        """Discard a read with its response outstanding on every bridge, then judge the pass."""
        rng = self.rng(label)
        stuck = []
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            self.log_iteration(
                idx,
                len(ROBUST_TARGETS),
                "target=%s system reset with the read response outstanding",
                target,
            )
            recovered = await self._reset_abort_read_response(
                target, rng, addr_idx=idx + addr_offset, context=f"{label}.{target}"
            )
            if not recovered:
                stuck.append(target)
        if stuck:
            raise AssertionError(
                f"{label}: {', '.join(stuck)} did not report the discarded read as DECERR"
            )

    async def _reset_abort_address_phase(
        self,
        target: str,
        rng: random.Random,
        *,
        read: bool,
        reset_cycles: int,
        addr_idx: int,
        context: str,
    ) -> bool:
        """System reset with the TAP holding Update-DR of a SINGLE_OP, so the CDC's
        clear reaches the bridge in the one TCK cycle its state machine spends in
        the address state.

        The pulse lands with TCK idle. The bridge latches the operation on the
        first TCK edge after it and moves onto the address path on the second;
        the clear, two TCK edges behind the reset through the CDC's
        synchronizer, returns the state machine to idle on the third with no
        request pushed into the crossing. SINGLE_OP then reads DECERR, with a
        zero data field for a read. Returns True when the discard was reported
        and the recovery access ran.
        """
        tb_if = self.cfg.tb_if
        size = self.target_cfg(target).default_size
        addr = self._target_addr(target, addr_idx)
        word = self.random_distinct_word(rng, target)
        direction = "read" if read else "write"
        if read:
            self.write_target_mem_int(target, addr, word, size)
        before = self.read_target_mem_int(target, addr, size)
        await self.scan_target_single_to_update_dr(
            target,
            DtpJtag2AxiOp.READ if read else DtpJtag2AxiOp.WRITE,
            addr,
            data=0 if read else word,
            wstrb=0 if read else self.target_full_wstrb(target, size),
            size=size,
        )
        await self._clear_cdc_clear_seen()
        await self.pulse_system_reset(cycles=reset_cycles)
        # The reset clears the port's request counters: quiet means no request
        # counted since the pulse.
        activity_before = await self.target_activity_counts(target)
        await self.tms_step(0)
        await self.tms_step(0)
        on_path = tb_if.bridge_fsm_on_path(target, read=read)
        pending = tb_if.bridge_op_pending(target)
        quiet = await self.target_activity_counts(target) == activity_before
        self._record_abort_check(
            target,
            ABORT_MIDFLIGHT_CHECK_ID,
            f"{context}.mid_flight",
            observed=int(on_path and pending and quiet),
            expected=1,
            context=f"{direction}_path={on_path} pending={pending} port_quiet={int(quiet)} "
            "in the address state",
        )
        await self.tms_step(0)
        self._record_abort_check(
            target,
            ABORT_FSM_CHECK_ID,
            f"{context}.fsm_idle",
            observed=int(tb_if.bridge_fsm_idle(target) and not tb_if.bridge_op_pending(target)),
            expected=1,
            context="one TCK edge after the address state",
        )
        self._record_abort_check(
            target,
            CDC_CLEAR_CHECK_ID,
            f"{context}.cdc_clear",
            observed=tb_if.cdc_clear_seen(target),
            expected=1,
        )
        for _ in range(ABORT_CDC_CLEAR_TCK):
            await self.tms_step(0)
        quiet = await self.target_activity_counts(target) == activity_before
        self._record_abort_check(
            target,
            ABORT_ESCAPE_CHECK_ID,
            f"{context}.no_request",
            observed=int(quiet),
            expected=1,
            context="no AW, W or AR reached the port",
        )
        self._record_abort_check(
            target,
            ABORT_ESCAPE_CHECK_ID,
            f"{context}.no_escape",
            observed=self.read_target_mem_int(target, addr, size),
            expected=before,
            context=f"addr=0x{addr:x}",
        )
        status, rdata, captures = await self._poll_status_bounded(target, ABORT_RECOVERY_POLLS)
        self.scoreboard_expect_completion(
            target, status, context=f"{context}.recovery", polls=ABORT_RECOVERY_POLLS
        )
        recovered = self._record_abort_check(
            target,
            ABORT_RECOVERY_CHECK_ID,
            f"{context}.recovery_status",
            observed=status,
            expected=DtpJtag2AxiStatus.DECERR,
            context=f"status={DtpJtag2AxiStatus(status).name} "
            f"captures={captures}/{ABORT_RECOVERY_POLLS} after the address-phase reset",
        )
        if read:
            self._record_abort_check(
                target,
                ABORT_RECOVERY_CHECK_ID,
                f"{context}.discarded_read_data",
                observed=rdata & self.target_data_mask(target),
                expected=0,
                context="data field of the discarded read",
            )
        self.status = DtpJtag2AxiStatus(status)
        if recovered:
            self.status = await self.verify_target_recovery(
                target,
                addr=addr + 0x200,
                data=self.random_distinct_word(rng, target, word),
                read=read,
                context=context,
            )
        self.operation_count += 1
        return recovered

    async def _run_address_phase_aborts(
        self, label: str, *, reset_cycles_hi: int, addr_offset: int
    ) -> None:
        """Discard a SINGLE_OP in its address state on every bridge, a write then a
        read, then judge the pass on the collected evidence."""
        rng = self.rng(label)
        stuck = []
        legs = [(target, read) for target in ROBUST_TARGETS for read in (False, True)]
        for idx, (target, read) in enumerate(legs, start=1):
            direction = "read" if read else "write"
            self.log_iteration(
                idx,
                len(legs),
                "target=%s system reset with the %s in its address state",
                target,
                direction,
            )
            recovered = await self._reset_abort_address_phase(
                target,
                rng,
                read=read,
                reset_cycles=rng.randint(1, reset_cycles_hi),
                addr_idx=idx + addr_offset,
                context=f"{label}.{target}.{direction}",
            )
            if not recovered:
                stuck.append(f"{target}.{direction}")
        if stuck:
            raise AssertionError(
                f"{label}: {', '.join(stuck)} did not report the operation discarded in its "
                "address state as DECERR"
            )

    async def _reset_abort_series(
        self, target: str, rng: random.Random, *, addr_idx: int, reset_cycles: int, context: str
    ) -> bool:
        """System reset while a series write beat is held on the W channel.

        The reset discards the series operation: SERIES_CTRL reads DECERR and
        keeps the held beat's address, since the beat never completed. After
        SERIES_CTRL.reset a beat programmed at that address lands. Returns
        True when the discard was reported and the follow-on beat ran.
        """
        tb_if = self.cfg.tb_if
        cfg = self.target_cfg(target)
        size = cfg.default_size
        addr = self._target_addr(target, addr_idx)
        data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
        before = self.read_target_mem_int(target, addr, size)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.NOP, 0, reset=1, size=size, target=target)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, addr, size=size, target=target)
        self.configure_target_backpressure(target, channels=("w",), stall_cycles=ABORT_HOLD_CYCLES)
        stalls_before = await self.target_stall_counts(target)
        await self.series_data_incr(data, size=size, target=target, back_to_rti=True)
        idle = await self._wait_bridge_fsm(target, idle=False, tck_cycles=ABORT_MIDFLIGHT_TCK)
        on_bus = await self._wait_held_on_bus(target, "w", stalls_before["w"], ABORT_MIDFLIGHT_TCK)
        self._record_abort_check(
            target,
            ABORT_MIDFLIGHT_CHECK_ID,
            f"{context}.mid_flight",
            observed=int(not idle and on_bus),
            expected=1,
            context=f"idle={idle} w_held={int(on_bus)}",
        )
        await self._clear_cdc_clear_seen()
        await self.pulse_system_reset(cycles=reset_cycles)
        self.clear_target_backpressure(target)
        idle = await self._wait_bridge_fsm(target, idle=True, tck_cycles=ABORT_SETTLE_TCK)
        self._record_abort_check(
            target,
            ABORT_FSM_CHECK_ID,
            f"{context}.fsm_idle",
            observed=idle,
            expected=1,
            context="after the series reset",
        )
        self._record_abort_check(
            target,
            CDC_CLEAR_CHECK_ID,
            f"{context}.cdc_clear",
            observed=tb_if.cdc_clear_seen(target),
            expected=1,
        )
        self._record_abort_check(
            target,
            ABORT_ESCAPE_CHECK_ID,
            f"{context}.no_escape",
            observed=self.read_target_mem_int(target, addr, size),
            expected=before,
            context=f"addr=0x{addr:x}",
        )
        status = await self.check_series_addr(target, addr, size=size, context=f"{context}.kept")
        recovered = self._record_abort_check(
            target,
            ABORT_RECOVERY_CHECK_ID,
            f"{context}.series_status",
            observed=status,
            expected=DtpJtag2AxiStatus.DECERR,
            context=f"SERIES_CTRL status={DtpJtag2AxiStatus(status).name} after the series reset",
        )
        self.status = DtpJtag2AxiStatus(status)
        if recovered:
            await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.NOP, 0, reset=1, size=size, target=target)
            await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, addr, size=size, target=target)
            await self.series_write_beat(
                target,
                data ^ self.data_mask(size),
                addr=addr,
                size=size,
                increment=True,
                context=f"{context}.recover",
            )
            status = await self.check_series_addr(
                target, addr + cfg.beat_bytes, size=size, context=f"{context}.recover"
            )
            self._record_series_status(
                target, status, DtpJtag2AxiStatus.SUCCESS, context=f"{context}.recover"
            )
            self.status = DtpJtag2AxiStatus(status)
        self.operation_count += 1
        return recovered

    async def _run_series_abort(
        self, label: str, *, reset_cycles_hi: int, addr_offset: int
    ) -> None:
        """Discard a held series write beat on every bridge, then judge the pass."""
        rng = self.rng(label)
        stuck = []
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            self.log_iteration(
                idx,
                len(ROBUST_TARGETS),
                "target=%s system reset while a series beat is held",
                target,
            )
            recovered = await self._reset_abort_series(
                target,
                rng,
                addr_idx=idx + addr_offset,
                reset_cycles=rng.randint(1, reset_cycles_hi),
                context=f"{label}.{target}",
            )
            if not recovered:
                stuck.append(target)
        if stuck:
            raise AssertionError(
                f"{label}: {', '.join(stuck)} did not report the discarded series write as DECERR"
            )

    async def _run_reset_abort(
        self,
        label: str,
        *,
        channels: tuple[str, ...],
        reset_cycles_hi: int,
        recovery_xor: int,
        addr_offset: int,
        second_reset: bool = False,
    ) -> None:
        """Abort a held write on every bridge, then judge the pass on the collected evidence."""
        await self.reset_tap()
        rng = self.rng(label)
        stuck = []
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            self.log_iteration(
                idx,
                len(ROBUST_TARGETS),
                "target=%s system reset while %s is held",
                target,
                "+".join(channels),
            )
            recovered = await self._reset_abort_mid_flight(
                target,
                rng,
                channels=channels,
                reset_cycles=rng.randint(1, reset_cycles_hi),
                addr_idx=idx + addr_offset,
                recovery_xor=recovery_xor,
                context=f"{label}.{target}",
                second_reset_cycles=rng.randint(1, reset_cycles_hi) if second_reset else 0,
            )
            if not recovered:
                stuck.append(target)
        if stuck:
            raise AssertionError(
                f"{label}: {', '.join(stuck)} did not report the discarded write as DECERR "
                "after the mid-flight reset"
            )

    async def run_backpressure_abort_at_data_w(self) -> None:
        self.log_banner("JTAG2AXI system reset while a write is held on the W channel")
        await self._run_reset_abort(
            "abort_w", channels=("w",), reset_cycles_hi=3, recovery_xor=0x1111, addr_offset=0
        )
        await self._run_series_abort("abort_w_series", reset_cycles_hi=3, addr_offset=4)

    async def run_cdc_clear_abort_narrow_reset_mid_xaction(self) -> None:
        self.log_banner(
            "JTAG2AXI single-cycle system reset while a write is held on the AW channel"
        )
        # The responder accepts W independently of AW, so W is held with AW:
        # neither channel completes a handshake before the reset.
        await self._run_reset_abort(
            "narrow_reset",
            channels=("aw", "w"),
            reset_cycles_hi=1,
            recovery_xor=0x2222,
            addr_offset=8,
            second_reset=True,
        )
        await self._run_read_response_abort("narrow_reset_read", addr_offset=12)
        await self._run_address_phase_aborts("address_phase", reset_cycles_hi=3, addr_offset=27)
        await self._run_tap_reset_orphans()

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
            expected = self.configure_target_error(
                target, addr + 0x100, RESP_SLVERR, read=False, write=True
            )
            await self.write_target_single_expect_status(
                target,
                addr + 0x100,
                data ^ 0x5A5A,
                expected,
                context=f"back_to_back_reset.{target}.prime",
            )
            phase = B2B_CLEAR_PHASES[(idx + (self.scenario_seed or 0)) % len(B2B_CLEAR_PHASES)]
            await self._reset_in_clear_phase(
                target, phase, rng.randint(1, 3), context=f"back_to_back_reset.{target}"
            )
            await self._clear_cdc_clear_seen()
            await self.pulse_system_reset(cycles=rng.randint(1, 2))
            await self.pulse_system_reset(cycles=rng.randint(1, 3))
            # The CDC's TCK-side isolate-and-clear runs only while TCK runs.
            for _ in range(ABORT_CDC_CLEAR_TCK):
                await self.tms_step(0)
            self._record_abort_check(
                target,
                CDC_CLEAR_CHECK_ID,
                f"back_to_back_reset.{target}.cdc_clear",
                observed=tb_if.cdc_clear_seen(target),
                expected=1,
                context="tck-side isolate-and-clear after two resets",
            )
            self._record_idle_bridge(target, f"back_to_back_reset.{target}.fsm_idle")
            status, _, captures = await self._poll_status_bounded(target, ABORT_RECOVERY_POLLS)
            self._record_abort_check(
                target,
                ABORT_RECOVERY_CHECK_ID,
                f"back_to_back_reset.{target}.status_kept",
                observed=status,
                expected=DtpJtag2AxiStatus.SLVERR,
                context=f"status={DtpJtag2AxiStatus(status).name} "
                f"captures={captures}/{ABORT_RECOVERY_POLLS} after two idle resets",
            )
            await self.verify_target_recovery(
                target,
                addr=addr,
                data=data,
                read=False,
                context=f"back_to_back_reset.{target}",
            )
            self.status = await self.verify_target_recovery(
                target,
                addr=addr,
                data=data,
                read=True,
                context=f"back_to_back_reset_read.{target}",
            )
            self.operation_count += 1
        seen = await self._tap_reset_in_receiver_wait(rng)
        await self._judge_receiver_leg(rng, leg="tck_wda", seen=seen, slot=B2B_RECOVERY_SLOT)
        seen = await self._system_reset_in_receiver_wait(rng)
        await self._judge_receiver_leg(
            rng, leg="aclk_wda", seen=seen, slot=B2B_RECOVERY_SLOT + len(ROBUST_TARGETS)
        )

    def _record_idle_bridge(self, target: str, name: str) -> None:
        """CHK-J2A-ABORT-FSM on a bridge that has nothing in flight: its state machine
        idle with no operation pending."""
        tb_if = self.cfg.tb_if
        idle = tb_if.bridge_fsm_idle(target)
        pending = tb_if.bridge_op_pending(target)
        self._record_abort_check(
            target,
            ABORT_FSM_CHECK_ID,
            name,
            observed=int(idle == 1 and pending == 0),
            expected=1,
            context=f"idle={idle} pending={pending} after the reset",
        )

    async def _trst_fall(self) -> None:
        """Wait for TRST to fall, unless it already has."""
        trst = self.cfg.tb_if.handle("jtag_trst")
        if int(trst.value):
            await FallingEdge(trst)

    async def _reset_after(
        self,
        landing: _PhaseLanding,
        trigger,
        *,
        flag: str,
        edges: int,
        cycles: int,
        context: str,
    ) -> None:
        """Pulse the system reset for ``cycles`` system clocks from the falling system
        clock edge ``edges`` rising edges after ``trigger`` completes, sampling the
        ``dtp_tb_if`` phase observable ``flag`` at the deposit. The deposit lands half a
        cycle inside a state at least one cycle wide that begins on the rising edge."""
        tb_if = self.cfg.tb_if
        await trigger
        landing.fired = True
        if edges:
            await ClockCycles(tb_if.clk, edges)
        await FallingEdge(tb_if.clk)
        landing.seen = tb_if.sample(flag)
        await self.pulse_system_reset(cycles=cycles, context=context)
        landing.landed = True

    async def _reset_in_clear_phase(
        self, target: str, phase: str, cycles: int, *, context: str
    ) -> None:
        """Pulse the system reset while the ACLK-side clear sequence, restarted by a pulse
        with TCK idle, is in ``phase``, then step TCK until the restarted sequence
        completes. The watcher deposits the pulse once the phase is observed; the TCK
        stepper stops after the step in which it landed, so no JTAG item is cut short."""
        tb_if = self.cfg.tb_if
        flag = f"j2a_cdc_aclk_{phase}"
        self.log.info("%s: system reset in the %s phase, %d cycles wide", context, phase, cycles)
        await self._clear_cdc_clear_seen()
        await self.pulse_system_reset(cycles=1)
        landing = _PhaseLanding()
        watcher = cocotb.start_soon(
            self._reset_after(
                landing,
                RisingEdge(tb_if.handle(flag)),
                flag=flag,
                edges=0,
                cycles=cycles,
                context=f"{context} in {phase}",
            )
        )
        for _ in range(B2B_PHASE_TCK):
            if landing.landed:
                break
            await self.tms_step(0)
        if landing.fired:
            await watcher
        else:
            watcher.cancel()
        self._record_abort_check(
            target,
            CDC_PHASE_CHECK_ID,
            f"{context}.phase.{phase}",
            observed=landing.seen,
            expected=1,
            context=f"system reset deposited in {phase}, landed={int(landing.landed)}",
        )
        for _ in range(B2B_PHASE_TCK):
            await self.tms_step(0)

    async def _tap_reset_in_receiver_wait(self, rng: random.Random) -> int:
        """TRST in the one TCK cycle the TCK-side four-phase receivers wait for their
        isolate acknowledge after a system reset with TCK idle; returns the receiver
        observable sampled at the TRST deposit."""
        hold = rng.randint(*ORPHAN_TRST_HOLD_TCK)
        self.log.info(
            "TRST %d TCK cycles after a system reset with TCK idle, held %d TCK cycles",
            B2B_RECEIVER_WAIT_EDGES,
            hold,
        )
        await self._clear_cdc_clear_seen()
        await self.pulse_system_reset(cycles=1)
        for _ in range(B2B_RECEIVER_WAIT_EDGES):
            await self.tms_step(0)
        seen = self.cfg.tb_if.sample("j2a_cdc_tck_dst_wait_ack")
        await self._enter_tap_reset(via_trst=True, hold=hold)
        await self._leave_tap_reset(via_trst=True, clear_tck=B2B_PHASE_TCK)
        return seen

    async def _system_reset_in_receiver_wait(self, rng: random.Random) -> int:
        """System reset in the one system clock cycle the ACLK-side four-phase receivers
        wait for their isolate acknowledge after TRST; returns the receiver observable
        sampled at the deposit. TRST is deposited half a system cycle from any system
        clock edge, so the receivers' synchronizers take it on the next edge."""
        tb_if = self.cfg.tb_if
        cycles = rng.randint(1, 3)
        hold = rng.randint(*ORPHAN_TRST_HOLD_TCK)
        self.log.info(
            "system reset %d system clock edges after TRST, %d cycles wide, TRST held %d TCK",
            B2B_RECEIVER_WAIT_EDGES,
            cycles,
            hold,
        )
        await self._clear_cdc_clear_seen()
        await FallingEdge(tb_if.clk)
        landing = _PhaseLanding()
        watcher = cocotb.start_soon(
            self._reset_after(
                landing,
                self._trst_fall(),
                flag="j2a_cdc_aclk_dst_wait_ack",
                edges=B2B_RECEIVER_WAIT_EDGES,
                cycles=cycles,
                context="back_to_back_reset.aclk_wda",
            )
        )
        await self._enter_tap_reset(via_trst=True, hold=hold)
        await watcher
        await self._leave_tap_reset(via_trst=True, clear_tck=B2B_PHASE_TCK)
        return landing.seen

    async def _judge_receiver_leg(
        self, rng: random.Random, *, leg: str, seen: int, slot: int
    ) -> None:
        """Every bridge's evidence after a reset placed in its receivers' waiting cycle:
        the receiver observable at the deposit, the TCK-side clear, the idle state
        machine, the SINGLE_OP status at its reset value, and a recovery write and read
        at slot ``slot`` onwards."""
        tb_if = self.cfg.tb_if
        for idx, target in enumerate(ROBUST_TARGETS):
            context = f"back_to_back_reset.{leg}.{target}"
            self._record_abort_check(
                target,
                CDC_PHASE_CHECK_ID,
                f"{context}.phase",
                observed=seen,
                expected=1,
                context="receiver waiting for its isolate acknowledge at the reset",
            )
            self._record_abort_check(
                target,
                CDC_CLEAR_CHECK_ID,
                f"{context}.cdc_clear",
                observed=tb_if.cdc_clear_seen(target),
                expected=1,
                context="tck-side isolate-and-clear after the reset",
            )
            self._record_idle_bridge(target, f"{context}.fsm_idle")
            status, _, captures = await self._poll_status_bounded(target, ABORT_RECOVERY_POLLS)
            self.scoreboard_expect_completion(
                target, status, context=f"{context}.status", polls=ABORT_RECOVERY_POLLS
            )
            self._record_abort_check(
                target,
                ABORT_RECOVERY_CHECK_ID,
                f"{context}.status",
                observed=status,
                expected=DtpJtag2AxiStatus.SUCCESS,
                context=f"status={DtpJtag2AxiStatus(status).name} "
                f"captures={captures}/{ABORT_RECOVERY_POLLS} on an idle bridge",
            )
            addr = self._target_addr(target, slot + idx)
            data = self.random_distinct_word(rng, target)
            await self.verify_target_recovery(
                target, addr=addr, data=data, read=False, context=context
            )
            self.status = await self.verify_target_recovery(
                target, addr=addr, data=data, read=True, context=f"{context}_read"
            )
            self.operation_count += 1

    def _record_orphan_check(
        self,
        target: str,
        check_id: str,
        name: str,
        *,
        observed: int,
        expected: int,
        context: str = "",
    ) -> bool:
        """Record one CHK-J2A-ORPHAN-* judgement of ``target``.

        ``DTP_J2A_ORPHAN_NEGATIVE=1`` flips bit 0 of ``expected``, so the run must fail.
        """
        if OcahKnobs.is_set(ORPHAN_NEGATIVE_KNOB):
            expected = int(expected) ^ 0x1
        return self._record_abort_check(
            target, check_id, name, observed=observed, expected=expected, context=context
        )

    async def _clear_cdc_clear_seen(self) -> None:
        """Pulse ``cdc_clear_seen_clear`` for one system cycle: every bridge's flag drops."""
        tb_if = self.cfg.tb_if
        tb_if.set_cdc_clear_seen_clear(1)
        await self.wait_sys_cycles(1)
        tb_if.set_cdc_clear_seen_clear(0)

    async def _hold_on_fabric(self, leg: _OrphanLeg, *, addr: int, word: int) -> bool:
        """Issue a SINGLE_OP whose request the responder holds on the fabric.

        A read holds its AR and is answered with the leg's error and the
        errored-beat word ``word``; a write holds its AW and W and is answered
        OKAY, so it lands ``word``. The request completes on the bus once the
        stall is released, so its intents are armed. Records
        CHK-J2A-ABORT-MIDFLIGHT once the state machine waits on it and the held
        channel's stall counter has advanced.
        """
        tb_if = self.cfg.tb_if
        target = leg.target
        size = self.target_cfg(target).default_size
        channels = ("ar",) if leg.read else ("aw", "w")
        self.configure_target_backpressure(
            target, channels=channels, stall_cycles=ABORT_HOLD_CYCLES
        )
        stalls = await self.target_stall_counts(target)
        if leg.read:
            self.configure_target_error(
                target, addr, leg.resp, read=True, write=False, err_rdata=word
            )
            self.log_target_jtag2axi_op(target, f"{leg.context}.held", addr=addr, size=size)
            await self.write_target_single_raw(target, DtpJtag2AxiOp.READ, addr, size=size)
        else:
            wstrb = self.target_full_wstrb(target, size)
            self.log_target_jtag2axi_op(
                target, f"{leg.context}.held", addr=addr, data=word, size=size, wstrb=wstrb
            )
            await self.write_target_single_raw(
                target, DtpJtag2AxiOp.WRITE, addr, data=word, wstrb=wstrb, size=size
            )
        idle = await self._wait_bridge_fsm(target, idle=False, tck_cycles=ABORT_MIDFLIGHT_TCK)
        on_bus = await self._wait_held_on_bus(
            target, leg.held, stalls[leg.held], ABORT_MIDFLIGHT_TCK
        )
        mid_flight = not idle and tb_if.bridge_op_pending(target) == 1 and on_bus
        return self._record_abort_check(
            target,
            ABORT_MIDFLIGHT_CHECK_ID,
            f"{leg.context}.mid_flight",
            observed=int(mid_flight),
            expected=1,
            context=f"idle={idle} {leg.held}_held={int(on_bus)}",
        )

    async def _enter_tap_reset(self, *, via_trst: bool, hold: int) -> None:
        """Reset the bridges' TCK side: TRST asserted over ``hold`` TCK cycles and left
        asserted, or a TMS walk into Test-Logic-Reset."""
        if via_trst:
            await self.assert_trst(cycles=hold)
            return
        for _ in range(ORPHAN_TLR_WALK):
            await self.tms_step(1)

    async def _leave_tap_reset(self, *, via_trst: bool, clear_tck: int) -> None:
        """Release TRST, leave Test-Logic-Reset, and step ``clear_tck`` TCK cycles in
        Run-Test/Idle, during which the CDC runs its TCK-side isolate-and-clear."""
        if via_trst:
            await self.deassert_trst(cycles=1)
        for _ in range(clear_tck + 1):
            await self.tms_step(0)

    async def _release_after(self, target: str, cycles: int) -> None:
        if cycles:
            await self.wait_sys_cycles(cycles)
        self.clear_target_backpressure(target)

    async def _aligned_tap_reset(self, target: str, *, offset: int, hold: int) -> None:
        """Assert TRST and release the stall ``offset`` system cycles after it, or
        before it when ``offset`` is negative; both land on system clock edges."""
        await self.wait_sys_cycles(1)
        if offset < 0:
            self.clear_target_backpressure(target)
            await self.wait_sys_cycles(-offset)
            await self.assert_trst(cycles=hold)
            return
        release = cocotb.start_soon(self._release_after(target, offset))
        await self.assert_trst(cycles=hold)
        await release

    async def _judge_clear_finished(self, leg: _OrphanLeg) -> bool:
        """CHK-J2A-ORPHAN-DRAIN: the clear has finished while the request is still held.

        The sticky clear-seen flag stays clear over the probe window and the
        held channel's stall counter keeps advancing.
        """
        target = leg.target
        await self._clear_cdc_clear_seen()
        stalls = await self.target_stall_counts(target)
        await self.wait_sys_cycles(ORPHAN_CLEAR_PROBE_CYCLES)
        pending = self.cfg.tb_if.cdc_clear_seen(target)
        still_held = (await self.target_stall_counts(target))[leg.held] > stalls[leg.held]
        return self._record_orphan_check(
            target,
            ORPHAN_DRAIN_CHECK_ID,
            f"{leg.context}.clear_finished",
            observed=int(not pending and still_held),
            expected=1,
            context=f"clear_pending={pending} {leg.held}_held={int(still_held)}",
        )

    async def _drain_tap_reset(self, leg: _OrphanLeg, *, completed: int) -> bool:
        """Reset the TAP with the request held and leave Test-Logic-Reset again.

        Inside the clear the stall is released while the TAP holds
        Test-Logic-Reset (CHK-J2A-ORPHAN-DRAIN for the landing there), and at
        the aligned drain point together with TRST. CHK-J2A-CDC-CLEAR records
        the TCK-side clear; ahead of a release after the clear,
        CHK-J2A-ORPHAN-DRAIN records the finished clear with the request still
        held.
        """
        tb_if = self.cfg.tb_if
        target = leg.target
        await self._clear_cdc_clear_seen()
        if leg.drain is _OrphanDrain.ALIGNED:
            await self._aligned_tap_reset(target, offset=leg.offset, hold=leg.trst_hold)
        else:
            await self._enter_tap_reset(via_trst=leg.via_trst, hold=leg.trst_hold)
        ok = True
        if leg.drain is _OrphanDrain.IN_CLEAR:
            await self.wait_sys_cycles(leg.in_clear_wait)
            self.clear_target_backpressure(target)
            landed = await self.wait_port_completion(target, read=leg.read, above=completed)
            tap = tb_if.sample("jtag_ptap_state")
            ok = self._record_orphan_check(
                target,
                ORPHAN_DRAIN_CHECK_ID,
                f"{leg.context}.drained_in_reset",
                observed=int(landed and tap == OcahJtagState.TEST_LOGIC_RESET),
                expected=1,
                context=f"landed={int(landed)} tap_state=0x{tap:04x}",
            )
        await self._leave_tap_reset(via_trst=leg.via_trst, clear_tck=leg.clear_tck)
        ok &= self._record_abort_check(
            target,
            CDC_CLEAR_CHECK_ID,
            f"{leg.context}.cdc_clear",
            observed=tb_if.cdc_clear_seen(target),
            expected=1,
            context="tck-side isolate-and-clear after the TAP reset",
        )
        if leg.drain in (_OrphanDrain.AFTER_CLEAR, _OrphanDrain.QUEUED):
            ok &= await self._judge_clear_finished(leg)
        return ok

    def _queued_addr(self, target: str, rng: random.Random, slot: int) -> int:
        """A seeded beat of slot ``slot``'s 0x400 window, with seeded address bits
        above the responder window."""
        beat_bytes = self.target_cfg(target).beat_bytes
        beat = rng.randrange(0x400 // beat_bytes) * beat_bytes
        return (ROBUST_BASE + slot * 0x400 + beat) | self.random_upper_addr(target, rng)

    async def _queue_behind(
        self, leg: _OrphanLeg, *, addr: int, word: int
    ) -> tuple[DtpJtag2AxiStatus, bool]:
        """Issue a SINGLE_OP of the new session behind the held request.

        A read of a slot holding ``word`` is answered OKAY, and a write of
        ``word`` with the leg's error, so neither response matches the held
        request's. Returns the status the queued request reports, and whether
        CHK-J2A-ORPHAN-ORDER saw the bridge waiting on it while the held
        request still stalls.
        """
        tb_if = self.cfg.tb_if
        target = leg.target
        size = self.target_cfg(target).default_size
        stalls = await self.target_stall_counts(target)
        if leg.read:
            expected = DtpJtag2AxiStatus.SUCCESS
            self.write_target_mem_int(target, addr, word, size)
            self.log_target_jtag2axi_op(target, f"{leg.context}.queued", addr=addr, size=size)
            await self.write_target_single_raw(target, DtpJtag2AxiOp.READ, addr, size=size)
        else:
            expected = self.configure_target_error(target, addr, leg.resp, read=False, write=True)
            wstrb = self.target_full_wstrb(target, size)
            self.log_target_jtag2axi_op(
                target, f"{leg.context}.queued", addr=addr, data=word, size=size, wstrb=wstrb
            )
            await self.write_target_single_raw(
                target, DtpJtag2AxiOp.WRITE, addr, data=word, wstrb=wstrb, size=size
            )
        idle = await self._wait_bridge_fsm(target, idle=False, tck_cycles=ABORT_MIDFLIGHT_TCK)
        for _ in range(ORPHAN_QUEUE_TCK):
            await self.tms_step(0)
        await self.wait_sys_cycles(ORPHAN_QUEUE_CYCLES)
        still_held = (await self.target_stall_counts(target))[leg.held] > stalls[leg.held]
        queued = not idle and tb_if.bridge_op_pending(target) == 1 and still_held
        ok = self._record_orphan_check(
            target,
            ORPHAN_ORDER_CHECK_ID,
            f"{leg.context}.queued",
            observed=int(queued),
            expected=1,
            context=f"idle={idle} {leg.held}_held={int(still_held)}",
        )
        return expected, ok

    async def _judge_drain(
        self,
        leg: _OrphanLeg,
        *,
        held: tuple[int, int],
        last: tuple[int, int, DtpJtag2AxiStatus],
        completed: int,
    ) -> bool:
        """Judge the port and SINGLE_OP once the held request, and a queued one, drained.

        ``held`` is the held request's (address, word) and ``last`` the newest
        request's (address, word, status). CHK-J2A-ORPHAN-DRAIN: one completion
        of the direction, two with a queued request, and a held write's word
        in its slot. Without a queued request, the newest completion is the
        held one (CHK-J2A-ORPHAN-DRAIN) and SINGLE_OP reads the TAP reset's
        SUCCESS (CHK-J2A-ORPHAN-DISCARD). With one, CHK-J2A-ORPHAN-ORDER: the
        newest completion is the queued request's, SINGLE_OP reads its status,
        and a queued read's data field holds its slot's word.
        """
        tb_if = self.cfg.tb_if
        target, read = leg.target, leg.read
        queued = leg.drain is _OrphanDrain.QUEUED
        size = self.target_cfg(target).default_size
        history = self.port_history(target)
        held_addr, held_word = held
        last_addr, last_word, last_status = last
        await self.wait_port_completion(target, read=read, above=completed + leg.landings - 1)
        for _ in range(ABORT_SETTLE_TCK):
            if not tb_if.bridge_op_pending(target):
                break
            await self.tms_step(0)
        status, rdata, captures = await self._poll_status_bounded(target, ABORT_RECOVERY_POLLS)
        self.scoreboard_expect_completion(
            target, status, context=f"{leg.context}.drained", polls=ABORT_RECOVERY_POLLS
        )
        newest = history.last(read=read)
        ok = self._record_orphan_check(
            target,
            ORPHAN_DRAIN_CHECK_ID,
            f"{leg.context}.landings",
            observed=history.count(read=read) - completed,
            expected=leg.landings,
            context="port completions of the direction after the release",
        )
        ok &= self._record_orphan_check(
            target,
            ORPHAN_ORDER_CHECK_ID if queued else ORPHAN_DRAIN_CHECK_ID,
            f"{leg.context}.last_address",
            observed=newest.address if newest is not None else 0,
            expected=self.masked_addr(target, last_addr),
            context="address of the newest completion of the direction",
        )
        if not read:
            nbytes = self.size_bytes(size)
            self.scoreboard_check_target_memory(
                target,
                held_addr,
                nbytes,
                context=f"{leg.context}.held_slot",
                expected=held_word.to_bytes(nbytes, "little"),
            )
            ok &= self._record_orphan_check(
                target,
                ORPHAN_DRAIN_CHECK_ID,
                f"{leg.context}.held_slot",
                observed=self.read_target_mem_int(target, held_addr, size),
                expected=held_word,
                context=f"addr=0x{held_addr:x}",
            )
        ok &= self._record_orphan_check(
            target,
            ORPHAN_ORDER_CHECK_ID if queued else ORPHAN_DISCARD_CHECK_ID,
            f"{leg.context}.{'queued_status' if queued else 'status_after_drain'}",
            observed=status,
            expected=last_status,
            context=(
                f"status={DtpJtag2AxiStatus(status).name} "
                f"captures={captures}/{ABORT_RECOVERY_POLLS}"
            ),
        )
        if queued and read:
            ok &= self._record_orphan_check(
                target,
                ORPHAN_ORDER_CHECK_ID,
                f"{leg.context}.queued_rdata",
                observed=rdata & self.target_data_mask(target),
                expected=last_word,
                context=f"addr=0x{last_addr:x}",
            )
        return ok

    async def _orphan_follow_on(
        self, leg: _OrphanLeg, rng: random.Random, *, avoid: tuple[int, ...], completed: int
    ) -> bool:
        """The next operation in the held request's direction reports its own response.

        The responder answers it with the error code the leg's earlier
        requests did not get, and a read with a seeded errored-beat word, so no
        earlier response of the direction can pass for it
        (CHK-J2A-ORPHAN-DISCARD); the port completes it as the only further
        transaction of that direction (CHK-J2A-ORPHAN-DRAIN).
        """
        target, read = leg.target, leg.read
        size = self.target_cfg(target).default_size
        addr = self._target_addr(target, leg.slot + 2)
        resp = RESP_DECERR if leg.resp == RESP_SLVERR else RESP_SLVERR
        errored = self.random_distinct_word(rng, target, *avoid)
        if read:
            preload = self.random_distinct_word(rng, target, *avoid, errored)
            self.write_target_mem_int(target, addr, preload, size)
            expected = self.configure_target_error(
                target, addr, resp, read=True, write=False, err_rdata=errored
            )
            self.log_target_jtag2axi_op(target, f"{leg.context}.follow_on", addr=addr, size=size)
            await self.write_target_single_raw(target, DtpJtag2AxiOp.READ, addr, size=size)
        else:
            expected = self.configure_target_error(target, addr, resp, read=False, write=True)
            wstrb = self.target_full_wstrb(target, size)
            self.log_target_jtag2axi_op(
                target, f"{leg.context}.follow_on", addr=addr, data=errored, size=size, wstrb=wstrb
            )
            await self.write_target_single_raw(
                target, DtpJtag2AxiOp.WRITE, addr, data=errored, wstrb=wstrb, size=size
            )
        status, rdata, captures = await self._poll_status_bounded(target, ABORT_RECOVERY_POLLS)
        self.scoreboard_expect_completion(
            target, status, context=f"{leg.context}.follow_on", polls=ABORT_RECOVERY_POLLS
        )
        ok = self._record_orphan_check(
            target,
            ORPHAN_DISCARD_CHECK_ID,
            f"{leg.context}.follow_on_status",
            observed=status,
            expected=expected,
            context=(
                f"status={DtpJtag2AxiStatus(status).name} "
                f"captures={captures}/{ABORT_RECOVERY_POLLS}"
            ),
        )
        if read:
            ok &= self._record_orphan_check(
                target,
                ORPHAN_DISCARD_CHECK_ID,
                f"{leg.context}.follow_on_rdata",
                observed=rdata & self.target_data_mask(target),
                expected=errored,
                context="errored-beat word of the follow-on read",
            )
        await self.wait_port_completion(target, read=read, above=completed)
        ok &= self._record_orphan_check(
            target,
            ORPHAN_DRAIN_CHECK_ID,
            f"{leg.context}.single_landing",
            observed=self.port_history(target).count(read=read),
            expected=completed + 1,
            context="port completions of the direction after the follow-on operation",
        )
        return ok

    async def _tap_reset_orphan(self, leg: _OrphanLeg, rng: random.Random) -> bool:
        """TCK-side clear while a SINGLE_OP is held on the fabric, drained as ``leg`` selects.

        The held request completes on the bus exactly once and the bridge
        consumes its response, so SINGLE_OP reads the TAP reset's SUCCESS, or
        the queued request's own status, and the next operation reports its own
        response. Returns True when every judgement of the leg matched.
        """
        target = leg.target
        addr = self._target_addr(target, leg.slot)
        word = self.random_distinct_word(rng, target)
        completed = self.port_history(target).count(read=leg.read)
        self.log.info(
            "%s clear=%s trst_hold=%d clear_tck=%d in_clear_wait=%d release_offset=%d error=%s",
            leg.context,
            "trst" if leg.via_trst else "tms_walk",
            leg.trst_hold,
            leg.clear_tck,
            leg.in_clear_wait,
            leg.offset,
            self.axi_resp_to_jtag_status(leg.resp).name,
        )
        ok = await self._hold_on_fabric(leg, addr=addr, word=word)
        ok &= await self._drain_tap_reset(leg, completed=completed)
        last = (addr, word, DtpJtag2AxiStatus.SUCCESS)
        if leg.drain is _OrphanDrain.QUEUED:
            queued_addr = self._queued_addr(target, rng, leg.slot + 1)
            queued_word = self.random_distinct_word(rng, target, word)
            status, queued = await self._queue_behind(leg, addr=queued_addr, word=queued_word)
            last = (queued_addr, queued_word, status)
            ok &= queued
        if leg.drain in (_OrphanDrain.AFTER_CLEAR, _OrphanDrain.QUEUED):
            self.clear_target_backpressure(target)
        ok &= await self._judge_drain(leg, held=(addr, word), last=last, completed=completed)
        ok &= await self._orphan_follow_on(
            leg, rng, avoid=(word, last[1]), completed=completed + leg.landings
        )
        self.operation_count += 1
        return ok

    async def _run_tap_reset_orphans(self) -> None:
        """TCK-side clear with a SINGLE_OP held on the fabric: every drain point on
        every bridge and direction, then a recovery write and read per bridge."""
        self.log_banner("JTAG2AXI TCK-side clear while a request is held on the fabric")
        await self.reset_tap()
        rng = self.rng("cdc_clear_abort_tap_reset")
        if OcahKnobs.is_set(ORPHAN_NEGATIVE_KNOB):
            self.log.warning(
                "NEGATIVE VALIDATION: every CHK-J2A-ORPHAN-* expectation is corrupted (%s)",
                ORPHAN_NEGATIVE_KNOB,
            )
        base = (self.scenario_seed or 0) % ORPHAN_ALIGN_SPAN
        pairs = [(target, read) for target in ROBUST_TARGETS for read in (False, True)]
        drains = list(_OrphanDrain)
        stuck = []
        for pair, (target, read) in enumerate(pairs):
            direction = "read" if read else "write"
            # Seeded drain order per bridge and direction; every drain runs on every pair.
            rng.shuffle(drains)
            for idx, drain in enumerate(drains):
                self.log_iteration(
                    pair * len(drains) + idx + 1,
                    len(pairs) * len(drains),
                    "target=%s %s held on the fabric, drain=%s",
                    target,
                    direction,
                    drain.value,
                )
                leg = _OrphanLeg(
                    target=target,
                    read=read,
                    drain=drain,
                    slot=1 + ORPHAN_SLOT_STRIDE * (len(drains) * int(read) + idx),
                    via_trst=drain is _OrphanDrain.ALIGNED or bool(rng.getrandbits(1)),
                    trst_hold=rng.randint(*ORPHAN_TRST_HOLD_TCK),
                    clear_tck=rng.randint(*ORPHAN_CLEAR_TCK),
                    in_clear_wait=rng.randint(*ORPHAN_IN_CLEAR_CYCLES),
                    offset=ORPHAN_ALIGN_MIN + (base + pair) % ORPHAN_ALIGN_SPAN,
                    resp=rng.choice((RESP_SLVERR, RESP_DECERR)),
                    context=f"tap_reset.{target}.{direction}.{drain.value}",
                )
                if not await self._tap_reset_orphan(leg, rng):
                    stuck.append(f"{target}.{direction}.{drain.value}")
        for target in ROBUST_TARGETS:
            for read in (False, True):
                self.status = await self.verify_target_recovery(
                    target,
                    addr=self._target_addr(
                        target, ORPHAN_SLOT_STRIDE * 2 * len(drains) + 1 + int(read)
                    ),
                    data=self.random_distinct_word(rng, target),
                    read=read,
                    context=f"tap_reset.{target}",
                )
        if stuck:
            raise AssertionError(
                f"tap_reset: {', '.join(stuck)} failed a judgement of the TCK-side clear"
            )

    async def run_decode_error_decerr_write(self) -> None:
        self.log_banner("JTAG2AXI DECERR write decode path")
        await self.reset_tap()
        rng = self.rng("decerr_write_data")
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            addr = self._target_addr(target, idx + 24)
            size = self.target_cfg(target).default_size
            expected = self.configure_target_error(
                target, addr, RESP_DECERR, read=False, write=True
            )
            before = self.read_target_mem_int(target, addr, size)
            await self.write_target_single_expect_status(
                target,
                addr,
                rng.getrandbits(32) ^ idx,
                expected,
                context=f"decerr_write.{target}",
            )
            # The responder drops an armed write beat, so the error slot keeps
            # its prior value.
            self.check_target_word(
                target,
                addr,
                before,
                size=size,
                context=f"decerr_write.{target}.no_write_side_effect",
            )
            self.status = await self.verify_target_recovery(
                target,
                addr=addr + 0x200,
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
            preload = rng.randrange(1, 1 << cfg.data_width)
            # The errored beat's word differs from zero and from the preload,
            # so neither a zeroed capture nor the slot's word can pass for it.
            errored = self.random_distinct_word(rng, target, preload)
            self.write_target_mem_int(target, addr, preload, cfg.default_size)
            expected = self.configure_target_error(
                target, addr, RESP_DECERR, read=True, write=False, err_rdata=errored
            )
            _, rdata = await self.read_target_single_expect_status(
                target,
                addr,
                expected,
                context=f"decerr_read.{target}",
            )
            self.check_error_rdata(
                target,
                addr,
                rdata,
                resp=RESP_DECERR,
                preload=preload,
                errored=errored,
                size=cfg.default_size,
                context=f"decerr_read.{target}",
            )
            self.status = await self.verify_target_recovery(
                target,
                addr=addr + 0x200,
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
                target, bad_addr, RESP_DECERR, read=True, write=True
            )
            await self.read_target_single_expect_status(
                target,
                bad_addr,
                expected,
                context=f"mixed.bad_read.{target}",
            )
            await self.write_target_single_expect_status(
                target,
                bad_addr,
                rng.getrandbits(self.target_cfg(target).data_width),
                expected,
                context=f"mixed.bad_write.{target}",
            )
            status, _ = await self.read_target_single_and_check(
                target,
                good_addr,
                good_data,
                context=f"mixed.good_read.{target}",
            )
            self.status = DtpJtag2AxiStatus(status)
            self.operation_count += 1
        self._emit_decode_error_nonvacuity("mixed")

    @staticmethod
    def _series_corner_base(target_idx: int, leg: int) -> int:
        """Aligned base of one series leg's window."""
        return SERIES_CORNER_BASE + target_idx * 0x400 + leg * 0x100

    def _record_series_status(
        self, target: str, observed: int, expected: DtpJtag2AxiStatus, *, context: str
    ) -> None:
        """CHK-J2A-FAULT-STATUS on a SERIES_CTRL capture."""
        self.check_bridge_status(target, observed, expected, context=context)

    async def _series_corner_beat(
        self, target: str, addr: int, data: int, *, size: int, increment: int, context: str
    ) -> None:
        """Land one write beat of a programmed series and compare the word it wrote."""
        completed = self.port_history(target).count(read=False)
        before = await self.target_activity_counts(target)
        if increment:
            await self.series_data_incr(data, size=size, target=target, back_to_rti=True)
        else:
            await self.series_data_no_incr(data, size=size, target=target, back_to_rti=True)
        await self.wait_for_target_activity(target, before=before, read=False, context=context)
        await self.require_port_completion(
            target, read=False, above=completed, context=f"{context}.commit"
        )
        self.check_target_word(target, addr, data, size=size, context=f"{context}.mem")
        self.operation_count += 1

    async def _series_corner_progressions(
        self, target: str, target_idx: int, beats: int, rng: random.Random
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
        self, target: str, target_idx: int, beats: int, rng: random.Random
    ) -> None:
        """One faulted beat sets the series status, which holds across the clean beats
        after it until SERIES_CTRL.reset starts a fresh series."""
        cfg = self.target_cfg(target)
        size = cfg.default_size
        base = self._series_corner_base(target_idx, 2)
        # At least one clean beat follows the fault, so the held status is observed
        # after a beat the responder accepted.
        fault_beat = rng.randrange(0, beats - 1)
        resp = rng.choice((RESP_SLVERR, RESP_DECERR))
        fault_addr = base + fault_beat * cfg.beat_bytes
        expected = self.configure_target_error(target, fault_addr, resp, read=False, write=True)
        fault_before = self.read_target_mem_int(target, fault_addr, size)
        await self.jtag2axi_series_ctrl(DtpJtag2AxiOp.WRITE, base, size=size, target=target)
        for beat in range(beats):
            addr = base + beat * cfg.beat_bytes
            data = rng.getrandbits(cfg.data_width) & self.data_mask(size)
            context = f"series_corner.sticky.{target}.{beat}"
            completed = self.port_history(target).count(read=False)
            before = await self.target_activity_counts(target)
            await self.series_data_incr(data, size=size, target=target, back_to_rti=True)
            await self.wait_for_target_activity(target, before=before, read=False, context=context)
            await self.require_port_completion(
                target, read=False, above=completed, context=f"{context}.commit"
            )
            if beat == fault_beat:
                self.check_target_word(
                    target, addr, fault_before, size=size, context=f"{context}.mem_dropped"
                )
                # The capture right after the faulted beat carries the code.
                status = await self.check_series_addr(
                    target, addr + cfg.beat_bytes, size=size, context=f"{context}.faulted"
                )
                self._record_series_status(target, status, expected, context=f"{context}.faulted")
            else:
                self.check_target_word(target, addr, data, size=size, context=f"{context}.mem")
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

    async def _series_corner_interleaved(self, beats: int, rng: random.Random) -> None:
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
                self.check_target_word(
                    target,
                    bases[target] + beat * cfg.beat_bytes,
                    words[target][beat],
                    size=size,
                    context=f"series_corner.interleaved.{target}.final#{beat}",
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
        await self._run_cdc_fifo_entry_sweep()

    def _cdc_fifo_slots(self, target: str) -> int:
        """Entries in each CDC FIFO of the bridge behind ``target``.

        The bridge sizes the five FIFOs of its clock crossing to the power of
        two at or above its read pipeline depth plus two. A FIFO pushes into
        its entries in turn from its last clear, so push ``j`` lands in entry
        ``j % slots``, and a stored entry keeps its payload until the
        asynchronous reset of the FIFO's source side.
        """
        return 1 << (self.target_cfg(target).rd_pl_depth + 1).bit_length()

    @staticmethod
    def _sweep_error_plan(
        rng: random.Random, slots: int, pushes: int, *, errored_last: bool
    ) -> list[int | None]:
        """The injected response of each of ``pushes`` accesses into a ``slots``-entry FIFO.

        Every entry takes one errored access on a seeded visit and OKAY on the
        others, so it stores an error code and OKAY in turn; SLVERR and DECERR
        alternate across entries from a seeded phase. With ``errored_last``
        the final access is its entry's errored one.
        """
        phase = rng.getrandbits(1)
        plan: list[int | None] = [None] * pushes
        for entry in range(slots):
            visit = rng.choice(range(entry, pushes, slots))
            if errored_last and entry == (pushes - 1) % slots:
                visit = pushes - 1
            plan[visit] = RESP_SLVERR if (entry + phase) % 2 == 0 else RESP_DECERR
        return plan

    def _sweep_beat(self, target: str, rng: random.Random) -> int:
        """A seeded beat address: bits above the responder window and a beat inside it."""
        return self.random_upper_addr(target, rng) | self.random_target_aligned_addr(target, rng)

    def _sweep_addr(self, target: str, rng: random.Random) -> tuple[int, int]:
        """A seeded address and transfer size for one OKAY access of the sweep.

        A seeded beat; on an AXI4 port a seeded byte offset inside it with a
        seeded size the offset is aligned to, on an AXI-Lite port the beat
        address with a seeded size up to the beat.
        """
        cfg = self.target_cfg(target)
        beat = self._sweep_beat(target, rng)
        offset = rng.randrange(cfg.beat_bytes) if cfg.bus_type == 0 else 0
        sizes = [
            size for size in range(cfg.default_size + 1) if offset % self.size_bytes(size) == 0
        ]
        return beat + offset, rng.choice(sizes)

    async def _sweep_write(
        self, target: str, rng: random.Random, resp: int | None, *, context: str
    ) -> None:
        """One checked SINGLE_OP write of seeded data and strobes; with ``resp`` the
        responder answers the full-beat write with that code and drops it."""
        cfg = self.target_cfg(target)
        if resp is None:
            addr, size = self._sweep_addr(target, rng)
            await self.write_target_single_and_check(
                target,
                addr,
                rng.getrandbits(cfg.data_width),
                size=size,
                wstrb=rng.randint(1, self.target_full_wstrb(target, size)),
                context=context,
            )
        else:
            size = cfg.default_size
            addr = self._sweep_beat(target, rng)
            before = self.read_target_mem_int(target, addr, size)
            expected = self.configure_target_error(target, addr, resp, read=False, write=True)
            await self.write_target_single_expect_status(
                target, addr, rng.getrandbits(cfg.data_width), expected, context=context
            )
            self.check_target_word(
                target, addr, before, size=size, context=f"{context}.no_write_side_effect"
            )
        self.operation_count += 1

    async def _sweep_read(
        self, target: str, rng: random.Random, resp: int | None, *, context: str
    ) -> None:
        """One checked SINGLE_OP read of a seeded preloaded beat; with ``resp`` the
        responder answers the full-beat read with that code and a second seeded word
        (CHK-J2A-ERR-RDATA)."""
        cfg = self.target_cfg(target)
        size = cfg.default_size
        if resp is None:
            addr, read_size = self._sweep_addr(target, rng)
            lane = addr % cfg.beat_bytes
            word = rng.getrandbits(cfg.data_width)
            self.write_target_mem_int(target, addr - lane, word, size)
            await self.read_target_single_and_check(
                target, addr, word >> (8 * lane), size=read_size, context=context
            )
        else:
            addr = self._sweep_beat(target, rng)
            preload = self.random_distinct_word(rng, target)
            errored = self.random_distinct_word(rng, target, preload)
            self.write_target_mem_int(target, addr, preload, size)
            expected = self.configure_target_error(
                target, addr, resp, read=True, write=False, err_rdata=errored
            )
            _, rdata = await self.read_target_single_expect_status(
                target, addr, expected, context=context
            )
            self.check_error_rdata(
                target,
                addr,
                rdata,
                resp=resp,
                preload=preload,
                errored=errored,
                size=size,
                context=context,
            )
        self.operation_count += 1

    def _record_sweep_clear(self, label: str) -> None:
        """CHK-J2A-CDC-CLEAR and CHK-J2A-ABORT-FSM on every bridge after the ``label`` reset."""
        tb_if = self.cfg.tb_if
        for target in ROBUST_TARGETS:
            context = f"cdc_fifo_entry_sweep.{target}.{label}"
            self._record_abort_check(
                target,
                CDC_CLEAR_CHECK_ID,
                f"{context}.cdc_clear",
                observed=tb_if.cdc_clear_seen(target),
                expected=1,
                context=f"tck-side isolate-and-clear after the {label}",
            )
            self._record_abort_check(
                target,
                ABORT_FSM_CHECK_ID,
                f"{context}.fsm_idle",
                observed=tb_if.bridge_fsm_idle(target),
                expected=1,
                context=f"after the {label}",
            )

    async def _run_cdc_fifo_entry_sweep(self) -> None:
        """Load every CDC FIFO entry of every bridge in one TAP session, then reset the
        TAP and the system with the entries holding their payloads."""
        self.log_banner("JTAG2AXI CDC FIFO entry sweep, then TAP and system resets")
        await self.reset_tap()
        rng = self.rng("cdc_fifo_entry_sweep")
        self.log_step(
            4, "Fill every entry of each bridge's CDC FIFOs at least twice in one TAP session"
        )
        operations = 0
        operations_before = self.operation_count
        for idx, target in enumerate(ROBUST_TARGETS, start=1):
            slots = self._cdc_fifo_slots(target)
            # Two full rotations plus two pushes: every entry is written at
            # least twice, entries 0 and 1 three times.
            pushes = 2 * slots + 2
            write_plan = self._sweep_error_plan(rng, slots, pushes, errored_last=False)
            read_plan = self._sweep_error_plan(rng, slots, pushes, errored_last=True)
            self.log_iteration(
                idx,
                len(ROBUST_TARGETS),
                "target=%s slots=%d writes=%d reads=%d write_errors=%s read_errors=%s",
                target,
                slots,
                pushes,
                pushes,
                [push for push, resp in enumerate(write_plan) if resp is not None],
                [push for push, resp in enumerate(read_plan) if resp is not None],
            )
            for push in range(pushes):
                context = f"cdc_fifo_entry_sweep.{target}.{push}"
                await self._sweep_write(target, rng, write_plan[push], context=f"{context}.write")
                await self._sweep_read(target, rng, read_plan[push], context=f"{context}.read")
            operations += 2 * pushes + 2
        self.log_step(5, "TAP reset while every request entry holds its last payload")
        await self._clear_cdc_clear_seen()
        await self.reset_tap()
        for _ in range(ABORT_SETTLE_TCK):
            await self.tms_step(0)
        self._record_sweep_clear("tap_reset")
        self.log_step(6, "System reset while every response entry holds its last payload")
        await self._clear_cdc_clear_seen()
        await self.pulse_system_reset(cycles=rng.randint(1, 3))
        for _ in range(ABORT_SETTLE_TCK):
            await self.tms_step(0)
        self._record_sweep_clear("system_reset")
        self.log_step(7, "SINGLE_OP status at its reset value, then a write and a read per bridge")
        for target in ROBUST_TARGETS:
            cfg = self.target_cfg(target)
            context = f"cdc_fifo_entry_sweep.{target}"
            # The last read of the sweep left an error code, which the TAP
            # reset returns to the op field's reset value; the system reset
            # on the idle bridge discards nothing and keeps it.
            status, _, captures = await self._poll_status_bounded(target, ABORT_RECOVERY_POLLS)
            self.scoreboard_expect_completion(
                target, status, context=f"{context}.status_reset", polls=ABORT_RECOVERY_POLLS
            )
            self._record_abort_check(
                target,
                ABORT_RECOVERY_CHECK_ID,
                f"{context}.status_reset",
                observed=status,
                expected=DtpJtag2AxiStatus.SUCCESS,
                context=f"status={DtpJtag2AxiStatus(status).name} "
                f"captures={captures}/{ABORT_RECOVERY_POLLS} after the TAP and system resets",
            )
            for read in (False, True):
                self.status = await self.verify_target_recovery(
                    target,
                    addr=self._sweep_beat(target, rng),
                    data=rng.getrandbits(cfg.data_width),
                    read=read,
                    context=context,
                )
                self.operation_count += 1
        scoreboard = self.axi_scoreboard
        unconsumed = scoreboard.unconsumed_credits()
        swept = self.operation_count - operations_before
        scoreboard.expect_nonvacuous(
            swept >= operations and unconsumed == 0,
            context=(
                f"scenario={self.scenario} leg=cdc_fifo_entry_sweep "
                f"operations={swept}/{operations} "
                f"credits_unconsumed={unconsumed}"
            ),
        )

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
