# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_ptap_ir_walk_test - every PTAP instruction and every TAP state at the boundary.

S1: the four TAP controller states the other leaves pass through without
    stopping -- Pause-DR, Exit2-DR, Pause-IR and Exit2-IR (IEEE 1149.1) -- are
    each entered from Run-Test/Idle, and `jtag_ptap_state_o` carries that
    state's one-hot code (the OCAH/DTP encoding the JTAG VIP's state enum
    transcribes).
S2: all 64 six-bit IR encodings are shifted in turn. The PTAP's decoded
    instruction output is one-hot with one bit per encoding
    (`hw/ip/jtag/jtag_intf_unit/doc/interface.adoc`, "Instruction Encodings",
    the encodings without a row decoding as BYPASS functions of their own), so
    after each Update-IR `jtag_ptap_inst_decoded_o` carries exactly the bit of
    the encoding shifted. Test-Logic-Reset then loads IDCODE (IEEE 1149.1).

No DR is shifted after any of those instructions, so no test register,
boundary cell or bridge operation is updated.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState
from seq_lib.smu_jtag_helpers import DTP_IR_WIDTH, dtp_ir_opcode, make_smu_jtag_tap
from smu_base_test import smu_base_test

STATES = (
    OcahJtagState.PAUSE_DR,
    OcahJtagState.EXIT2_DR,
    OcahJtagState.PAUSE_IR,
    OcahJtagState.EXIT2_IR,
)
IDLE_TCKS = 4


def _sample(signal, name: str) -> int:
    val = signal.value
    if isinstance(val, int):
        return val
    if not val.is_resolvable:
        raise AssertionError(f"X/Z on {name}: {val}")
    return int(val)


@pyuvm.test()
class smu_dtp_ptap_ir_walk_test(smu_base_test):
    """Every PTAP IR encoding decodes to its own bit; every TAP state reaches the boundary."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        await ClockCycles(dut.clk_smu_i, 8)

        states = []
        for state in STATES:
            await jtag.goto_state(state)
            states.append(_sample(dut.jtag_ptap_state, "jtag_ptap_state"))
            await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        self.logger.info("CHK-PTAP-STATE-WALK " + " ".join(f"0x{s:04x}" for s in states))
        sb.expect_eq(
            "CHK-PTAP-STATE-WALK",
            states,
            [int(s) for s in STATES],
            evidence="CHK-PTAP-STATE-WALK",
        )

        wrong = []
        for opcode in range(1 << DTP_IR_WIDTH):
            await jtag.shift_ir(opcode, width=DTP_IR_WIDTH, back_to_rti=True)
            for _ in range(IDLE_TCKS):
                await jtag.step_tms(0)
            decoded = _sample(dut.tb_ptap_inst_decoded, "tb_ptap_inst_decoded")
            if decoded != 1 << opcode:
                wrong.append((opcode, decoded))
        await jtag.reset_tap()
        after_tlr = _sample(dut.tb_ptap_inst_decoded, "tb_ptap_inst_decoded")
        self.logger.info(
            f"CHK-PTAP-IR-DECODE-WALK 64 encodings, mismatches={wrong} after TLR=0x{after_tlr:x}"
        )
        sb.expect_eq(
            "CHK-PTAP-IR-DECODE-WALK",
            (wrong, after_tlr),
            ([], 1 << dtp_ir_opcode("IDCODE")),
            evidence="CHK-PTAP-IR-DECODE-WALK",
        )
