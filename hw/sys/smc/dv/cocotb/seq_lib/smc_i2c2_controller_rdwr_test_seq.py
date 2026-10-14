# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C2 as the bus controller: a write and a two-byte read against I2C1.

This leaf makes instance 2 the controller, so its `i2c_controller_fsm` passes
through the acknowledge and read phases.

`+smc_i2c_shared_bus` puts the three instances on one open-drain bus, so making
I2C2 the controller is a matter of which instance gets `CTRL.ENABLEHOST`. I2C1
is the target for both legs, and each leg is checked at the far end: the write
against the bytes the target acquired, the read against the bytes the target
was told to source.

The read asks for two bytes rather than one. A controller that reads a single
byte only ever NACKs it, so the acknowledge phase is only entered when a byte
is followed by another one.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_CONTROLLER_EVENTS_NACK,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_HOSTIDLE,
    I2C_STATUS_RXEMPTY,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
    acq_abyte,
    acq_signal,
)
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

INSTANCES = (0, 1, 2)
HOST = 2
TARGET = 1
TARGET_ADDR = 0x36
WRITE_PAYLOAD = (0xC3, 0x3C, 0x5A)
# Two bytes, so the controller acknowledges the first and only NACKs the last.
READ_BYTES = (0x9E, 0x71)

# Bounds on the DUT-side observations, in clk_smc_i cycles so they scale with
# the randomised clock. Expiry is a failure, never a pass.
POLL_CYCLES = 200
POLL_LIMIT = 400
DRAIN_LIMIT = 400


class smc_i2c2_controller_rdwr_test_seq(SmcCsrSeq):
    """Drive a controller write and a controller read from I2C2."""

    def __init__(self, name: str = "smc_i2c2_controller_rdwr_test_seq") -> None:
        super().__init__(name)
        self.acquired: list[int] = []
        self.read_bytes: list[int] = []

    @staticmethod
    def _addr(symbol: str, idx: int) -> int:
        return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{symbol}_BASE_ADDR", idx)

    @staticmethod
    def _wrap_addr(idx: int) -> int:
        return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)

    async def _program_timing(self, idx: int) -> None:
        for reg, value in (
            ("TIMING0", _pack_timing0(0x1A, 0x32)),
            ("TIMING1", _pack_timing1(2, 2)),
            ("TIMING2", _pack_timing2(5, 4)),
            ("TIMING3", _pack_timing3(2, 5)),
            ("TIMING4", _pack_timing4(4, 5)),
        ):
            await self.csr_write(f"I2C{idx}_{reg}", self._addr(reg, idx), value)

    async def _disconnect_all(self) -> None:
        for idx in INSTANCES:
            await self.csr_write(f"I2C{idx}_WRAP_OFF", self._wrap_addr(idx), 0)
            await self.csr_write(f"I2C{idx}_CTRL_OFF", self._addr("CTRL", idx), 0)

    async def _bring_up(self) -> None:
        await self._disconnect_all()
        await self.csr_write("TGT_WRAP", self._wrap_addr(TARGET), I2C_WRAP_CTRL_TARGET)
        await self._program_timing(TARGET)
        await self.csr_write(
            "TGT_ID", self._addr("TARGET_ID", TARGET), _pack_target_id(TARGET_ADDR, 0x7F, 0, 0)
        )
        await self.csr_write(
            "TGT_FIFO",
            self._addr("FIFO_CTRL", TARGET),
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_ACQRST,
        )
        await self.csr_write(
            "TGT_CTRL",
            self._addr("CTRL", TARGET),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

        await self.csr_write("HOST_WRAP", self._wrap_addr(HOST), I2C_WRAP_CTRL_HOST)
        await self._program_timing(HOST)
        await self.csr_write("HOST_OVRD", self._addr("OVRD", HOST), 0)
        await self.csr_write("HOST_FIFO", self._addr("FIFO_CTRL", HOST), I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write(
            "HOST_CEVENTS", self._addr("CONTROLLER_EVENTS", HOST), I2C_CONTROLLER_EVENTS_ALL
        )
        await self.csr_write("HOST_CTRL", self._addr("CTRL", HOST), I2C_CTRL_ENABLEHOST)

    async def _wait_hostidle(self, label: str) -> int:
        status_addr = self._addr("STATUS", HOST)
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_IDLE", status_addr)
            if status & I2C_STATUS_HOSTIDLE and status & I2C_STATUS_FMTEMPTY:
                return status
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(
            f"{label}: controller I2C{HOST} never returned idle with its format FIFO drained "
            f"(STATUS=0x{status:08x})"
        )

    async def _drain_acq(self, label: str) -> list[int]:
        status_addr = self._addr("STATUS", TARGET)
        acq_addr = self._addr("ACQDATA", TARGET)
        words: list[int] = []
        for _ in range(DRAIN_LIMIT):
            status = await self.csr_read(f"{label}_ACQ_STATUS", status_addr)
            if status & I2C_STATUS_ACQEMPTY:
                return words
            words.append(int(await self.csr_read(f"{label}_ACQDATA", acq_addr)) & 0xFFFF)
        raise AssertionError(f"{label}: target I2C{TARGET} acquisition FIFO never drained")

    async def _write_leg(self) -> None:
        fdata = self._addr("FDATA", HOST)
        addr_w = (TARGET_ADDR << 1) | 0
        await self.csr_write("WR_FDATA_START", fdata, I2C_FDATA_START | addr_w)
        for i, byte in enumerate(WRITE_PAYLOAD[:-1]):
            await self.csr_write(f"WR_FDATA_{i}", fdata, byte)
        await self.csr_write("WR_FDATA_STOP", fdata, I2C_FDATA_STOP | WRITE_PAYLOAD[-1])
        await self._wait_hostidle("WR")

        words = await self._drain_acq("WR")
        self.acquired = words
        data = [acq_abyte(w) for w in words if acq_signal(w) == I2C_ACQ_SIGNAL_NONE]
        assert data == list(WRITE_PAYLOAD), (
            f"target I2C{TARGET} acquired {[hex(b) for b in data]} for the "
            f"{[hex(b) for b in WRITE_PAYLOAD]} controller I2C{HOST} wrote"
        )
        events = await self.csr_read("WR_CEVENTS", self._addr("CONTROLLER_EVENTS", HOST))
        assert not events & I2C_CONTROLLER_EVENTS_NACK, (
            f"controller I2C{HOST} reported a NACK writing to a target that is programmed to "
            f"match address 0x{TARGET_ADDR:02x} (CONTROLLER_EVENTS=0x{events:08x})"
        )
        cocotb.log.info(
            "CHK-I2C2-CTRL-WRITE: controller I2C%d drove the bus and target I2C%d acquired "
            "%s in order, with no NACK reported",
            HOST,
            TARGET,
            [f"0x{b:02x}" for b in data],
        )

    async def _read_leg(self) -> None:
        for i, byte in enumerate(READ_BYTES):
            await self.csr_write(f"TGT_TXDATA_{i}", self._addr("TXDATA", TARGET), byte)
        fdata = self._addr("FDATA", HOST)
        addr_r = (TARGET_ADDR << 1) | 1
        await self.csr_write("RD_FDATA_START", fdata, I2C_FDATA_START | addr_r)
        await self.csr_write(
            "RD_FDATA_READB", fdata, I2C_FDATA_READB | I2C_FDATA_STOP | len(READ_BYTES)
        )

        status_addr = self._addr("STATUS", HOST)
        rdata_addr = self._addr("RDATA", HOST)
        got: list[int] = []
        for _ in range(POLL_LIMIT):
            if len(got) == len(READ_BYTES):
                break
            status = await self.csr_read("RD_HOST_STATUS", status_addr)
            if not status & I2C_STATUS_RXEMPTY:
                got.append(int(await self.csr_read("RD_RDATA", rdata_addr)) & 0xFF)
                continue
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        self.read_bytes = got
        assert got == list(READ_BYTES), (
            f"controller I2C{HOST} read {[hex(b) for b in got]} from target I2C{TARGET}, "
            f"expected the {[hex(b) for b in READ_BYTES]} written to its TXDATA"
        )
        await self._wait_hostidle("RD")
        cocotb.log.info(
            "CHK-I2C2-CTRL-READ: controller I2C%d clocked %d bytes out of target I2C%d and "
            "read back %s, acknowledging every byte but the last, then returned idle",
            HOST,
            len(got),
            TARGET,
            [f"0x{b:02x}" for b in got],
        )

    async def body(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "smc_i2c2_controller_rdwr_test needs +smc_i2c_shared_bus; without it I2C1 and "
            "I2C2 are not on the same bus"
        )
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for idx in INSTANCES:
            await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_LSIO")
        await self.wait_i2c_bus_released("I2C_SHARED_BUS")

        await self._bring_up()
        await self._write_leg()
        await self._read_leg()
        await self._disconnect_all()
