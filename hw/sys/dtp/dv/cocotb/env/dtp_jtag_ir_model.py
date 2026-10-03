# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary-TAP instruction model: TAP state, active instruction and PTAP 3DCR.

Rebuilt from the JTAG monitor's per-TCK events and reconstructed scans.
Update-IR latches the instruction shift register: after one plain 6-bit IR
scan that is the scanned opcode; after an IR scan that reaches Update-IR
without a Shift-IR cycle it is the Capture-IR pattern
(``DTP_IR_CAPTURE_PATTERN``, the IDCODE opcode); a composed scan (wider,
spanning the STAP chain) or a re-shifted instruction scan leaves it unknown
until the next plain load or TAP reset. Test-Logic-Reset by TRST or TMS, and
power-on reset, load the device-identification instruction (IEEE 1149.1
6.1.1).

The model also tracks the PTAP 3DCR, ``{stap_sel, config_hold}``. The 3DCR
takes TDI directly, so Update-DR under TAP_3DCR latches the last two bits the
scan shifted in, or the shifted bit and the old stap_sel after a one-bit scan.
Test-Logic-Reset by TMS clears it unless config_hold is set; TRST and power-on
reset always clear it. Whether a data scan ran under TAP_3DCR is decided from
the instruction register's shifted value, which stays known through composed
and re-shifted instruction scans. While the select is set the PTAP splices the
STAP chain onto the TDO end of every data scan, so a model that predicts TDO
carries no contract unless ``ptap_select_clear()`` holds.

Plain class held by the JTAG reference models; no reporting. The SV-UVM twin
is ``dtp_jtag_ir_model``.
"""

from __future__ import annotations

from ocah_jtag_vip import OcahJtagEvent, OcahJtagScanItem, OcahJtagState, next_jtag_state

from .dtp_types import DTP_IR_CAPTURE_PATTERN, DTP_IR_WIDTH, DtpJtagInstr

__all__ = ["DtpJtagIrModel"]

_IR_MASK = (1 << DTP_IR_WIDTH) - 1


class DtpJtagIrModel:
    """TAP state, active PTAP instruction and PTAP 3DCR, from monitor events and scans."""

    def __init__(self) -> None:
        self._por_seen = 0
        self._ir_loads = 0
        self._ptap_select = 0
        self._ptap_config_hold = 0
        self.reset_tap()

    # --- monitor streams ------------------------------------------------------
    def on_event(self, event: OcahJtagEvent) -> bool:
        """One TCK cycle or TRST edge; True when an instruction became active on it.

        An instruction becomes active on the cycle leaving Update-IR.
        """
        if event.kind == "TRST":
            if event.trst_asserted:
                self._hard_reset()
            return False
        if event.trst_n == 0:
            self._hard_reset()
            return False
        committed = False
        if self._tap is OcahJtagState.UPDATE_IR:
            committed = self._commit_instruction()
        if self._tap is OcahJtagState.UPDATE_DR:
            self._commit_data_scan()
        self._tap = next_jtag_state(self._tap, event.tms)
        if self._tap is OcahJtagState.TEST_LOGIC_RESET:
            self.reset_tap()
            if not self._ptap_config_hold:
                self._ptap_select = 0
        return committed

    def on_ir_scan(self, item: OcahJtagScanItem) -> None:
        """One reconstructed IR scan (published on Shift-IR -> Exit1-IR)."""
        self._pending_ir_scans += 1
        self._pending_ir_valid = item.bit_count == DTP_IR_WIDTH
        self._pending_ir = item.tdi_value & _IR_MASK
        self._pending_ir_item = item

    def on_dr_scan(self, item: OcahJtagScanItem) -> None:
        """One reconstructed DR scan (published on Shift-DR -> Exit1-DR)."""
        self._pending_dr_item = item

    def sync_power_on_reset(self, por_assert_count: int) -> bool:
        """Reset on a new power-on reset assertion; True when one was seen.

        Power-on reset moves the TAP without a TCK edge or a TRST event, so the
        ``dtp_tb_if`` assertion counter is the observable.
        """
        if por_assert_count == self._por_seen:
            return False
        self._por_seen = por_assert_count
        self._hard_reset()
        return True

    # --- queries ----------------------------------------------------------------
    def ptap_select_clear(self) -> bool:
        """True while the PTAP 3DCR select is clear, so a data scan covers the PTAP register alone."""
        return not self._ptap_select

    def take_tap_reset(self) -> bool:
        """Set by every TAP reset and cleared by the caller that consumed it."""
        seen = self._tap_reset_seen
        self._tap_reset_seen = False
        return seen

    def ir_known(self) -> bool:
        return self._ir_known

    def ir(self) -> int:
        return self._ir

    def ir_loads(self) -> int:
        return self._ir_loads

    def tap_state(self) -> OcahJtagState:
        return self._tap

    def reset_tap(self) -> None:
        """Test-Logic-Reset: the TAP state and the instruction, not the 3DCR."""
        self._tap = OcahJtagState.TEST_LOGIC_RESET
        self._ir = int(DtpJtagInstr.IDCODE)
        self._ir_known = True
        # The instruction register's value after the last Update-IR or reset.
        # The PTAP IR is the TDI-nearest segment of every instruction scan, so
        # it holds the last six bits shifted in, or for a shorter scan the
        # shifted bits above the rest of the Capture-IR pattern.
        self._shift_ir = int(DtpJtagInstr.IDCODE)
        self._pending_ir_valid = False
        self._pending_ir = 0
        self._pending_ir_scans = 0
        self._pending_ir_item: OcahJtagScanItem | None = None
        self._pending_dr_item: OcahJtagScanItem | None = None
        self._tap_reset_seen = True

    # --- internals ----------------------------------------------------------------
    def _hard_reset(self) -> None:
        """TRST and power-on reset: the TAP reset plus a 3DCR clear config_hold cannot block."""
        self.reset_tap()
        self._ptap_select = 0
        self._ptap_config_hold = 0

    def _commit_data_scan(self) -> None:
        """Update-DR: a TAP_3DCR scan that shifted at least one bit latches the 3DCR.

        A capture that reaches Update-DR without a Shift-DR cycle writes back
        the captured value.
        """
        item = self._pending_dr_item
        n = item.bit_count if item is not None else 0
        if self._shift_ir == int(DtpJtagInstr.TAP_3DCR) and n != 0:
            last = (item.tdi_value >> (n - 1)) & 0x1
            self._ptap_config_hold = (
                (item.tdi_value >> (n - 2)) & 0x1 if n >= 2 else self._ptap_select
            )
            self._ptap_select = last
        self._pending_dr_item = None

    def _commit_instruction(self) -> bool:
        """Latch the instruction register on the cycle leaving Update-IR.

        The active instruction is the Capture-IR pattern when no Shift-IR cycle
        followed the capture, the scanned opcode after one plain 6-bit scan,
        and unknown otherwise; ``_shift_ir`` follows every scan.
        """
        shift_ir = DTP_IR_CAPTURE_PATTERN
        item = self._pending_ir_item
        if item is not None:
            for idx in range(item.bit_count):
                shift_ir = (((item.tdi_value >> idx) & 0x1) << (DTP_IR_WIDTH - 1)) | (shift_ir >> 1)
        self._shift_ir = shift_ir
        self._pending_ir_item = None
        known = True
        if self._pending_ir_scans == 0:
            latched = DTP_IR_CAPTURE_PATTERN
        elif self._pending_ir_scans == 1 and self._pending_ir_valid:
            latched = self._pending_ir
        else:
            known = False
            latched = 0
        self._pending_ir_valid = False
        self._pending_ir_scans = 0
        self._ir_known = known
        if not known:
            return False
        self._ir = latched
        self._ir_loads += 1
        return True


def _selftest() -> None:
    """Drive the model through scripted TMS/TDI streams without a simulator.

    Runs as ``python -m env.dtp_jtag_ir_model`` from ``hw/sys/dtp/dv/cocotb``.
    Covers a plain IDCODE-to-BYPASS load, a composed IR scan that leaves the
    active instruction unknown while the shifted value stays known, a
    TAP_3DCR write that sets stap_sel with config_hold so a TMS
    Test-Logic-Reset keeps the select, TRST and power-on reset clearing it,
    and a one-bit TAP_3DCR scan.
    """
    state = {"tap": OcahJtagState.TEST_LOGIC_RESET, "acc": [], "kind": ""}
    model = DtpJtagIrModel()
    model.sync_power_on_reset(0)

    def step(tms: int, tdi: int = 0) -> bool:
        previous = state["tap"]
        if previous in (OcahJtagState.CAPTURE_IR, OcahJtagState.CAPTURE_DR):
            state["acc"] = []
        if previous in (OcahJtagState.SHIFT_IR, OcahJtagState.SHIFT_DR):
            state["acc"].append(tdi)
        nxt = next_jtag_state(previous, tms)
        state["tap"] = nxt
        if (previous, nxt) in (
            (OcahJtagState.SHIFT_IR, OcahJtagState.EXIT1_IR),
            (OcahJtagState.SHIFT_DR, OcahJtagState.EXIT1_DR),
        ):
            bits = state["acc"]
            item = OcahJtagScanItem(
                kind="IR" if previous is OcahJtagState.SHIFT_IR else "DR",
                tdi_value=sum(bit << idx for idx, bit in enumerate(bits)),
                tdo_value=0,
                bit_count=len(bits),
            )
            (model.on_ir_scan if item.is_ir else model.on_dr_scan)(item)
        return model.on_event(OcahJtagEvent(kind="STEP", tms=tms, tdi=tdi))

    def tlr() -> None:
        for _ in range(5):
            step(1)
        step(0)

    def scan(ir: bool, value: int, width: int) -> None:
        # From Run-Test/Idle: Select-DR [, Select-IR], Capture, Shift x width,
        # Exit1, Update, Run-Test/Idle.
        step(1)
        if ir:
            step(1)
        step(0)
        step(0)
        for idx in range(width):
            step(1 if idx == width - 1 else 0, (value >> idx) & 0x1)
        step(1)
        step(0)

    tlr()
    assert model.ir_known() and model.ir() == int(DtpJtagInstr.IDCODE)
    scan(True, int(DtpJtagInstr.BYPASS_3F), DTP_IR_WIDTH)
    assert model.ir_known() and model.ir() == int(DtpJtagInstr.BYPASS_3F)
    # A wider IR scan leaves the instruction unknown, but its last six bits
    # land in the register, so the TAP_3DCR write below is tracked.
    scan(True, int(DtpJtagInstr.TAP_3DCR) << 3, DTP_IR_WIDTH + 3)
    assert not model.ir_known()
    assert model.ptap_select_clear()
    scan(False, 0b110, 3)
    assert not model.ptap_select_clear(), "TAP_3DCR scan should set stap_sel"
    tlr()
    assert not model.ptap_select_clear(), "config_hold keeps the select through a TMS reset"
    model.on_event(OcahJtagEvent(kind="TRST", trst_n=0, trst_asserted=1))
    assert model.ptap_select_clear(), "TRST clears the 3DCR"
    tlr()
    scan(True, int(DtpJtagInstr.TAP_3DCR), DTP_IR_WIDTH)
    scan(False, 0b10, 2)
    assert not model.ptap_select_clear()
    tlr()
    assert model.ptap_select_clear(), "without config_hold a TMS reset clears the select"
    scan(True, int(DtpJtagInstr.TAP_3DCR), DTP_IR_WIDTH)
    scan(False, 0b11, 2)
    model.sync_power_on_reset(1)
    assert model.ptap_select_clear(), "power-on reset clears the 3DCR"
    tlr()
    scan(True, int(DtpJtagInstr.TAP_3DCR), DTP_IR_WIDTH)
    scan(False, 0b1, 1)
    assert not model.ptap_select_clear(), "a one-bit scan sets stap_sel"
    print("dtp_jtag_ir_model selftest: PASS")


if __name__ == "__main__":
    _selftest()
