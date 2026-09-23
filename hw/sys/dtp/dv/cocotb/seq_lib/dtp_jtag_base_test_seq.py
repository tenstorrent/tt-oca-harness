# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG-focused base sequence helpers for DTP tests.

Besides TAP navigation and the instruction-family checks, this layer owns the
scan-control windows: a window counts high samples of named ``dtp_scan_if``
observables on every rising TCK edge across one DR scan, so a scenario proves
which host chain the loaded instruction selects and that the TAP's strobes
reach it. The SV-UVM twin is ``uvm/seq_lib/dtp_jtag_base_test_seq.svh``.
"""

from __future__ import annotations

import random
from collections.abc import Iterable

import cocotb
from env.dtp_jtag_item import DtpJtagItem
from env.dtp_scan_model import DtpScanModel
from env.dtp_scan_window_monitor import DtpScanControlWindowMonitor, DtpTapShiftMonitor
from env.dtp_tap_device import DTP_BSR_MODEL_LEN
from env.dtp_tb_if import JTAG_SIGNAL_MAP
from env.dtp_types import (
    DTP_IR_WIDTH,
    DtpJtagInstr,
    DtpScanCtrlExpect,
    DtpTapFsm,
    DtpTapState,
)
from ocah_jtag_vip import OcahJtagChecker, OcahJtagMasterMonitor
from ocah_lib import OcahKnobs

from .dtp_base_test_seq import dtp_base_test_seq

# Host scan-control fields every chain exposes on dtp_scan_if, by suffix.
SCAN_CTRL_SUFFIXES: tuple[str, ...] = ("select", "capture_en", "shift_en", "update_en")
# dtp_scan_if prefixes of the boundary-scan chain and the non-secure DFT host.
BSR_SCAN_CTRL = "jtag_bsr"
DFT_SCAN_CTRL = "jtag_dft"
# The instruction-qualified host chain selects: boundary scan and the three
# iJTAG SIB hosts. The extended STAP host select follows every IR and DR
# scan path regardless of the instruction, so it is not one of them.
HOST_SELECTS: tuple[str, ...] = (
    "jtag_bsr_select",
    "jtag_dft_secure_select",
    "jtag_dft_select",
    "jtag_dfd_select",
)
# Evidence IDs (select, strobes) of each chain's control window, and of the
# quiet host-select window.
SCAN_CTRL_CHECK_IDS: dict[str, tuple[str, str]] = {
    BSR_SCAN_CTRL: ("CHK-BSR-SELECT", "CHK-BSR-SCAN-CTRL"),
    DFT_SCAN_CTRL: ("CHK-DFT-SIB-SELECT", "CHK-DFT-SCAN-CTRL"),
}
NO_HOST_SELECT_CHECK_ID = "CHK-UNDEF-NO-SELECT"


class dtp_jtag_base_test_seq(dtp_base_test_seq):
    """Helpers for TAP FSM navigation, scan loopback, BYPASS, and scan-control checks."""

    # Optional shared-VIP checker; when attached, TAP resets and every raw TMS
    # step also emit reference-model named evidence.
    tap_checker: OcahJtagChecker | None = None
    # Optional passive scan monitors; when started, load_ir/shift_dr record the
    # sequence's own scan intent so finalize can cross-check the Shift-x
    # episodes of the DUT's exported TAP state against it (CHK-SCAN-COUNT /
    # CHK-SCAN-IR-LEN / CHK-SCAN-DR-LEN); the pin-level reconstruction stays
    # available to the scenarios.
    family_monitor: OcahJtagMasterMonitor | None = None
    shift_monitor: DtpTapShiftMonitor | None = None
    # The scan-control window most recently opened by this sequence.
    _last_window: DtpScanControlWindowMonitor | None = None
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
        monitor reconstructs every IR/DR scan and a TAP shift monitor counts
        the DUT's Shift-x episodes for the cross-checks; disable them only for
        sequences whose scans go through driver-level TDR ops the sequence
        cannot count.

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
            self.shift_monitor = DtpTapShiftMonitor(self.cfg.tb_if).start()
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
        """Cross-check the DUT's Shift-x episodes against sequence intent and finalize.

        The DUT exports its TAP state on ``jtag_ptap_state_o``; the shift
        monitor turns every Shift-IR / Shift-DR visit into an episode whose
        length is the scan the DUT performed. As many episodes as scans issued,
        each as long as the width driven, is the scan evidence.
        """
        checker = self.tap_checker
        assert checker is not None, "family checker was never attached"
        if self.family_monitor is not None:
            await self.family_monitor.stop()
        if self.shift_monitor is not None:
            self.shift_monitor.stop()
            ir_lens = self.shift_monitor.ir_lens
            dr_lens = self.shift_monitor.dr_lens
            checker.expect_equal(
                "CHK-SCAN-COUNT",
                (len(ir_lens), len(dr_lens)),
                (len(self._expected_ir_widths), len(self._expected_dr_widths)),
                context="DUT Shift episodes (ir, dr) vs sequence-issued scans",
            )
            if len(ir_lens) == len(self._expected_ir_widths) and len(dr_lens) == len(
                self._expected_dr_widths
            ):
                for idx, (length, width) in enumerate(
                    zip(ir_lens, self._expected_ir_widths), start=1
                ):
                    self.family_check(
                        "CHK-SCAN-IR-LEN",
                        f"ir_scan#{idx}",
                        length,
                        width,
                        context="source=jtag_ptap_state_o",
                    )
                for idx, (length, width) in enumerate(
                    zip(dr_lens, self._expected_dr_widths), start=1
                ):
                    self.family_check(
                        "CHK-SCAN-DR-LEN",
                        f"dr_scan#{idx}",
                        length,
                        width,
                        context="source=jtag_ptap_state_o",
                    )
            checker.expect_true(
                "CHK-NONVAC",
                len(ir_lens) > 0 and len(dr_lens) > 0,
                context=f"DUT Shift-IR episodes={len(ir_lens)} Shift-DR episodes={len(dr_lens)}",
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

    def check_bypass_tdo(
        self,
        instr: DtpJtagInstr | int,
        observed: int,
        pattern: int,
        width: int,
        *,
        capture_bit: int = 0,
        context: str = "",
    ) -> None:
        """Record CHK-BYPASS-DELAY: the TDO of a one-bit bypass scan is TDI one TCK late."""
        expected = self.expected_bypass_tdo(pattern, width, capture_bit=capture_bit)
        self.family_check(
            "CHK-BYPASS-DELAY",
            f"bypass TDO for IR 0x{int(instr):02x}",
            observed & self.bit_mask(width),
            expected,
            context=f"pattern=0x{pattern:x} width={width} {context}".strip(),
        )

    async def check_bypass_delay(
        self,
        instr: DtpJtagInstr | int,
        pattern: int,
        width: int = 64,
        *,
        capture_bit: int = 0,
    ) -> None:
        """Load a one-bit bypass instruction, check its decode and 1-TCK TDI-to-TDO delay."""
        await self.load_ir(instr)
        await self.expect_decoded_instruction(instr)
        item = await self.shift_dr(pattern, width)
        self.check_bypass_tdo(instr, item.result, pattern, width, capture_bit=capture_bit)

    async def check_bypass_no_host_select(
        self,
        instr: DtpJtagInstr | int,
        pattern: int,
        width: int = 64,
    ) -> None:
        """Bypass-delay check with every instruction-qualified host select quiet across the scan."""
        await self.load_ir(instr)
        await self.expect_decoded_instruction(instr)
        item, edges, counts = await self.shift_dr_windowed(pattern, width, HOST_SELECTS)
        context = f"ir=0x{int(instr):02x} width={width} edges={edges}"
        self.check_bypass_tdo(instr, item.result, pattern, width, context=context)
        self.check_quiet_window(NO_HOST_SELECT_CHECK_ID, edges, counts, context=context)

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

    # --- scan-control windows --------------------------------------------------
    def start_scan_window(self, signals: Iterable[str]) -> DtpScanControlWindowMonitor:
        """Begin sampling named scan observables on every rising TCK edge."""
        self._last_window = DtpScanControlWindowMonitor(self.cfg.tb_if, signals).start()
        return self._last_window

    def check_window_shifted(self, check_id: str, monitor, *, context: str) -> None:
        """Record that the DUT's TAP shifted inside the closed window.

        Its exported state visited Shift-DR or Shift-IR, so the counts judged
        next were taken across a scan the DUT performed; a TAP held in reset or
        a dead state output records zero cycles here and fails.
        """
        cycles = monitor.dut_shift_cycles
        self.family_check(
            check_id,
            "window DUT shift cycles nonvacuous",
            int(cycles > 0),
            1,
            context=f"{context} dut_shift_cycles={cycles}",
        )

    @staticmethod
    def scan_ctrl_signals(prefix: str) -> tuple[str, ...]:
        """The four host scan-control observables of one chain prefix."""
        return tuple(f"{prefix}_{suffix}" for suffix in SCAN_CTRL_SUFFIXES)

    async def shift_dr_windowed(
        self,
        value: int,
        width: int,
        signals: tuple[str, ...],
    ) -> tuple[DtpJtagItem, int, dict[str, int]]:
        """Shift DR from Run-Test/Idle while a window counts high samples of ``signals``."""
        window = self.start_scan_window(signals)
        item = await self.shift_dr(value, width)
        edges, counts = window.stop()
        self.log.info("DR scan width=%d window edges=%d counts=%s", width, edges, counts)
        return item, edges, counts

    def check_scan_ctrl_counts(
        self,
        prefix: str,
        counts: dict[str, int],
        *,
        width: int,
        mode: DtpScanCtrlExpect,
        context: str,
    ) -> None:
        """Judge one chain's control counts across a ``width``-bit DR scan.

        The scan enters Shift-DR before its first bit, so the TAP's strobes
        pulse capture once, shift ``width`` times, and update once; a gated
        host shows none of them. Select is high only for the chain's own
        instruction.
        """
        select_id, ctrl_id = SCAN_CTRL_CHECK_IDS[prefix]
        strobes = mode is not DtpScanCtrlExpect.GATED
        expected = {
            "capture_en": int(strobes),
            "shift_en": width if strobes else 0,
            "update_en": int(strobes),
        }
        self.family_check(
            select_id,
            f"{prefix}_select asserted",
            int(counts[f"{prefix}_select"] > 0),
            int(mode is DtpScanCtrlExpect.SELECTED),
            context=f"{mode.value} {context}",
        )
        for suffix, value in expected.items():
            self.family_check(
                ctrl_id,
                f"{prefix}_{suffix} pulses",
                counts[f"{prefix}_{suffix}"],
                value,
                context=f"{mode.value} {context}",
            )

    def check_quiet_window(
        self,
        check_id: str,
        edges: int,
        counts: dict[str, int],
        *,
        context: str,
    ) -> None:
        """Record that a window the DUT shifted through saw every counted observable stay low."""
        assert self._last_window is not None, "no scan window was opened"
        self.check_window_shifted(check_id, self._last_window, context=f"{context} edges={edges}")
        for name, count in counts.items():
            self.family_check(check_id, f"{name} quiet", count, 0, context=context)

    async def check_bsr_scan_ctrl(
        self,
        instr: DtpJtagInstr | int,
        pattern: int,
        width: int = DTP_BSR_MODEL_LEN,
        *,
        mode: DtpScanCtrlExpect = DtpScanCtrlExpect.SELECTED,
        extra_signals: tuple[str, ...] = (),
    ) -> dict[str, int]:
        """Load an instruction and judge its DR scan under a boundary-scan control window.

        A boundary-scan instruction selects the looped-back chain
        (CHK-BSR-SELECT, CHK-BSR-LOOPBACK); any other instruction leaves the
        select low and scans the one-bit bypass register (CHK-BYPASS-DELAY).
        The TAP's strobes pulse either way (CHK-BSR-SCAN-CTRL). Returns the
        window counts, including ``extra_signals``.
        """
        await self.load_ir(instr)
        await self.expect_decoded_instruction(instr)
        signals = self.scan_ctrl_signals(BSR_SCAN_CTRL) + tuple(extra_signals)
        item, edges, counts = await self.shift_dr_windowed(pattern, width, signals)
        context = f"ir=0x{int(instr):02x} pattern=0x{pattern:x} width={width} edges={edges}"
        self.check_scan_ctrl_counts(BSR_SCAN_CTRL, counts, width=width, mode=mode, context=context)
        if mode is DtpScanCtrlExpect.SELECTED:
            model = DtpScanModel(width)
            self.family_check(
                "CHK-BSR-LOOPBACK",
                f"IR 0x{int(instr):02x} loopback",
                item.result & model.mask,
                model.loopback_expected(pattern),
                context=context,
            )
        else:
            self.check_bypass_tdo(instr, item.result, pattern, width, context=context)
        return counts

    async def check_scan_observable(
        self,
        check_id: str,
        name: str,
        expected: int,
        *,
        context: str = "",
    ) -> None:
        """Sample one scan-domain observable through the driver and record it."""
        item = await self.sample_observables()
        if name not in item.signals:
            raise KeyError(f"{name} is not exposed by the DTP JTAG driver")
        self.family_check(check_id, name, item.signals[name], expected, context=context)
