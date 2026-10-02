# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI error and error-path security scenarios.

Every fault beat is judged: the SINGLE_OP or SERIES_CTRL status the bridge
reports is compared with the injected response, the read data with the
seeded word the errored beat carried, the with-status capture bit with the
previous beat's outcome, the SERIES_CTRL address with the per-beat
increment, and the responder memory with the committed or dropped
expectation. Outside security gating, every operation's port transaction,
the fault beat's included, is the one its request carried
(``CHK-J2A-BUS-REQ``). ``status`` is the scenario verdict.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from env.dtp_types import (
    FAULT_STATUS_CHECK_ID,
    DtpJtag2AxiOp,
    DtpJtag2AxiStatus,
    pack_single_op,
    unpack_series_data,
)

from .dtp_jtag2axi_base_test_seq import STATUS_BIT_CHECK_ID, dtp_jtag2axi_base_test_seq

AXI_SLVERR = 2
AXI_DECERR = 3
ERROR_RESPONSES = (AXI_SLVERR, AXI_DECERR)
ERROR_BASE = 0x1800
RECOVERY_BASE = 0x2800
SERIES_BEATS = 3
# The middle beat: a committed good beat precedes and follows the fault.
SERIES_FAULT_BEAT = 1


def _series_mode(*, increment: bool, with_status: bool) -> str:
    return ("incr" if increment else "no_incr") + ("_with_status" if with_status else "")


@dataclass(frozen=True)
class _SeriesFault:
    """One series error stream: its geometry and the beat that carries the fault."""

    increment: bool
    with_status: bool
    size: int
    stride: int
    base: int
    fault_idx: int
    expected: DtpJtag2AxiStatus
    resp: int

    def addr(self, idx: int) -> int:
        return self.base + idx * self.stride

    @property
    def fault_addr(self) -> int:
        return self.addr(self.fault_idx)

    def beat_resp_name(self, idx: int) -> str:
        return self.expected.name if idx == self.fault_idx else "OKAY"


class dtp_jtag2axi_error_test_seq(dtp_jtag2axi_base_test_seq):
    """Run one target-specific JTAG2AXI negative scenario."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_error_test_seq",
        *,
        target: str = "smc_axi",
        scenario: str = "error_single_write",
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self.target = target
        self.scenario = scenario
        # Scenario verdict: SUCCESS until a bridge status disagrees with the
        # injected response, then that observed status.
        self.status = DtpJtag2AxiStatus.SUCCESS
        self.operation_count = 0

    def bus_ledger_target(self) -> str | None:
        return None if "security_gating" in self.scenario else self.target

    def _addr(self, base: int, idx: int) -> int:
        cfg = self.target_cfg(self.target)
        return base + idx * max(cfg.beat_bytes, 0x20)

    # --- verdicts ------------------------------------------------------------
    def _check_status(
        self, name: str, observed: int, expected: DtpJtag2AxiStatus, context: str = ""
    ) -> None:
        """Judge one bridge status against the injected response and fold it into ``status``."""
        if int(observed) != int(expected):
            self.status = DtpJtag2AxiStatus(observed)
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            scoreboard.expect_equal(
                FAULT_STATUS_CHECK_ID,
                DtpJtag2AxiStatus(observed).name,
                DtpJtag2AxiStatus(expected).name,
                context=f"{name} target={self.target} {context}".strip(),
            )
        self.assert_equal(name, observed, expected, context)

    def _check_status_bit(self, name: str, observed: int, expected: int, context: str = "") -> None:
        """Judge one with-status capture bit (1 = the previous beat failed)."""
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            scoreboard.expect_equal(
                STATUS_BIT_CHECK_ID,
                observed,
                expected,
                context=f"{name} target={self.target} {context}".strip(),
            )
        self.assert_equal(name, observed, expected, context)

    async def _single_op_status(
        self,
        op: DtpJtag2AxiOp,
        addr: int,
        data: int,
        *,
        expected: DtpJtag2AxiStatus,
        context: str,
    ) -> tuple[int, int]:
        """Issue one SINGLE_OP, poll it to completion, judge its status; returns (status, rdata)."""
        size = self.target_cfg(self.target).default_size
        wstrb = self.target_full_wstrb(self.target, size) if op == DtpJtag2AxiOp.WRITE else 0
        self.log_target_jtag2axi_op(
            self.target, context, addr=addr, data=data, size=size, wstrb=wstrb
        )
        await self.write_target_single_raw(self.target, op, addr, data=data, wstrb=wstrb, size=size)
        status, rdata = await self.poll_target_single_status(self.target)
        self.scoreboard_expect_completion(self.target, status, context=context)
        self._check_status(f"{context}.status", status, expected, f"addr=0x{addr:x}")
        await self.expect_bus_request(
            self.target,
            read=op == DtpJtag2AxiOp.READ,
            addr=addr,
            size=size,
            context=context,
            data=data,
            wstrb=wstrb,
        )
        return status, rdata

    def _emit_error_nonvacuity(self, label: str) -> None:
        """CHK-AXI-NONVAC: every armed SLVERR/DECERR was consumed by a real
        bus response and each injection was followed by an OKAY recovery.

        An always-OKAY, tied-off, or wedged bridge cannot satisfy this: the
        armed credits would stay unconsumed (also failing CHK-AXI-CREDITS)
        or the recovery accesses would not complete.
        """
        scoreboard = self.axi_scoreboard
        if scoreboard is None:
            return
        unconsumed = scoreboard.unconsumed_credits()
        scoreboard.expect_nonvacuous(
            self.operation_count >= len(ERROR_RESPONSES) and unconsumed == 0,
            context=(
                f"scenario={label} target={self.target} "
                f"injections={self.operation_count} resp_set=SLVERR+DECERR "
                f"credits_unconsumed={unconsumed}"
            ),
        )

    # --- single-op error flows ----------------------------------------------
    async def _expect_error_write(self, addr: int, data: int, resp: int, context: str) -> None:
        expected = self.configure_target_error(self.target, addr, resp, read=False, write=True)
        size = self.target_cfg(self.target).default_size
        before = self.read_target_mem_int(self.target, addr, size)
        await self._single_op_status(
            DtpJtag2AxiOp.WRITE, addr, data, expected=expected, context=context
        )
        # The responder drops an armed write beat, so the error slot keeps
        # its prior value.
        after = self.read_target_mem_int(self.target, addr, size)
        self.assert_equal(f"{context}.no_write_side_effect", after, before, f"addr=0x{addr:x}")
        await self.verify_target_recovery(
            self.target,
            addr=addr + 0x400,
            data=data ^ 0x55AA_55AA_55AA_55AA,
            read=False,
            context=context,
        )
        self.operation_count += 1

    async def _expect_error_read(
        self, addr: int, data: int, resp: int, errored: int, context: str
    ) -> int:
        """One errored SINGLE_OP read and its recovery read; returns the recovery word."""
        size = self.target_cfg(self.target).default_size
        self.write_target_mem_int(self.target, addr, data, size)
        expected = self.configure_target_error(
            self.target, addr, resp, read=True, write=False, err_rdata=errored
        )
        _, rdata = await self._single_op_status(
            DtpJtag2AxiOp.READ, addr, 0, expected=expected, context=context
        )
        self.check_error_rdata(
            self.target,
            addr,
            rdata,
            resp=resp,
            preload=data,
            errored=errored,
            size=size,
            context=context,
        )
        recovery = (data ^ 0x00FF_00FF_00FF_00FF) & self.data_mask(size)
        await self.verify_target_recovery(
            self.target, addr=addr + 0x400, data=recovery, read=True, context=context
        )
        self.operation_count += 1
        return recovery

    async def run_error_single_write(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP write error")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.error_single_write")
        for idx, resp in enumerate(ERROR_RESPONSES, start=1):
            addr = self._addr(ERROR_BASE, idx)
            data = rng.getrandbits(self.target_cfg(self.target).data_width)
            self.log_iteration(
                idx, len(ERROR_RESPONSES), "write error addr=0x%08x resp=%d", addr, resp
            )
            await self._expect_error_write(addr, data, resp, f"single_write_error#{idx}")
        self._emit_error_nonvacuity("error_single_write")

    async def run_error_single_read(self) -> None:
        self.log_banner(f"{self.target} SINGLE_OP read error")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.error_single_read")
        width = self.target_cfg(self.target).data_width
        # Every word a read of this pass returned: an errored beat's word avoids
        # them, so a stale capture cannot pass for it.
        returned: list[int] = []
        for idx, resp in enumerate(ERROR_RESPONSES, start=1):
            addr = self._addr(ERROR_BASE + 0x100, idx)
            data = rng.randrange(1, 1 << width)
            errored = self.random_distinct_word(rng, self.target, data, *returned)
            self.log_iteration(
                idx,
                len(ERROR_RESPONSES),
                "read error addr=0x%08x resp=%d preload=0x%x errored=0x%x",
                addr,
                resp,
                data,
                errored,
            )
            recovery = await self._expect_error_read(
                addr, data, resp, errored, f"single_read_error#{idx}"
            )
            returned += [errored, recovery]
        self._emit_error_nonvacuity("error_single_read")

    # --- series error flows (the fault armed on one beat) --------------------
    async def _series_write_shift(
        self, data: int, *, size: int, increment: bool, with_status: bool
    ) -> int | None:
        """One series-data write shift; returns the captured status bit in status mode."""
        if with_status:
            _, status_bit = await self.series_data_with_status(
                data, size=size, increment=int(increment), target=self.target, back_to_rti=True
            )
            return status_bit
        if increment:
            await self.series_data_incr(data, size=size, target=self.target, back_to_rti=True)
        else:
            await self.series_data_no_incr(data, size=size, target=self.target, back_to_rti=True)
        return None

    async def _series_plain_read_shift(self, *, size: int, increment: bool) -> int:
        """One plain series-data read shift; returns the captured payload."""
        if increment:
            raw = await self.series_data_incr(0, size=size, target=self.target, back_to_rti=True)
        else:
            raw = await self.series_data_no_incr(0, size=size, target=self.target, back_to_rti=True)
        data, _ = unpack_series_data(raw, size)
        return data & self.data_mask(size)

    def _plan_series_fault(
        self, *, increment: bool, with_status: bool, base: int, resp: int
    ) -> _SeriesFault:
        """The stream plan: its geometry and the middle beat that carries the fault."""
        cfg = self.target_cfg(self.target)
        return _SeriesFault(
            increment=increment,
            with_status=with_status,
            size=cfg.default_size,
            stride=cfg.beat_bytes if increment else 0,
            base=self._addr(base, 1),
            fault_idx=SERIES_FAULT_BEAT,
            expected=self.axi_resp_to_jtag_status(resp),
            resp=resp,
        )

    def _arm_fault_beat(self, plan: _SeriesFault, *, read: bool, err_rdata: int = 0) -> None:
        """Arm the one-shot fault at the fault beat's address.

        A fixed-address stream revisits that address on every beat, so the
        fault is armed only once the previous beat's transaction is published.
        """
        self.configure_target_error(
            self.target, plan.fault_addr, plan.resp, read=read, write=not read, err_rdata=err_rdata
        )

    async def _series_write_beat(self, plan: _SeriesFault, idx: int, data: int) -> None:
        addr = plan.addr(idx)
        fault_before = 0
        if idx == plan.fault_idx:
            fault_before = self.read_target_mem_int(self.target, addr, plan.size)
            self._arm_fault_beat(plan, read=False)
        completed = self.port_history(self.target).count(read=False)
        before = await self.target_activity_counts(self.target)
        self.log_iteration(
            idx + 1,
            SERIES_BEATS,
            "series write addr=0x%08x resp=%s",
            addr,
            plan.beat_resp_name(idx),
        )
        status_bit = await self._series_write_shift(
            data, size=plan.size, increment=plan.increment, with_status=plan.with_status
        )
        if status_bit is not None:
            # The captured bit reports the previous beat, so only the shift
            # after the fault beat carries a 1.
            self._check_status_bit(
                f"series_write_error.status_bit#{idx}",
                status_bit,
                int(idx == plan.fault_idx + 1),
                f"addr=0x{addr:x}",
            )
        await self.wait_for_target_activity(
            self.target, before=before, read=False, context=f"series_write_error.axi#{idx}"
        )
        if not await self.wait_port_completion(self.target, read=False, above=completed):
            raise AssertionError(
                f"series_write_error.commit#{idx}: {self.target} write did not complete"
            )
        await self.expect_bus_request(
            self.target,
            read=False,
            addr=addr,
            size=plan.size,
            context=f"series_write_error#{idx}",
            data=data,
            wstrb=self.full_wstrb(plan.size),
        )
        observed = self.read_target_mem_int(self.target, addr, plan.size)
        if idx != plan.fault_idx:
            self.assert_equal(f"series_write_error.mem#{idx}", observed, data, f"addr=0x{addr:x}")
        else:
            # The responder drops the armed beat, so the slot keeps its prior value.
            self.assert_equal(
                f"series_write_error.mem_dropped#{idx}", observed, fault_before, f"addr=0x{addr:x}"
            )
        if idx > plan.fault_idx or (plan.with_status and idx < plan.fault_idx):
            return
        # The write advances the captured address by one stride, errored or not.
        status = await self.check_series_addr(
            self.target,
            addr + plan.stride,
            size=plan.size,
            context=f"series_write_error.addr#{idx}",
        )
        if idx < plan.fault_idx:
            self._check_status(
                "series_write_error.pre_fault_status",
                status,
                DtpJtag2AxiStatus.SUCCESS,
                f"beat={idx} addr=0x{addr:x}",
            )
        else:
            self._check_status(
                "series_write_error.fault_status",
                status,
                plan.expected,
                f"beat={idx} addr=0x{addr:x}",
            )

    async def _series_write_final_capture(self, plan: _SeriesFault) -> None:
        """A capture-only shift returns the last beat's outcome; it writes zero one slot past the stream."""
        addr = plan.addr(SERIES_BEATS)
        completed = self.port_history(self.target).count(read=False)
        before = await self.target_activity_counts(self.target)
        _, status_bit = await self.series_data_with_status(
            0, size=plan.size, increment=0, target=self.target, back_to_rti=True
        )
        await self.wait_for_target_activity(
            self.target, before=before, read=False, context="series_write_error.axi#final"
        )
        if not await self.wait_port_completion(self.target, read=False, above=completed):
            raise AssertionError(
                f"series_write_error.commit#final: {self.target} write did not complete"
            )
        await self.expect_bus_request(
            self.target,
            read=False,
            addr=addr,
            size=plan.size,
            context="series_write_error#final",
            wstrb=self.full_wstrb(plan.size),
        )
        self._check_status_bit(
            f"series_write_error.status_bit#{SERIES_BEATS}",
            status_bit,
            int(SERIES_BEATS - 1 == plan.fault_idx),
            f"addr=0x{addr:x}",
        )

    async def run_error_series_write(self, *, increment: bool, with_status: bool) -> None:
        mode = _series_mode(increment=increment, with_status=with_status)
        self.log_banner(f"{self.target} series {mode} write error")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_write_error.{mode}")
        plan = self._plan_series_fault(
            increment=increment,
            with_status=with_status,
            base=ERROR_BASE + 0x300,
            resp=rng.choice(ERROR_RESPONSES),
        )
        await self.jtag2axi_series_ctrl(
            DtpJtag2AxiOp.WRITE, plan.base, size=plan.size, target=self.target
        )
        width = self.target_cfg(self.target).data_width
        for idx in range(SERIES_BEATS):
            data = rng.getrandbits(width) & self.data_mask(plan.size)
            await self._series_write_beat(plan, idx, data)
        if with_status:
            await self._series_write_final_capture(plan)
        await self.verify_target_recovery(
            self.target,
            addr=RECOVERY_BASE,
            data=0xCAFE_BABE_1234_5678,
            read=False,
            context="series_write_error",
        )
        self.operation_count += SERIES_BEATS

    async def _series_read_beat(
        self, plan: _SeriesFault, idx: int, mem_expected: int, errored: int
    ) -> None:
        addr = plan.addr(idx)
        if idx == plan.fault_idx:
            self._arm_fault_beat(plan, read=True, err_rdata=errored)
        await self.jtag2axi_series_ctrl(
            DtpJtag2AxiOp.READ, addr, size=plan.size, target=self.target
        )
        completed = self.port_history(self.target).count(read=True)
        before = await self.target_activity_counts(self.target)
        self.log_iteration(
            idx + 1, SERIES_BEATS, "series read addr=0x%08x resp=%s", addr, plan.beat_resp_name(idx)
        )
        # The first shift launches the read; the bridge drops the second
        # shift's request and returns the first read's data.
        await self._series_plain_read_shift(size=plan.size, increment=plan.increment)
        await self.wait_for_target_activity(
            self.target, before=before, read=True, context=f"series_read_error.axi#{idx}"
        )
        rdata = await self._series_plain_read_shift(size=plan.size, increment=plan.increment)
        if not await self.wait_port_completion(self.target, read=True, above=completed):
            raise AssertionError(f"series_read_error.r#{idx}: {self.target} read did not complete")
        await self.expect_bus_request(
            self.target, read=True, addr=addr, size=plan.size, context=f"series_read_error#{idx}"
        )
        if idx == plan.fault_idx:
            self.check_error_rdata(
                self.target,
                addr,
                rdata,
                resp=plan.resp,
                preload=mem_expected,
                errored=errored,
                size=plan.size,
                context=f"series_read_error.fault#{idx}",
            )
        else:
            self.assert_equal(
                f"series_read_error.rdata#{idx}", rdata, mem_expected, f"addr=0x{addr:x}"
            )
        # The launched read advances the captured address by one stride,
        # errored or not; the dropped second request leaves it alone.
        status = await self.check_series_addr(
            self.target,
            addr + plan.stride,
            size=plan.size,
            context=f"series_read_error.addr#{idx}",
        )
        if idx < plan.fault_idx:
            self._check_status(
                "series_read_error.pre_fault_status",
                status,
                DtpJtag2AxiStatus.SUCCESS,
                f"beat={idx} addr=0x{addr:x}",
            )
        elif idx == plan.fault_idx:
            self._check_status(
                "series_read_error.fault_status",
                status,
                plan.expected,
                f"beat={idx} addr=0x{addr:x}",
            )

    async def _series_read_with_status_stream(self, plan: _SeriesFault, preload: list[int]) -> None:
        """Status-mode stream: shift k launches read k and returns read k-1's data and outcome.

        A with-status shift is a real read, so one CTRL programming serves the
        whole stream and a final capture-only shift returns the last beat; the
        fault beat's SERIES_CTRL status is read before the next launch.
        """
        await self.jtag2axi_series_ctrl(
            DtpJtag2AxiOp.READ, plan.base, size=plan.size, target=self.target
        )
        for shift in range(SERIES_BEATS + 1):
            launching = shift < SERIES_BEATS
            if launching:
                self.log_iteration(
                    shift + 1,
                    SERIES_BEATS,
                    "series read addr=0x%08x resp=%s",
                    plan.addr(shift),
                    plan.beat_resp_name(shift),
                )
            if shift == plan.fault_idx:
                self._arm_fault_beat(plan, read=True)
            completed = self.port_history(self.target).count(read=True)
            before = await self.target_activity_counts(self.target)
            rdata, status_bit = await self.series_data_with_status(
                0, size=plan.size, increment=int(launching), target=self.target, back_to_rti=True
            )
            await self.wait_for_target_activity(
                self.target, before=before, read=True, context=f"series_read_error.axi#{shift}"
            )
            if not await self.wait_port_completion(self.target, read=True, above=completed):
                raise AssertionError(
                    f"series_read_error.r#{shift}: {self.target} read did not complete"
                )
            await self.expect_bus_request(
                self.target,
                read=True,
                addr=plan.addr(shift),
                size=plan.size,
                context=f"series_read_error#{shift}",
            )
            if shift == plan.fault_idx:
                _, _, _, _, status = await self.read_series_ctrl(size=plan.size, target=self.target)
                self._check_status(
                    "series_read_error.fault_status",
                    status,
                    plan.expected,
                    f"beat={shift} addr=0x{plan.addr(shift):x}",
                )
            if shift == 0:
                continue
            beat = shift - 1
            self._check_status_bit(
                f"series_read_error.status_bit#{beat}",
                status_bit,
                int(beat == plan.fault_idx),
                f"addr=0x{plan.addr(beat):x}",
            )
            if beat != plan.fault_idx:
                self.assert_equal(
                    f"series_read_error.rdata#{beat}",
                    rdata & self.data_mask(plan.size),
                    preload[beat],
                    f"addr=0x{plan.addr(beat):x}",
                )

    async def run_error_series_read(self, *, increment: bool, with_status: bool) -> None:
        mode = _series_mode(increment=increment, with_status=with_status)
        self.log_banner(f"{self.target} series {mode} read error")
        await self.reset_tap()
        rng = self.rng(f"{self.target}.series_read_error.{mode}")
        plan = self._plan_series_fault(
            increment=increment,
            with_status=with_status,
            base=ERROR_BASE + 0x600,
            resp=rng.choice(ERROR_RESPONSES),
        )
        width = self.target_cfg(self.target).data_width
        preload = [
            rng.randrange(1, 1 << width) & self.data_mask(plan.size) for _ in range(SERIES_BEATS)
        ]
        for idx, value in enumerate(preload):
            self.write_target_mem_int(self.target, plan.addr(idx), value, plan.size)
        if with_status:
            await self._series_read_with_status_stream(plan, preload)
        else:
            # The errored beat's word differs from zero and from every preload,
            # so a zeroed or stale capture cannot pass for it.
            errored = self.random_distinct_word(rng, self.target, *preload)
            self.log.info("series read errored-beat word=0x%x", errored)
            for idx in range(SERIES_BEATS):
                # Without increment every beat reads the one slot the last preload filled.
                await self._series_read_beat(
                    plan, idx, preload[idx] if increment else preload[-1], errored
                )
        await self.verify_target_recovery(
            self.target,
            addr=RECOVERY_BASE + 0x100,
            data=0xDEAD_BEEF_7654_3210,
            read=True,
            context="series_read_error",
        )
        self.operation_count += SERIES_BEATS

    # --- error-path security gating ------------------------------------------
    async def _gated_error_attempt(
        self, cfg, addr: int, data: int, bit_name: str, image_rng: random.Random
    ) -> dict[str, int]:
        """Assert the target's disable, attempt an armed error write, and prove no bus
        activity and no TDR update; returns the request counters before the attempt."""
        reference = await self.gate_image_reference(self.target, image_rng, request_addr=addr)
        await self.disable_debug_bits(cfg.dbg_disable_bit)
        # arm=False: the gated op must never reach the bus, so no model
        # expectation or scoreboard credit may be armed for it (an armed
        # credit that is never consumed fails CHK-AXI-CREDITS).
        self.configure_target_error(
            self.target, addr, AXI_SLVERR, read=False, write=True, arm=False
        )
        # Hold a blocked window across the gated attempt: any monitored
        # transaction inside it fails (CHK-AXI-BLOCKED).
        gate_before = await self.target_activity_counts(self.target)
        self.scoreboard_begin_blocked(self.target)
        raw = pack_single_op(
            DtpJtag2AxiOp.WRITE,
            addr,
            data,
            wstrb=self.target_full_wstrb(self.target, cfg.default_size),
            size=cfg.default_size,
            target=cfg,
        )
        gated = await self.read_tdr(cfg.single_op_reg, raw)
        await self.expect_no_target_activity(
            self.target, 8, context=f"error_gate.{bit_name}.no_axi"
        )
        if self.axi_scoreboard is not None:
            gate_after = await self.target_activity_counts(self.target)
            self.axi_scoreboard.expect_no_activity(
                before=gate_before,
                after=gate_after,
                context=(
                    f"error_gate.{bit_name} target={self.target} "
                    f"source=tb_pulse_counters window=gated_attempt+8cyc"
                ),
            )
        post = await self.read_tdr(cfg.single_op_reg)
        self.check_gated_tdr(
            self.target,
            reference,
            raw,
            request_capture=gated,
            post_capture=post,
            context=f"error_gate.{bit_name}",
        )
        self.clear_target_errors(self.target)
        await self.enable_all_debug()
        await self.wait_sys_cycles(8)
        self.scoreboard_end_blocked(self.target, context=f"error_gate.{bit_name}")
        return gate_before

    async def run_error_security_gating(self) -> None:
        self.log_banner(f"{self.target} error-path security gating")
        await self.reset_tap()
        cfg = self.target_cfg(self.target)
        size = cfg.default_size
        addr = self._addr(ERROR_BASE + 0x900, 1)
        # Seeded per-pass payload for the gated/ungated/recovery writes.
        data = self.rng(f"{self.target}_error_gate").getrandbits(64) & self.data_mask(size)
        # The ungated error of each pass, SLVERR and DECERR in seeded order.
        ungated = self.rng(f"{self.target}_error_gate_resp").sample(ERROR_RESPONSES, 2)
        self.log.info(
            "error gate ungated responses per pass: %s",
            ", ".join(self.axi_resp_to_jtag_status(resp).name for resp in ungated),
        )
        # Two assert/release passes of the target's direct disable prove the
        # gate is repeatable, not a one-shot POR effect.
        image_rng = self.rng(f"{self.target}_error_gate_image")
        for idx in (1, 2):
            bit_name = f"{cfg.dbg_disable_bit}_pass{idx}"
            self.log_step(
                idx,
                "Gate %s with %s (pass %d) and attempt error-path write",
                self.target,
                cfg.dbg_disable_bit,
                idx,
            )
            gate_before = await self._gated_error_attempt(cfg, addr, data, bit_name, image_rng)
            expected = self.configure_target_error(
                self.target, addr, ungated[idx - 1], read=False, write=True
            )
            await self._single_op_status(
                DtpJtag2AxiOp.WRITE,
                addr,
                data ^ idx,
                expected=expected,
                context=f"error_gate.{bit_name}.ungated_error",
            )
            await self.verify_target_recovery(
                self.target,
                addr=addr + 0x400 + idx * cfg.beat_bytes,
                data=data ^ (idx << 4),
                read=False,
                context=f"error_gate.{bit_name}",
            )
            if self.axi_scoreboard is not None:
                # Exact delta from before the gated attempt: only the ungated
                # error write and the recovery write reach the bus (aw/w +2,
                # ar +0), so a replay of the gated write fails here.
                self.axi_scoreboard.expect_no_activity(
                    before={
                        "aw": gate_before["aw"] + 2,
                        "w": gate_before["w"] + 2,
                        "ar": gate_before["ar"],
                    },
                    after=await self.target_activity_counts(self.target),
                    context=(
                        f"error_gate.{bit_name} target={self.target} "
                        f"source=tb_pulse_counters window=exact_delta "
                        f"sanctioned=ungated_error_write+recovery_write(aw+2,w+2)"
                    ),
                )
            self.operation_count += 1
        self._emit_error_nonvacuity("error_security_gating")

    async def body(self) -> None:
        await self.enable_all_debug()
        scenarios = {
            "error_single_write": self.run_error_single_write,
            "error_single_read": self.run_error_single_read,
            "error_series_no_incr_write": lambda: self.run_error_series_write(
                increment=False, with_status=False
            ),
            "error_series_no_incr_read": lambda: self.run_error_series_read(
                increment=False, with_status=False
            ),
            "error_series_incr_write": lambda: self.run_error_series_write(
                increment=True, with_status=False
            ),
            "error_series_incr_read": lambda: self.run_error_series_read(
                increment=True, with_status=False
            ),
            "error_series_incr_write_with_status": lambda: self.run_error_series_write(
                increment=True, with_status=True
            ),
            "error_series_incr_read_with_status": lambda: self.run_error_series_read(
                increment=True, with_status=True
            ),
            "error_security_gating": self.run_error_security_gating,
        }
        if self.scenario not in scenarios:
            raise ValueError(f"unknown JTAG2AXI error scenario {self.scenario!r}")
        await scenarios[self.scenario]()
        scoreboard = self.axi_scoreboard
        if scoreboard is not None:
            # CHK-AXI-NONVAC for every error scenario: real operations ran and
            # no armed error credit was left unconsumed. A tied-off or wedged
            # bridge cannot satisfy both.
            unconsumed = scoreboard.unconsumed_credits()
            scoreboard.expect_nonvacuous(
                self.operation_count >= 1 and unconsumed == 0,
                context=(
                    f"scenario={self.scenario} target={self.target} "
                    f"operations={self.operation_count} credits_unconsumed={unconsumed}"
                ),
            )
        self.clear_target_errors(self.target)
        self.clear_target_backpressure(self.target)
        await self.enable_all_debug()
        self.log_summary(
            "JTAG2AXI error scenario complete",
            target=self.target,
            scenario=self.scenario,
            operations=self.operation_count,
            status=DtpJtag2AxiStatus(self.status).name,
        )
