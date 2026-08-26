# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG-focused base sequence helpers for DTP tests."""

from __future__ import annotations

import random

from env.dtp_scan_model import DtpScanModel
from env.dtp_tap_device import DTP_BSR_MODEL_LEN
from env.dtp_types import DtpJtagInstr, DtpTapFsm, DtpTapState
from ocah_jtag_vip import OcahJtagChecker

from .dtp_base_test_seq import dtp_base_test_seq


class dtp_jtag_base_test_seq(dtp_base_test_seq):
    """Helpers for TAP FSM navigation, scan loopback, and BYPASS checks."""

    # Optional shared-VIP checker; when attached, TAP resets and every raw TMS
    # step also emit reference-model named evidence (issue tt-oca-hw#3296).
    tap_checker: OcahJtagChecker | None = None

    def attach_tap_checker(self, checker: OcahJtagChecker) -> None:
        """Route TAP reset/state navigation through VIP reference-model evidence."""
        self.tap_checker = checker

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
        return item

    async def shift_dr(self, value: int, width: int, *, back_to_rti: bool = True):
        """Shift raw DR data, keeping the attached TAP checker in sync."""
        item = await super().shift_dr(value, width, back_to_rti=back_to_rti)
        if back_to_rti and self.tap_checker is not None:
            self.tap_checker.sync_state(DtpTapState.RUN_TEST_IDLE)
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
        assert item.decoded == expected, (
            f"decoded instruction mismatch: expected 0x{expected:016x}, "
            f"got 0x{item.decoded:016x}"
        )

    @classmethod
    def expected_bypass_tdo(cls, pattern: int, width: int, capture_bit: int = 0) -> int:
        """Expected LSB-first TDO for a one-bit bypass register."""
        if width <= 0:
            return 0
        shifted = (pattern & cls._bit_mask(max(width - 1, 0))) << 1
        return (capture_bit & 0x1) | shifted

    @classmethod
    def expected_inverted_bypass_tdo(cls, pattern: int, width: int) -> int:
        """Expected LSB-first TDO for the inverted one-bit bypass register."""
        if width <= 0:
            return 0
        inverted = (~pattern) & cls._bit_mask(max(width - 1, 0))
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
        observed = item.result & self._bit_mask(width)
        assert observed == expected, (
            f"bypass TDO mismatch for IR 0x{int(instr):02x}: "
            f"expected 0x{expected:0{(width + 3) // 4}x}, "
            f"got 0x{observed:0{(width + 3) // 4}x}"
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
        observed = item.result & self._bit_mask(width)
        assert observed == expected, (
            f"inverted bypass TDO mismatch: expected 0x{expected:0{(width + 3) // 4}x}, "
            f"got 0x{observed:0{(width + 3) // 4}x}"
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
        expected = pattern & self._bit_mask(width)
        observed = item.result & self._bit_mask(width)
        assert observed == expected, (
            f"zero-length bypass mismatch: expected 0x{expected:0{(width + 3) // 4}x}, "
            f"got 0x{observed:0{(width + 3) // 4}x}"
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
        model.assert_loopback(item.result, pattern, f"IR 0x{int(instr):02x}")

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
