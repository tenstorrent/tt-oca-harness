# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG-focused base sequence helpers for DTP tests."""

from __future__ import annotations

import random

import cocotb
from env.dtp_scan_model import DtpScanModel
from env.dtp_tap_device import DTP_BSR_MODEL_LEN
from env.dtp_tb_if import JTAG_SIGNAL_MAP
from env.dtp_types import DTP_IR_WIDTH, DtpJtagInstr, DtpTapFsm, DtpTapState
from ocah_jtag_vip import OcahJtagChecker, OcahJtagMasterMonitor
from ocah_lib import OcahKnobs

from .dtp_base_test_seq import dtp_base_test_seq

# Pin map for the passive scan monitor (shared by every family-checked test).


class dtp_jtag_base_test_seq(dtp_base_test_seq):
    """Helpers for TAP FSM navigation, scan loopback, and BYPASS checks."""

    # Optional shared-VIP checker; when attached, TAP resets and every raw TMS
    # step also emit reference-model named evidence.
    tap_checker: OcahJtagChecker | None = None
    # Optional passive scan monitor; when started, load_ir/shift_dr record the
    # sequence's own scan intent so finalize can cross-check the pin-level
    # reconstruction (CHK-SCAN-COUNT / CHK-SCAN-IR-LEN / CHK-SCAN-DR-LEN).
    family_monitor: OcahJtagMasterMonitor | None = None
    _family_negative: bool = False

    def attach_tap_checker(self, checker: OcahJtagChecker) -> None:
        """Route TAP reset/state navigation through VIP reference-model evidence."""
        self.tap_checker = checker

    # --- instruction-family evidence checker ---------------------------------
    async def attach_family_checker(
        self,
        required_ids: set[str],
        *,
        use_monitor: bool = True,
    ) -> OcahJtagChecker:
        """Create the per-instruction evidence checker for this sequence pass.

        Every family helper (loopback, bypass delay, IR decode, TMP persist)
        then records named ``CHK-*`` evidence instead of bare asserts, and
        ``finalize_family_checker()`` rejects a pass with zero checks or a
        missing required ID. With ``use_monitor`` a passive pin-level scan
        monitor independently reconstructs every IR/DR scan for cross-checks;
        disable it only for sequences whose scans go through driver-level TDR
        ops the sequence cannot count.

        DTP_JTAG_FAMILY_CHECKER_NEGATIVE=1 is the documented negative-
        validation hook: every integer family expectation is corrupted so the
        run must FAIL, proving the evidence path gates pass/fail end to end.
        """
        checker = OcahJtagChecker(
            name=f"{self.get_name()}.checker",
            raise_on_error=False,
            required_ids=set(required_ids),
            logger=cocotb.log,
        )
        self.attach_tap_checker(checker)
        self._family_negative = OcahKnobs.is_set("DTP_JTAG_FAMILY_CHECKER_NEGATIVE")
        if self._family_negative:
            self.log.warning("NEGATIVE VALIDATION: family checker expectations will be corrupted")
        self._expected_ir_widths: list[int] = []
        self._expected_dr_widths: list[int] = []
        if use_monitor:
            self.family_monitor = OcahJtagMasterMonitor(
                self.cfg.tb_if.jtag,
                name=f"{self.get_name()}.monitor",
                signal_map=JTAG_SIGNAL_MAP,
            )
            await self.family_monitor.start()
        return checker

    def family_check(
        self,
        check_id: str,
        name: str,
        observed: int,
        expected: int,
        *,
        context: str = "",
    ) -> None:
        """Record one named family comparison; plain assert when unattached."""
        if self.tap_checker is None:
            self.assert_equal(name, observed, expected, context)
            return
        if self._family_negative and isinstance(expected, int):
            expected = expected ^ 1
        self.tap_checker.expect_equal(
            check_id, observed, expected, context=f"{name} {context}".strip()
        )

    async def finalize_family_checker(self) -> None:
        """Cross-check monitored scans against sequence intent and finalize."""
        checker = self.tap_checker
        assert checker is not None, "family checker was never attached"
        if self.family_monitor is not None:
            await self.family_monitor.stop()
            ir_items = self.family_monitor.get_ir_transactions()
            dr_items = self.family_monitor.get_dr_transactions()
            checker.expect_equal(
                "CHK-SCAN-COUNT",
                (len(ir_items), len(dr_items)),
                (len(self._expected_ir_widths), len(self._expected_dr_widths)),
                context="monitored (ir, dr) scans vs sequence-issued scans",
            )
            if len(ir_items) == len(self._expected_ir_widths) and len(dr_items) == len(
                self._expected_dr_widths
            ):
                for idx, (item, width) in enumerate(
                    zip(ir_items, self._expected_ir_widths), start=1
                ):
                    checker.check_scan_length(item, expected_width=width, context=f"ir_scan#{idx}")
                for idx, (item, width) in enumerate(
                    zip(dr_items, self._expected_dr_widths), start=1
                ):
                    checker.check_scan_length(item, expected_width=width, context=f"dr_scan#{idx}")
            checker.expect_true(
                "CHK-NONVAC",
                len(ir_items) > 0 and len(dr_items) > 0,
                context=f"ir_scans={len(ir_items)} dr_scans={len(dr_items)}",
            )
        checker.finalize()

    def record_tap_state(self, observed: int, expected: DtpTapState) -> None:
        """Check the observed DUT TAP state and record the visit."""
        assert observed == int(expected), (
            f"TAP state mismatch: expected {expected.name} "
            f"(0x{int(expected):04x}), got 0x{observed:04x}"
        )
        self.current_tap_state = expected
        self.visited_tap_states.add(expected)
        self.log.info("Visited TAP state %-16s (0x%04x)", expected.name, observed)

    async def reset_to_tlr(self) -> None:
        """Drive the TAP to Test-Logic-Reset and check the observed state."""
        item = await self.reset_tap()
        if self.tap_checker is not None:
            self.tap_checker.check_reset_to_tlr(item.result)
        self.record_tap_state(item.result, DtpTapState.TEST_LOGIC_RESET)

    async def tms_expect(self, tms: int, expected: DtpTapState | None = None) -> None:
        """Drive one raw TMS cycle and check the next TAP state."""
        if expected is None:
            if self.current_tap_state is None:
                raise RuntimeError("current TAP state is unknown; call reset_to_tlr() first")
            expected = DtpTapFsm.get_next_state(self.current_tap_state, tms)
        item = await self.tms_step(tms)
        if self.tap_checker is not None:
            self.tap_checker.check_state_step(tms, item.result)
        self.record_tap_state(item.result, expected)

    async def load_ir(self, instr: DtpJtagInstr | int, *, back_to_rti: bool = True):
        """Load a raw IR opcode, keeping the attached TAP checker in sync."""
        item = await super().load_ir(instr, back_to_rti=back_to_rti)
        if back_to_rti and self.tap_checker is not None:
            self.tap_checker.sync_state(DtpTapState.RUN_TEST_IDLE)
        if self.family_monitor is not None:
            self._expected_ir_widths.append(DTP_IR_WIDTH)
        return item

    async def shift_ir(self, value: int, width: int, *, back_to_rti: bool = True):
        """Shift a raw IR value, keeping the attached TAP checker in sync."""
        item = await super().shift_ir(value, width, back_to_rti=back_to_rti)
        if back_to_rti and self.tap_checker is not None:
            self.tap_checker.sync_state(DtpTapState.RUN_TEST_IDLE)
        if self.family_monitor is not None:
            self._expected_ir_widths.append(width)
        return item

    async def shift_dr(self, value: int, width: int, *, back_to_rti: bool = True):
        """Shift raw DR data, keeping the attached TAP checker in sync."""
        item = await super().shift_dr(value, width, back_to_rti=back_to_rti)
        if back_to_rti and self.tap_checker is not None:
            self.tap_checker.sync_state(DtpTapState.RUN_TEST_IDLE)
        if self.family_monitor is not None:
            self._expected_dr_widths.append(width)
        return item

    async def goto_run_test_idle(self) -> None:
        """Enter Run-Test/Idle from the current tracked TAP state."""
        await self.goto_tap_state(DtpTapState.RUN_TEST_IDLE)

    async def goto_tap_state(self, target_state: DtpTapState) -> None:
        """Navigate to a TAP state from the current state using raw TMS cycles."""
        if self.current_tap_state is None:
            await self.reset_to_tlr()

        assert self.current_tap_state is not None
        path = DtpTapFsm.get_tms_path(self.current_tap_state, target_state)
        self.log.info(
            "Navigating TAP %-16s -> %-16s with TMS %s",
            self.current_tap_state.name,
            target_state.name,
            path,
        )
        for tms in path:
            await self.tms_expect(tms)

    async def goto_random_tap_state(
        self,
        *,
        rng: random.Random | None = None,
        exclude: set[DtpTapState] | None = None,
    ) -> DtpTapState:
        """Choose and navigate to a random TAP state from the current state."""
        rand = rng or random
        excluded = set(exclude or set())
        if self.current_tap_state is not None:
            excluded.add(self.current_tap_state)

        choices = [state for state in DtpTapState if state not in excluded]
        if not choices:
            raise ValueError("no TAP state choices remain after exclusions")

        target = rand.choice(choices)
        await self.goto_tap_state(target)
        return target

    async def random_tms_walk(
        self,
        cycles: int,
        *,
        rng: random.Random | None = None,
        start_state: DtpTapState | None = None,
    ) -> DtpTapState:
        """Drive random TMS bits and check each DUT state transition."""
        rand = rng or random
        if start_state is not None:
            await self.goto_tap_state(start_state)
        elif self.current_tap_state is None:
            await self.reset_to_tlr()

        for _ in range(cycles):
            await self.tms_expect(rand.randint(0, 1))

        assert self.current_tap_state is not None
        return self.current_tap_state

    @staticmethod
    def decoded_mask(instr: DtpJtagInstr | int) -> int:
        """Return the one-hot decoded-instruction bit for an IR opcode."""
        return 1 << int(instr)

    async def expect_decoded_instruction(self, instr: DtpJtagInstr | int) -> None:
        """Check the exposed decoded-instruction one-hot value, when available."""
        item = await self.sample_observables()
        if "jtag_ptap_inst_decoded" not in item.signals:
            self.log.info("Decoded-instruction observable is not exposed; skipping check")
            return

        expected = self.decoded_mask(instr)
        self.family_check(
            "CHK-IR-DECODE",
            "decoded instruction",
            item.decoded,
            expected,
            context=f"ir=0x{int(instr):02x}",
        )

    @classmethod
    def expected_bypass_tdo(cls, pattern: int, width: int, capture_bit: int = 0) -> int:
        """Expected LSB-first TDO for a one-bit bypass register."""
        if width <= 0:
            return 0
        shifted = (pattern & cls.bit_mask(max(width - 1, 0))) << 1
        return (capture_bit & 0x1) | shifted

    @classmethod
    def expected_inverted_bypass_tdo(cls, pattern: int, width: int) -> int:
        """Expected LSB-first TDO for the inverted one-bit bypass register."""
        if width <= 0:
            return 0
        inverted = (~pattern) & cls.bit_mask(max(width - 1, 0))
        return 0x1 | (inverted << 1)

    async def check_bypass_delay(
        self,
        instr: DtpJtagInstr | int,
        pattern: int,
        width: int = 64,
        *,
        capture_bit: int = 0,
    ) -> None:
        """Load a one-bit bypass instruction and check 1-TCK TDI-to-TDO delay."""
        await self.load_ir(instr)
        item = await self.shift_dr(pattern, width)
        expected = self.expected_bypass_tdo(pattern, width, capture_bit=capture_bit)
        observed = item.result & self.bit_mask(width)
        self.family_check(
            "CHK-BYPASS-DELAY",
            f"bypass TDO for IR 0x{int(instr):02x}",
            observed,
            expected,
            context=f"pattern=0x{pattern:x} width={width}",
        )

    async def check_bypass_patterns(
        self,
        instr: DtpJtagInstr | int,
        width: int = 64,
        *,
        random_count: int | None = None,
    ) -> None:
        """Check one-bit bypass behavior across reference-like pattern classes."""
        for pattern in self.directed_patterns(
            width,
            rng=self.rng(f"bypass_{int(instr):02x}"),
            random_count=random_count,
        ):
            await self.check_bypass_delay(instr, pattern, width)

    async def check_inverted_bypass_delay(
        self,
        pattern: int,
        width: int = 64,
    ) -> None:
        """Load INV_BYPASS and check inverted 1-TCK TDI-to-TDO delay."""
        await self.load_ir(DtpJtagInstr.INV_BYPASS)
        item = await self.shift_dr(pattern, width)
        expected = self.expected_inverted_bypass_tdo(pattern, width)
        observed = item.result & self.bit_mask(width)
        self.family_check(
            "CHK-INV-BYPASS",
            "inverted bypass TDO",
            observed,
            expected,
            context=f"pattern=0x{pattern:x} width={width}",
        )

    async def check_inverted_bypass_patterns(
        self,
        width: int = 64,
        *,
        random_count: int | None = None,
    ) -> None:
        """Check inverted bypass across edge, walking, and random patterns."""
        for pattern in self.directed_patterns(
            width,
            rng=self.rng("inv_bypass"),
            random_count=random_count,
        ):
            await self.check_inverted_bypass_delay(pattern, width)

    async def check_zero_length_bypass(
        self,
        pattern: int,
        width: int = 64,
    ) -> None:
        """Load ZERO_LENGTH_BYPASS and check direct TDI-to-TDO pass-through."""
        await self.load_ir(DtpJtagInstr.ZERO_LENGTH_BYPASS)
        item = await self.shift_dr(pattern, width)
        expected = pattern & self.bit_mask(width)
        observed = item.result & self.bit_mask(width)
        self.family_check(
            "CHK-ZLB-PASSTHROUGH",
            "zero-length bypass TDO",
            observed,
            expected,
            context=f"pattern=0x{pattern:x} width={width}",
        )

    async def check_zero_length_bypass_patterns(
        self,
        width: int = 64,
        *,
        random_count: int | None = None,
    ) -> None:
        """Check zero-length bypass across directed and random patterns."""
        for pattern in self.directed_patterns(
            width,
            rng=self.rng("zero_length_bypass"),
            random_count=random_count,
        ):
            await self.check_zero_length_bypass(pattern, width)

    async def check_loopback_scan(
        self,
        instr: DtpJtagInstr | int,
        pattern: int,
        width: int = DTP_BSR_MODEL_LEN,
    ) -> None:
        """Check a compact OSS scan loopback instruction with the local scan model."""
        model = DtpScanModel(width)
        await self.load_ir(instr)
        await self.expect_decoded_instruction(instr)
        item = await self.shift_dr(pattern, width)
        self.family_check(
            "CHK-BSR-LOOPBACK",
            f"IR 0x{int(instr):02x} loopback",
            item.result & model.mask,
            model.loopback_expected(pattern),
            context=f"pattern=0x{pattern:x} width={width}",
        )

    async def check_loopback_patterns(
        self,
        instr: DtpJtagInstr | int,
        width: int = DTP_BSR_MODEL_LEN,
        *,
        random_count: int | None = None,
    ) -> None:
        """Check compact scan-loopback behavior with directed/random patterns."""
        for pattern in self.directed_patterns(
            width,
            rng=self.rng(f"loopback_{int(instr):02x}"),
            random_count=random_count,
        ):
            await self.check_loopback_scan(instr, pattern, width)
