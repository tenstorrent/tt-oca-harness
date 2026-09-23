# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target gives up on a stretch it is not released from.

`TARGET_TIMEOUT_CTRL` is the cumulative limit on how long this target may
stretch within one transaction. `i2c.rdl` states the consequence: past that
limit the target "will NACK incoming data bytes or release the SDA line for
outgoing data bytes". Every stretch leaf so far is released by software before
any limit applies, so the expiry had never been reached.

Both halves of that sentence are driven, one per direction, with the limit set
short enough that nothing has to wait for it:

* **Incoming.** ACK Control Mode is used to stop the target at the first data
  byte without filling the acquisition FIFO first, which is the same hold
  `smc_i2c_target_ack_ctrl_test` answers -- except that nothing answers it
  here, so the limit expires and the byte is NACKed.
* **Outgoing.** A read from an empty transmit FIFO leaves the target with
  nothing to send, so it holds the clock; the limit expires and it releases
  SDA, which the bench reads as all ones.

`TARGET_NACK_COUNT` is the register witness for both. `i2c_core.sv` increments
it on the edge where the target decides to NACK the transaction, and the field
is read-to-clear, so each leg reads it clear beforehand and requires exactly
one afterwards. The acquisition FIFO carries the other half: the NACK-stop
entry the target appends so software can see the transaction ended badly.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_ERROR,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_CTRL_ACK_CTRL_EN,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
    I2C_TARGET_TIMEOUT_CTRL_EN,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

I2C0 = 0
TARGET_ADDR = 0x25
VIP_SPEED = 2_000_000

#: Cumulative stretch allowance, in the target's own clock periods. Short
#: enough that the limit is reached within one held byte.
NACK_TIMEOUT_CYCLES = 64
WRITE_PAYLOAD = bytes((0x70 + i) & 0xFF for i in range(2))
READ_BYTES = 2
NACK_COUNT_BM = 0xFF

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
I2C0_WRAP_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", I2C0)
I2C0_OVRD = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", I2C0)
I2C0_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", I2C0)
I2C0_STATUS = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", I2C0)
I2C0_FIFO_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", I2C0)
I2C0_TARGET_ID = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", I2C0)
I2C0_TARGET_TIMEOUT_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_TIMEOUT_CTRL_BASE_ADDR", I2C0
)
I2C0_TARGET_NACK_COUNT = smc_indexed_addr(
    "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_NACK_COUNT_BASE_ADDR", I2C0
)
I2C0_TARGET_FIFO_STATUS = smc_indexed_addr(
    "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR", I2C0
)
I2C0_ACQDATA = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR", I2C0)
I2C0_TIMING0 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR", I2C0)
I2C0_TIMING1 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR", I2C0)
I2C0_TIMING2 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR", I2C0)
I2C0_TIMING3 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR", I2C0)
I2C0_TIMING4 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR", I2C0)

_ABYTE_BM = 0xFF
POLL_CYCLES = 100
FINISH_POLLS = 4000


class smc_i2c_target_nack_timeout_test_seq(SmcCsrSeq):
    """A stretch nobody releases must end in the target's own NACK."""

    def __init__(self, name: str = "smc_i2c_target_nack_timeout_test_seq") -> None:
        super().__init__(name)
        self.write_entries: list[tuple[int, int]] = []
        self.read_entries: list[tuple[int, int]] = []
        self.write_acks: list[int] = []
        self.read_data = b""

    async def _pop_all(self, into: list[tuple[int, int]]) -> None:
        fifo = await self.csr_read("I2C0_TARGET_FIFO_STATUS", I2C0_TARGET_FIFO_STATUS)
        level = (fifo & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP
        for _ in range(level):
            word = await self.csr_read("I2C0_ACQDATA", I2C0_ACQDATA)
            into.append(((word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP, word & _ABYTE_BM))

    async def _bring_up(self, label: str, ack_ctrl: bool) -> None:
        ctrl = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
        if ack_ctrl:
            ctrl |= I2C_CTRL_ACK_CTRL_EN
        await self.csr_write(f"I2C0_DISABLE_{label}", I2C0_CTRL, 0)
        await self.csr_write("I2C0_WRAP_TARGET", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready(f"I2C0_NACK_TIMEOUT_{label}")
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, 0)
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write(
            "I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST
        )
        await self.csr_write(
            "I2C0_TARGET_ID", I2C0_TARGET_ID, _pack_target_id(TARGET_ADDR, 0x7F, 0, 0)
        )
        timeout = I2C_TARGET_TIMEOUT_CTRL_EN | NACK_TIMEOUT_CYCLES
        await self.csr_write(f"I2C0_TARGET_TIMEOUT_{label}", I2C0_TARGET_TIMEOUT_CTRL, timeout)
        await self.csr_read(
            f"I2C0_TARGET_TIMEOUT_{label}_RB", I2C0_TARGET_TIMEOUT_CTRL, expected=timeout
        )
        await self.csr_write(f"I2C0_CTRL_{label}", I2C0_CTRL, ctrl)
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        status = await self.csr_read(f"I2C0_STATUS_{label}_ENTRY", I2C0_STATUS)
        assert status & I2C_STATUS_ACQEMPTY, (
            f"{label}: the acquisition FIFO is not empty before the leg starts "
            f"(STATUS=0x{status:08x})"
        )
        # Read-to-clear, so this both reports and resets the counter the leg
        # measures.
        count = await self.csr_read(f"I2C0_NACK_COUNT_{label}_CLEAR", I2C0_TARGET_NACK_COUNT)
        again = await self.csr_read(f"I2C0_NACK_COUNT_{label}_ENTRY", I2C0_TARGET_NACK_COUNT)
        assert again & NACK_COUNT_BM == 0, (
            f"{label}: TARGET_NACK_COUNT reads {again & NACK_COUNT_BM} straight after a read "
            f"cleared it from {count & NACK_COUNT_BM}; the leg cannot then attribute a count "
            f"to its own transaction"
        )

    async def _await_task(self, label: str, task) -> None:
        for _ in range(FINISH_POLLS):
            if task.done():
                task.result()
                return
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(
            f"{label}: the transfer never finished, so the target never gave up on its stretch"
        )

    async def _incoming_leg(self) -> None:
        await self._bring_up("INCOMING", ack_ctrl=True)
        master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_nack_timeout_write")

        async def run() -> None:
            await master.send_start()
            self.write_acks.append(await master.send_byte((TARGET_ADDR & 0x7F) << 1))
            for value in WRITE_PAYLOAD:
                self.write_acks.append(await master.send_byte(value))
            await master.send_stop()

        task = cocotb.start_soon(run())
        await self._await_task("INCOMING", task)
        await self._pop_all(self.write_entries)
        count = (
            await self.csr_read("I2C0_NACK_COUNT_INCOMING", I2C0_TARGET_NACK_COUNT)
        ) & NACK_COUNT_BM

        assert self.write_acks[0] == 0, (
            f"INCOMING: the target NACKed its own address (ACK bits {self.write_acks})"
        )
        assert any(a == 1 for a in self.write_acks[1:]), (
            f"INCOMING: every data byte was acknowledged although the target was left holding "
            f"the bus past its {NACK_TIMEOUT_CYCLES}-cycle allowance (ACK bits "
            f"{self.write_acks})"
        )
        assert count == 1, (
            f"INCOMING: TARGET_NACK_COUNT reads {count} after one transaction the target gave "
            f"up on; the counter takes the edge on which the target decides to NACK"
        )
        assert self.write_entries and self.write_entries[-1][0] == I2C_ACQ_SIGNAL_ERROR, (
            f"INCOMING: the acquisition FIFO does not end with the NACK-stop entry that tells "
            f"software the transaction ended badly (acquired {self.write_entries})"
        )
        cocotb.log.info(
            "CHK-I2C-TGT-NACK-TIMEOUT-RX: held at a data byte with nothing to release it, the "
            "target ran out its %d-cycle allowance and NACKed the incoming byte (ACK bits %s), "
            "counted the transaction once in TARGET_NACK_COUNT and closed the acquisition "
            "stream with a NACK-stop entry (%s)",
            NACK_TIMEOUT_CYCLES,
            self.write_acks,
            self.write_entries,
        )

    async def _outgoing_leg(self) -> None:
        await self._bring_up("OUTGOING", ack_ctrl=False)
        master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_nack_timeout_read")

        async def run() -> None:
            self.read_data = await master.read(TARGET_ADDR, READ_BYTES)

        task = cocotb.start_soon(run())
        await self._await_task("OUTGOING", task)
        await self._pop_all(self.read_entries)
        count = (
            await self.csr_read("I2C0_NACK_COUNT_OUTGOING", I2C0_TARGET_NACK_COUNT)
        ) & NACK_COUNT_BM

        assert self.read_data == bytes([0xFF] * READ_BYTES), (
            f"OUTGOING: the bench read {self.read_data!r} from a target whose transmit FIFO "
            f"was empty for longer than its allowance; a released SDA line reads as all ones"
        )
        assert count == 1, (
            f"OUTGOING: TARGET_NACK_COUNT reads {count} after one read the target gave up on"
        )
        assert self.read_entries and self.read_entries[-1][0] == I2C_ACQ_SIGNAL_ERROR, (
            f"OUTGOING: the acquisition FIFO does not end with the NACK-stop entry "
            f"(acquired {self.read_entries})"
        )
        cocotb.log.info(
            "CHK-I2C-TGT-NACK-TIMEOUT-TX: asked to transmit with an empty transmit FIFO, the "
            "target held the clock, ran out its %d-cycle allowance and released SDA, so the "
            "bench read %s; the transaction was counted once in TARGET_NACK_COUNT and the "
            "acquisition stream ends with a NACK-stop entry (%s)",
            NACK_TIMEOUT_CYCLES,
            self.read_data.hex(),
            self.read_entries,
        )

    async def body(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self._incoming_leg()
        await self._outgoing_leg()
