# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target ACK Control Mode: software decides byte by byte.

`i2c.rdl` describes `CTRL.ACK_CTRL_EN` as making the target ACK only the first
`TARGET_ACK_CTRL.NBYTES` bytes. When another byte arrives the target stretches
the clock, raises `STATUS.ACK_CTRL_STRETCH`, and waits for software either to
accept the new bytes by reloading the counter or to reject them by writing
`TARGET_ACK_CTRL.NACK`. It is the mechanism behind SMBus's mid-transfer
responses.

Both are given here, on transfers whose acquisition FIFO has room throughout:
the hold is the ACK counter's doing, and `STATUS.ACQFULL` is required to be
clear while it lasts so it cannot be read as the FIFO-full stretch that
`smc_i2c_target_acq_stretch_test` already covers.

The counter is a counter, not a flag. `NBYTES` is reloaded with fewer bytes
than remain, so the target stretches a second time after consuming exactly
that many, which is what shows the count decrementing per byte rather than
simply enabling the rest of the transfer.

`TARGET_ACK_CTRL.NBYTES` is writable only while the target is stretching for
this reason (`i2c_core.sv` gates its write enable on that condition), so each
reload is also a check that the gate is open when the register documentation
says it is.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NACK_DATA,
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_CTRL_ACK_CTRL_EN,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACK_CTRL_STRETCH,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_ACQFULL,
    I2C_TARGET_ACK_CTRL_NACK,
    I2C_TARGET_ACK_CTRL_NBYTES_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
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
TARGET_ADDR = 0x24
VIP_SPEED = 2_000_000

#: Accepted in two reloads of this many bytes each, so the second stretch
#: proves the count decrements per byte.
ACCEPT_CHUNK = 2
ACCEPT_PAYLOAD = bytes((0x50 + i) & 0xFF for i in range(2 * ACCEPT_CHUNK))
REJECT_PAYLOAD = bytes((0x60 + i) & 0xFF for i in range(3))

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
I2C0_WRAP_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", I2C0)
I2C0_OVRD = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", I2C0)
I2C0_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", I2C0)
I2C0_STATUS = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", I2C0)
I2C0_FIFO_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", I2C0)
I2C0_TARGET_ID = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", I2C0)
I2C0_TARGET_ACK_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ACK_CTRL_BASE_ADDR", I2C0)
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
STRETCH_POLLS = 4000
FINISH_POLLS = 4000


class smc_i2c_target_ack_ctrl_test_seq(SmcCsrSeq):
    """Accept and reject bytes through TARGET_ACK_CTRL while the target holds."""

    def __init__(self, name: str = "smc_i2c_target_ack_ctrl_test_seq") -> None:
        super().__init__(name)
        self.accepted: list[tuple[int, int]] = []
        self.rejected: list[tuple[int, int]] = []
        self.accept_acks: list[int] = []
        self.reject_acks: list[int] = []
        self.stretch_rounds = 0

    async def _pop_all(self, into: list[tuple[int, int]]) -> int:
        fifo = await self.csr_read("I2C0_TARGET_FIFO_STATUS", I2C0_TARGET_FIFO_STATUS)
        level = (fifo & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP
        for _ in range(level):
            word = await self.csr_read("I2C0_ACQDATA", I2C0_ACQDATA)
            into.append(((word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP, word & _ABYTE_BM))
        return level

    async def _bring_up(self, label: str) -> None:
        await self.csr_write(f"I2C0_DISABLE_{label}", I2C0_CTRL, 0)
        await self.csr_write("I2C0_WRAP_TARGET", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready(f"I2C0_ACK_CTRL_{label}")
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
        await self.csr_write(
            f"I2C0_CTRL_{label}",
            I2C0_CTRL,
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACK_CTRL_EN | I2C_CTRL_ACQ_START_STOP_EN,
        )
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        ctrl = await self.csr_read(f"I2C0_CTRL_{label}_RB", I2C0_CTRL)
        assert ctrl & I2C_CTRL_ACK_CTRL_EN, (
            f"{label}: CTRL.ACK_CTRL_EN did not take (CTRL=0x{ctrl:08x}); ACK Control Mode is "
            f"what the leg under test depends on"
        )
        status = await self.csr_read(f"I2C0_STATUS_{label}_ENTRY", I2C0_STATUS)
        assert status & I2C_STATUS_ACQEMPTY, (
            f"{label}: the acquisition FIFO is not empty before the leg starts "
            f"(STATUS=0x{status:08x})"
        )
        assert not status & I2C_STATUS_ACK_CTRL_STRETCH, (
            f"{label}: STATUS.ACK_CTRL_STRETCH is set before any transfer (STATUS=0x{status:08x})"
        )

    @staticmethod
    async def _transfer(master: SmcI2cMasterVip, payload: bytes, acks: list[int]) -> None:
        """Address plus payload, recording every ACK bit, then a STOP."""
        await master.send_start()
        acks.append(await master.send_byte((TARGET_ADDR & 0x7F) << 1))
        for value in payload:
            acks.append(await master.send_byte(value))
        await master.send_stop()

    async def _await_ack_ctrl_stretch(self, label: str, task) -> int:
        """Bounded wait for the ACK-control hold, with the FIFO proven to have room."""
        status = 0
        for _ in range(STRETCH_POLLS):
            status = await self.csr_read(f"I2C0_STATUS_{label}", I2C0_STATUS)
            if status & I2C_STATUS_ACK_CTRL_STRETCH:
                assert not status & I2C_STATUS_ACQFULL, (
                    f"{label}: STATUS.ACQFULL is set alongside ACK_CTRL_STRETCH "
                    f"(0x{status:08x}); the hold under test is the ACK counter's, not the "
                    f"acquisition FIFO's"
                )
                return status
            if task.done():
                seen: list[tuple[int, int]] = []
                await self._pop_all(seen)
                raise AssertionError(
                    f"{label}: the transfer completed without the target ever setting "
                    f"STATUS.ACK_CTRL_STRETCH (last 0x{status:08x}), so ACK Control Mode never "
                    f"held anything (acquired {seen})"
                )
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(f"{label}: STATUS.ACK_CTRL_STRETCH never set (last 0x{status:08x})")

    async def _accept_leg(self) -> None:
        await self._bring_up("ACCEPT")
        master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_ack_ctrl_accept")
        task = cocotb.start_soon(self._transfer(master, ACCEPT_PAYLOAD, self.accept_acks))

        # NBYTES resets to 0, so the target holds at the first data byte and
        # each reload covers exactly ACCEPT_CHUNK more. A payload of several
        # chunks therefore has to stop the target once per chunk.
        expected_rounds = len(ACCEPT_PAYLOAD) // ACCEPT_CHUNK
        for _ in range(expected_rounds):
            await self._await_ack_ctrl_stretch("ACCEPT", task)
            self.stretch_rounds += 1
            await self.csr_write("I2C0_ACK_CTRL_NBYTES", I2C0_TARGET_ACK_CTRL, ACCEPT_CHUNK)
            read = await self.csr_read("I2C0_ACK_CTRL_NBYTES_RB", I2C0_TARGET_ACK_CTRL)
            assert read & I2C_TARGET_ACK_CTRL_NBYTES_BM, (
                f"ACCEPT: TARGET_ACK_CTRL.NBYTES reads 0 straight after {ACCEPT_CHUNK} was "
                f"written while the target was stretching (0x{read:08x}); the write enable is "
                f"open in exactly this condition"
            )
            for _ in range(FINISH_POLLS):
                status = await self.csr_read("I2C0_STATUS_ACCEPT_RUN", I2C0_STATUS)
                if task.done() or not status & I2C_STATUS_ACK_CTRL_STRETCH:
                    break
                await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            else:
                raise AssertionError(
                    f"ACCEPT: the target kept stretching after NBYTES was reloaded with "
                    f"{ACCEPT_CHUNK}"
                )

        # The payload is spent, so the rest of the transfer must run out
        # without another hold.
        for _ in range(FINISH_POLLS):
            if task.done():
                break
            status = await self.csr_read("I2C0_STATUS_ACCEPT_END", I2C0_STATUS)
            assert not status & I2C_STATUS_ACK_CTRL_STRETCH, (
                f"ACCEPT: the target stretched again after {self.stretch_rounds} reloads of "
                f"{ACCEPT_CHUNK} covered the whole {len(ACCEPT_PAYLOAD)}-byte payload "
                f"(STATUS=0x{status:08x})"
            )
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"ACCEPT: the transfer never finished after {expected_rounds} reloads covered "
                f"every payload byte"
            )
        task.result()

        await self._pop_all(self.accepted)
        assert all(a == 0 for a in self.accept_acks), (
            f"ACCEPT: the target NACKed part of the transfer (ACK bits {self.accept_acks}) "
            f"although every byte was accepted through TARGET_ACK_CTRL.NBYTES"
        )
        wanted = (
            [(I2C_ACQ_SIGNAL_START, (TARGET_ADDR & 0x7F) << 1)]
            + [(I2C_ACQ_SIGNAL_NONE, v) for v in ACCEPT_PAYLOAD]
            + [(I2C_ACQ_SIGNAL_STOP, self.accepted[-1][1] if self.accepted else 0)]
        )
        assert [e[0] for e in self.accepted] == [e[0] for e in wanted], (
            f"ACCEPT: the acquired signals do not match the transfer: {self.accepted}"
        )
        assert [e[1] for e in self.accepted[:-1]] == [e[1] for e in wanted[:-1]], (
            f"ACCEPT: the acquired bytes do not match the transfer: {self.accepted}"
        )
        assert self.stretch_rounds == len(ACCEPT_PAYLOAD) // ACCEPT_CHUNK, (
            f"ACCEPT: the target stretched {self.stretch_rounds} times for "
            f"{len(ACCEPT_PAYLOAD)} bytes reloaded {ACCEPT_CHUNK} at a time, not the "
            f"{len(ACCEPT_PAYLOAD) // ACCEPT_CHUNK} a counter that decrements per byte "
            f"would give"
        )
        cocotb.log.info(
            "CHK-I2C-TGT-ACK-CTRL-ACCEPT: with ACK Control Mode enabled and the acquisition "
            "FIFO proven to have room, the target held the bus %d times -- once per %d bytes "
            "of the %d-byte payload -- and each reload of TARGET_ACK_CTRL.NBYTES released it "
            "for exactly that many more. Every byte was acknowledged and acquired in order",
            self.stretch_rounds,
            ACCEPT_CHUNK,
            len(ACCEPT_PAYLOAD),
        )

    async def _reject_leg(self) -> None:
        await self._bring_up("REJECT")
        master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_ack_ctrl_reject")
        task = cocotb.start_soon(self._transfer(master, REJECT_PAYLOAD, self.reject_acks))

        await self._await_ack_ctrl_stretch("REJECT", task)
        await self.csr_write("I2C0_ACK_CTRL_NACK", I2C0_TARGET_ACK_CTRL, I2C_TARGET_ACK_CTRL_NACK)
        for _ in range(FINISH_POLLS):
            if task.done():
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                "REJECT: the transfer never finished after TARGET_ACK_CTRL.NACK was written "
                "while the target was stretching"
            )
        task.result()

        await self._pop_all(self.rejected)
        assert self.reject_acks[0] == 0, (
            f"REJECT: the target NACKed its own address (ACK bits {self.reject_acks})"
        )
        assert any(a == 1 for a in self.reject_acks[1:]), (
            f"REJECT: every byte was acknowledged although TARGET_ACK_CTRL.NACK was written "
            f"while the target was stretching (ACK bits {self.reject_acks})"
        )
        nacked = [e for e in self.rejected if e[0] == I2C_ACQ_SIGNAL_NACK_DATA]
        assert nacked, (
            f"REJECT: no NACKed-data entry reached the acquisition FIFO, so software cannot "
            f"tell which byte it rejected (acquired {self.rejected})"
        )
        cocotb.log.info(
            "CHK-I2C-TGT-ACK-CTRL-NACK: writing TARGET_ACK_CTRL.NACK while the target held the "
            "bus made it reject the transfer: the bench saw NACKs from that byte on (ACK bits "
            "%s) and the acquisition FIFO recorded %d NACKed-data entr%s so software can tell "
            "which byte was refused",
            self.reject_acks,
            len(nacked),
            "y" if len(nacked) == 1 else "ies",
        )

    async def body(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self._accept_leg()
        await self._reject_leg()
