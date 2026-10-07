# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG-focused base sequence helpers for DTP tests.

Besides TAP navigation and the instruction-family checks, this layer owns the
scan-control windows: a window counts high samples of named ``dtp_scan_if``
observables on every rising TCK edge across one DR scan, so a scenario proves
which host chain the loaded instruction selects and that the TAP's strobes
reach it. A selected chain's select is high on every sample whose exported TAP
state is Capture-DR through Update-DR. The SV-UVM twin is
``uvm/seq_lib/dtp_jtag_base_test_seq.svh``.
"""

from __future__ import annotations

import random
from collections.abc import Iterable

import cocotb
from env.dtp_jtag_item import DtpJtagItem
from env.dtp_scan_model import DtpScanModel
from env.dtp_scan_window_monitor import DtpScanControlWindowMonitor, DtpTapShiftMonitor
from env.dtp_tap_device import DTP_BSR_MODEL_LEN, dtp_tap_device
from env.dtp_tb_if import JTAG_SIGNAL_MAP
from env.dtp_types import DTP_IR_WIDTH, RESET_COUNT_CHECK_ID, DtpJtagInstr, DtpScanCtrlExpect
from ocah_jtag_vip import (
    OcahJtagChecker,
    OcahJtagMasterMonitor,
    OcahJtagState,
    jtag_tms_path,
    next_jtag_state,
)
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
# Instructions other than IDCODE, which a TAP reset or a power-on reset must
# replace with IDCODE.
NON_IDCODE_PRELOADS: tuple[DtpJtagInstr, ...] = (
    DtpJtagInstr.BYPASS_00,
    DtpJtagInstr.BYPASS_3F,
    DtpJtagInstr.SAMPLE_PRELOAD,
)
# The register map the driver's TDR accesses shift, by register name.
TAP_REGISTERS = dtp_tap_device()


class dtp_jtag_base_test_seq(dtp_base_test_seq):
    """Helpers for TAP FSM navigation, scan loopback, BYPASS, and scan-control checks."""

    # Optional shared-VIP checker; when attached, TAP resets and every raw TMS
    # step also emit reference-model named evidence.
    tap_checker: OcahJtagChecker | None = None
    # Optional passive scan monitors; when started, load_ir/shift_dr and the
    # TDR accesses (read_tdr, write_tdr, read_idcode) record the sequence's
    # own scan intent so finalize can cross-check the Shift-x episodes of the
    # DUT's exported TAP state against it (CHK-SCAN-COUNT / CHK-SCAN-IR-LEN /
    # CHK-SCAN-DR-LEN); the pin-level reconstruction stays available to the
    # scenarios.
    family_monitor: OcahJtagMasterMonitor | None = None
    shift_monitor: DtpTapShiftMonitor | None = None
    # Optional per-operation scan monitor; when started, every load_ir,
    # shift_ir, and shift_dr records that the DUT's exported TAP state made
    # exactly one new Shift-x visit, as long as the width driven
    # (CHK-SCAN-IR-LEN / CHK-SCAN-DR-LEN).
    op_shift_monitor: DtpTapShiftMonitor | None = None
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
        op_scan_len: bool = False,
    ) -> OcahJtagChecker:
        """Create the per-instruction evidence checker for this sequence pass.

        Every family helper (loopback, bypass delay, IR decode, TMP persist)
        then records named ``CHK-*`` evidence instead of bare asserts, and
        ``finalize_family_checker()`` rejects a pass with zero checks or a
        missing required ID. With ``use_monitor`` a passive pin-level scan
        monitor reconstructs every IR/DR scan and a TAP shift monitor counts
        the DUT's Shift-x episodes for the cross-checks; disable them only for
        sequences whose raw TMS stimulus enters Shift-IR or Shift-DR outside a
        scan the sequence issues. With ``op_scan_len`` a separate TAP shift
        monitor judges each IR and DR scan the sequence issues on its own, so
        raw TMS walks through Shift-x between scans do not disturb the
        evidence.

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
        if op_scan_len:
            self.op_shift_monitor = DtpTapShiftMonitor(self.cfg.tb_if).start()
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

    def check_reset_counted(self, counter: str, before: int, after: int, context: str) -> None:
        """Record ``CHK-RESET-COUNT`` on the attached checker; plain assert when unattached.

        The record bypasses ``family_check``, so
        DTP_JTAG_FAMILY_CHECKER_NEGATIVE does not corrupt it.
        """
        if self.tap_checker is None:
            super().check_reset_counted(counter, before, after, context)
            return
        self.tap_checker.expect_equal(
            RESET_COUNT_CHECK_ID,
            after - before,
            1,
            context=f"{counter} before={before} after={after} {context}",
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
        if self.op_shift_monitor is not None:
            self.op_shift_monitor.stop()
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

    def record_tap_state(self, observed: int, expected: OcahJtagState) -> None:
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
        self.record_tap_state(item.result, OcahJtagState.TEST_LOGIC_RESET)

    async def tms_expect(
        self, tms: int, expected: OcahJtagState | None = None, *, tdi: int = 0
    ) -> None:
        """Drive one raw TMS cycle and check the next TAP state.

        A step that lands where the IEEE 1149.1 table sends the tracked state
        records its (state, TMS) transition in ``visited_tap_arcs``.
        """
        previous = self.current_tap_state
        if expected is None:
            if previous is None:
                raise RuntimeError("current TAP state is unknown; call reset_to_tlr() first")
            expected = next_jtag_state(previous, tms)
        item = await self.tms_step(tms, tdi=tdi)
        if self.tap_checker is not None:
            self.tap_checker.check_state_step(tms, item.result)
        self.record_tap_state(item.result, expected)
        if previous is not None and next_jtag_state(previous, tms) == expected:
            self.visited_tap_arcs.add((previous, tms & 0x1))

    def _op_scan_mark(self, *, is_ir: bool) -> int | None:
        """Episodes of one kind the per-operation shift monitor holds, when it runs."""
        monitor = self.op_shift_monitor
        if monitor is None:
            return None
        return len(monitor.ir_lens if is_ir else monitor.dr_lens)

    def check_op_scan_length(
        self, *, is_ir: bool, width: int, before: int | None, context: str
    ) -> None:
        """Record CHK-SCAN-IR-LEN / CHK-SCAN-DR-LEN for one scan this sequence issued.

        Since ``before`` the DUT's exported TAP state made exactly one new
        Shift-x visit, and that visit is ``width`` TCK cycles long.
        """
        if before is None:
            return
        assert self.tap_checker is not None and self.op_shift_monitor is not None
        kind = "IR" if is_ir else "DR"
        check_id = f"CHK-SCAN-{kind}-LEN"
        lens = self.op_shift_monitor.ir_lens if is_ir else self.op_shift_monitor.dr_lens
        new = len(lens) - before
        self.tap_checker.expect_equal(
            check_id, new, 1, context=f"new DUT Shift-{kind} episodes {context}"
        )
        if new == 1:
            self.tap_checker.expect_equal(
                check_id,
                lens[-1],
                width,
                context=f"kind={kind} source=jtag_ptap_state_o {context}",
            )

    async def load_ir(self, instr: DtpJtagInstr | int, *, back_to_rti: bool = True):
        """Load a raw IR opcode, keeping the attached TAP checker in sync."""
        before = self._op_scan_mark(is_ir=True)
        item = await super().load_ir(instr, back_to_rti=back_to_rti)
        if back_to_rti and self.tap_checker is not None:
            self.tap_checker.sync_state(OcahJtagState.RUN_TEST_IDLE)
        if self.family_monitor is not None:
            self._expected_ir_widths.append(DTP_IR_WIDTH)
        self.check_op_scan_length(
            is_ir=True, width=DTP_IR_WIDTH, before=before, context=f"ir=0x{int(instr):02x}"
        )
        return item

    async def shift_ir(self, value: int, width: int, *, back_to_rti: bool = True):
        """Shift a raw IR value, keeping the attached TAP checker in sync."""
        before = self._op_scan_mark(is_ir=True)
        item = await super().shift_ir(value, width, back_to_rti=back_to_rti)
        if back_to_rti and self.tap_checker is not None:
            self.tap_checker.sync_state(OcahJtagState.RUN_TEST_IDLE)
        if self.family_monitor is not None:
            self._expected_ir_widths.append(width)
        self.check_op_scan_length(
            is_ir=True, width=width, before=before, context=f"raw ir width={width}"
        )
        return item

    async def shift_dr(self, value: int, width: int, *, back_to_rti: bool = True):
        """Shift raw DR data, keeping the attached TAP checker in sync."""
        before = self._op_scan_mark(is_ir=False)
        item = await super().shift_dr(value, width, back_to_rti=back_to_rti)
        if back_to_rti and self.tap_checker is not None:
            self.tap_checker.sync_state(OcahJtagState.RUN_TEST_IDLE)
        if self.family_monitor is not None:
            self._expected_dr_widths.append(width)
        self.check_op_scan_length(
            is_ir=False, width=width, before=before, context=f"pattern=0x{value:x}"
        )
        return item

    async def read_tdr(self, reg: str, shift_value: int = 0) -> int:
        """Read a named TDR, recording its IR and DR scans as scan intent."""
        value = await super().read_tdr(reg, shift_value)
        self._note_tdr_access(reg)
        return value

    async def write_tdr(self, reg: str, value: int) -> None:
        """Write a named TDR, recording its IR and DR scans as scan intent."""
        await super().write_tdr(reg, value)
        self._note_tdr_access(reg)

    async def read_idcode(self) -> DtpJtagItem:
        """Read IDCODE, recording its IR and DR scans as scan intent."""
        item = await super().read_idcode()
        self._note_tdr_access("IDCODE")
        return item

    def _note_tdr_access(self, reg: str) -> None:
        """Record the two scans a driver-level TDR access makes for the family cross-check.

        The access loads the register's instruction and then shifts the
        register; the driver issues no DR scan for a zero-width register.
        """
        if self.family_monitor is None:
            return
        self._expected_ir_widths.append(DTP_IR_WIDTH)
        width = TAP_REGISTERS.reg(reg).width
        if width > 0:
            self._expected_dr_widths.append(width)

    async def goto_run_test_idle(self) -> None:
        """Enter Run-Test/Idle from the current tracked TAP state."""
        await self.goto_tap_state(OcahJtagState.RUN_TEST_IDLE)

    async def goto_tap_state(self, target_state: OcahJtagState) -> None:
        """Navigate to a TAP state from the current state using raw TMS cycles."""
        if self.current_tap_state is None:
            await self.reset_to_tlr()

        assert self.current_tap_state is not None
        path = jtag_tms_path(self.current_tap_state, target_state)
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
        exclude: set[OcahJtagState] | None = None,
    ) -> OcahJtagState:
        """Choose and navigate to a random TAP state from the current state."""
        rand = rng or random
        excluded = set(exclude or set())
        if self.current_tap_state is not None:
            excluded.add(self.current_tap_state)

        choices = [state for state in OcahJtagState if state not in excluded]
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
        start_state: OcahJtagState | None = None,
        random_tdi: bool = False,
    ) -> OcahJtagState:
        """Drive random TMS bits (and TDI bits with ``random_tdi``) and check each DUT state."""
        rand = rng or random
        if start_state is not None:
            await self.goto_tap_state(start_state)
        elif self.current_tap_state is None:
            await self.reset_to_tlr()

        for _ in range(cycles):
            tms = rand.randint(0, 1)
            await self.tms_expect(tms, tdi=rand.randint(0, 1) if random_tdi else 0)

        assert self.current_tap_state is not None
        return self.current_tap_state

    @staticmethod
    def decoded_mask(instr: DtpJtagInstr | int) -> int:
        """Return the one-hot decoded-instruction bit for an IR opcode."""
        return 1 << int(instr)

    async def expect_decoded_instruction(self, instr: DtpJtagInstr | int) -> None:
        """Record the exposed decoded-instruction one-hot value (CHK-IR-DECODE)."""
        item = await self.sample_observables()
        if "jtag_ptap_inst_decoded" not in item.signals:
            raise KeyError("jtag_ptap_inst_decoded is not exposed by the DTP JTAG driver")

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
        """Check a compact OSS scan loopback instruction with the local scan model.

        The looped-back chain returns the same TDO as the one-bit bypass
        register, so this proves the data path only; chain selection is
        ``CHK-BSR-SELECT`` under a scan-control window (``check_bsr_scan_ctrl``).
        """
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
        self.log.info(
            "DR scan width=%d window edges=%d counts=%s dr_scan=%d %s rti=%d %s",
            width,
            edges,
            counts,
            window.dr_scan_edges,
            window.dr_scan_high_counts,
            window.rti_edges,
            window.rti_high_counts,
        )
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
        host shows none of them. The DUT's exported TAP state spends
        ``width + 3`` samples in Capture-DR through Update-DR whatever the
        host does. A selected chain's select is high on each of those
        samples; any other chain's select stays low across the whole window.
        """
        window = self._last_window
        assert window is not None, "no scan window was opened"
        select_id, ctrl_id = SCAN_CTRL_CHECK_IDS[prefix]
        select = f"{prefix}_select"
        strobes = mode is not DtpScanCtrlExpect.GATED
        expected = {
            "capture_en": int(strobes),
            "shift_en": width if strobes else 0,
            "update_en": int(strobes),
        }
        self.family_check(
            ctrl_id,
            "Capture-DR..Update-DR samples",
            window.dr_scan_edges,
            width + 3,
            context=f"{mode.value} {context}",
        )
        if mode is DtpScanCtrlExpect.SELECTED:
            self.family_check(
                select_id,
                f"{select} high at every Capture-DR..Update-DR sample",
                window.dr_scan_high_counts[select],
                window.dr_scan_edges,
                context=f"{mode.value} {context}",
            )
        else:
            self.family_check(
                select_id,
                f"{select} high samples",
                counts[select],
                0,
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

    def check_run_test_idle_window(self, check_id: str, signal: str, *, context: str) -> None:
        """Judge a Run-Test/Idle decode across the DR scan of the last window.

        The decode is low on every sample whose exported TAP state is not
        Run-Test/Idle and high on the window's last sample, the scan's return
        to Run-Test/Idle.
        """
        window = self._last_window
        assert window is not None, "no scan window was opened"
        returned = window.last_state == int(OcahJtagState.RUN_TEST_IDLE)
        self.family_check(
            check_id,
            f"{signal} high outside Run-Test/Idle",
            window.high_counts[signal] - window.rti_high_counts[signal],
            0,
            context=f"{context} edges={window.edges}",
        )
        self.family_check(
            check_id,
            f"{signal} high on the return to Run-Test/Idle",
            int(returned and window.last_high[signal] == 1),
            1,
            context=f"{context} last_state=0x{window.last_state or 0:04x}",
        )

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
