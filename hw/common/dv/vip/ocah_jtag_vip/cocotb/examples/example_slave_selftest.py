# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Slave-engine selftest: the reactive TAP device judged by the master model.

Runs standalone (``python example_slave_selftest.py``) with no simulator: a
minimal host emulation navigates the `OcahJtagSlaveEngine` with TMS paths
from the shared planner and compares every response against the master-side
predictions (`OcahJtagTapRefModel`, `predict_bypass_tdo`). Named `CHK-*`
evidence goes through `OcahJtagChecker`, so a failure is a hard error.

Covered contracts:
  * Test-Logic-Reset selects the device-identification register
  * IDCODE reads back the configured value with the marker bit set
  * BYPASS delays TDI to TDO by exactly one TCK
  * unimplemented instructions behave as BYPASS
  * writable registers latch on Update-DR (recorded), read-only ones do not
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ocah_jtag_vip import (  # noqa: E402
    OcahJtagChecker,
    OcahJtagDevice,
    OcahJtagState,
    OcahJtagTapRefModel,
    jtag_tms_path,
)
from ocah_jtag_vip.cocotb.ocah_jtag_slave_driver import (  # noqa: E402
    OcahJtagSlaveEngine,
)

IR_WIDTH = 5
IDCODE = 0x1B34_C0D1  # marker bit[0] = 1
CTRL_OPCODE = 0x02
STATUS_OPCODE = 0x03
UNUSED_OPCODE = 0x0A


class EngineHost:
    """Minimal host: replays master-driver cycles against the engine."""

    def __init__(self, engine: OcahJtagSlaveEngine) -> None:
        self.engine = engine
        self.model = OcahJtagTapRefModel(name="selftest.model")
        self._tdo = 0  # value presented on the current low phase

    def cycle(self, tms: int, tdi: int = 0) -> int:
        """One TCK cycle; returns TDO as the master would sample it."""
        sampled = self._tdo
        self.engine.clock_rise(tms, tdi)
        self.model.step(tms)
        self._tdo, _oen = self.engine.clock_fall()
        return sampled

    def goto(self, state: OcahJtagState) -> None:
        for tms in jtag_tms_path(self.model.state, state):
            self.cycle(tms)

    def reset_to_tlr(self) -> None:
        for _ in range(5):
            self.cycle(1)
        self.model.reset()

    def shift(self, value: int, width: int, *, sel_ir: bool) -> int:
        """Full scan from Run-Test/Idle back to Run-Test/Idle, LSB-first."""
        self.goto(OcahJtagState.SHIFT_IR if sel_ir else OcahJtagState.SHIFT_DR)
        captured = 0
        for i in range(width):
            tdo = self.cycle(1 if i == width - 1 else 0, (value >> i) & 1)
            captured |= (tdo & 1) << i
        self.cycle(1)  # Exit1 -> Update
        self.cycle(0)  # Update -> Run-Test/Idle
        return captured


def main() -> None:
    device = OcahJtagDevice.from_registers(
        name="selftest_device",
        idcode=IDCODE,
        ir_width=IR_WIDTH,
        registers={
            "IDCODE": (32, 0x01),
            "CTRL": (16, CTRL_OPCODE, True),
            "STATUS": (8, STATUS_OPCODE),
        },
    )
    engine = OcahJtagSlaveEngine(device, name="selftest.engine")
    host = EngineHost(engine)
    checker = OcahJtagChecker(
        name="slave_selftest",
        required_ids=(
            "CHK-SLAVE-TLR-IDCODE",
            "CHK-SLAVE-IDCODE-MARKER",
            "CHK-SLAVE-BYPASS-LATENCY",
            "CHK-SLAVE-UNDEF-AS-BYPASS",
            "CHK-SLAVE-DR-UPDATE",
            "CHK-SLAVE-RO-NO-UPDATE",
            "CHK-SLAVE-STATUS-CAPTURE",
        ),
    )

    # TLR selects IDCODE: DR scan with no IR load returns the identification
    # value, marker bit set.
    host.reset_to_tlr()
    host.cycle(0)  # TLR -> RTI
    observed = host.shift(0, 32, sel_ir=False)
    checker.expect_equal(
        "CHK-SLAVE-TLR-IDCODE", observed, IDCODE, context="DR scan after TLR, no IR load"
    )
    checker.expect_equal(
        "CHK-SLAVE-IDCODE-MARKER", observed & 1, 1, context=f"raw=0x{observed:08x}"
    )

    # BYPASS: exactly one TCK of TDI-to-TDO delay.
    bypass_opcode = (1 << IR_WIDTH) - 1
    pattern = 0xA5A5_5A5A_C3C3_3C3C
    host.shift(bypass_opcode, IR_WIDTH, sel_ir=True)
    observed = host.shift(pattern, 64, sel_ir=False)
    checker.check_bypass_latency(
        observed, pattern=pattern, width=64, check_id="CHK-SLAVE-BYPASS-LATENCY"
    )

    # An unimplemented instruction behaves as BYPASS.
    host.shift(UNUSED_OPCODE, IR_WIDTH, sel_ir=True)
    observed = host.shift(pattern, 64, sel_ir=False)
    expected = OcahJtagTapRefModel.predict_bypass_tdo(pattern, 64)
    checker.expect_equal(
        "CHK-SLAVE-UNDEF-AS-BYPASS", observed, expected, context=f"ir=0x{UNUSED_OPCODE:02x}"
    )

    # Writable register: the host write latches on Update-DR and is recorded.
    host.shift(CTRL_OPCODE, IR_WIDTH, sel_ir=True)
    host.shift(0xBEEF, 16, sel_ir=False)
    updates = [u for u in engine.updates if u.reg_name == "CTRL"]
    checker.expect_equal(
        "CHK-SLAVE-DR-UPDATE",
        updates[-1].value if updates else -1,
        0xBEEF,
        context=f"updates={len(updates)}",
    )
    observed = host.shift(0, 16, sel_ir=False)
    checker.expect_equal(
        "CHK-SLAVE-DR-UPDATE", observed, 0xBEEF, context="readback after Update-DR"
    )

    # Read-only register: captures the backdoor value, never latches.
    engine.set_register("STATUS", 0xA5)
    host.shift(STATUS_OPCODE, IR_WIDTH, sel_ir=True)
    observed = host.shift(0xFF, 8, sel_ir=False)
    checker.expect_equal("CHK-SLAVE-STATUS-CAPTURE", observed, 0xA5, context="read-only capture")
    checker.expect_equal(
        "CHK-SLAVE-RO-NO-UPDATE",
        len([u for u in engine.updates if u.reg_name == "STATUS"]),
        0,
        context="read-only register must not latch",
    )
    checker.expect_equal(
        "CHK-SLAVE-STATUS-CAPTURE",
        engine.get_register("STATUS"),
        0xA5,
        context="stored value survives the host write",
    )

    # TLR re-selects IDCODE after arbitrary instruction churn.
    host.reset_to_tlr()
    host.cycle(0)
    observed = host.shift(0, 32, sel_ir=False)
    checker.expect_equal(
        "CHK-SLAVE-TLR-IDCODE", observed, IDCODE, context="TLR re-selects IDCODE after IR churn"
    )

    checker.finalize()
    print("SLAVE SELFTEST PASS")


if __name__ == "__main__":
    main()
