# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target-mode line loopback, against a transmit FIFO that is already full.

`i2c.rdl` describes `CTRL.LLPBK` in target mode as a target that "sends all
received SDA data back out": what an external controller writes to it comes
back on the next read. No leaf had set it with the target enabled.

The loopback is driven against back-pressure. The transmit FIFO's depth is
measured by filling it through `TXDATA` until `STATUS.TXFULL` sets; it is then
reset and loaded with one entry fewer, `LLPBK` is set with
`ACQ_START_STOP_EN`, so the START and STOP are acquisition entries too, and a
two-byte write is made to the target. The first written byte takes the last free entry; the
second has nowhere to go and must wait in the acquisition FIFO, with the STOP
entry behind it, while the START entry with the address, which carries no
payload, must not wait. `TARGET_FIFO_STATUS.ACQLVL` shows exactly those two.

A read cannot unblock it: the target holds a read until the acquisition FIFO
is empty, and the acquisition FIFO cannot empty into a full transmit FIFO.
Software breaks the tie by reading `ACQDATA`, which must return the waiting
byte as a data entry; the STOP entry behind it then leaves on its own. A read
of the whole transmit FIFO has to return the bytes loaded through `TXDATA`, in
order, followed by the first written byte, and leave the acquisition FIFO
empty.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_TXFULL,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_master_target_test_seq import _i2c_u32
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_target_ack_ctrl_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_ACQDATA,
    I2C0_CTRL,
    I2C0_FIFO_CTRL,
    I2C0_OVRD,
    I2C0_STATUS,
    I2C0_TARGET_FIFO_STATUS,
    I2C0_TARGET_ID,
    I2C0_TIMING0,
    I2C0_TIMING1,
    I2C0_TIMING2,
    I2C0_TIMING3,
    I2C0_TIMING4,
    I2C0_WRAP_CTRL,
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

I2C0_TXDATA = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR", 0)
CTRL_LLPBK = _i2c_u32("I2C__CTRL__LLPBK_bm")

TARGET_ADDR = 0x2A
VIP_SPEED = 2_000_000
ECHO = bytes((0xC5, 0x3A))
#: Upper bound on the transmit FIFO depth; the fill stops at STATUS.TXFULL.
MAX_TX_DEPTH = 512
SETTLE_CYCLES = 200


def _preload(index: int) -> int:
    return (0x11 + 3 * index) & 0xFF


class smc_i2c_target_loopback_test_seq(SmcCsrSeq):
    """Write to a looped-back target whose transmit FIFO is full, then read it all back."""

    def __init__(self, name: str = "smc_i2c_target_loopback_test_seq") -> None:
        super().__init__(name)
        self.depth = 0

    async def _acq_level(self, label: str) -> int:
        word = await self.csr_read(label, I2C0_TARGET_FIFO_STATUS)
        return (word & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP

    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_DISABLE", I2C0_CTRL, 0)
        await self.csr_write("I2C0_WRAP_TARGET", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready("I2C0_TARGET_LOOPBACK")
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
        await self.csr_write("I2C0_CTRL_TARGET", I2C0_CTRL, I2C_CTRL_ENABLETARGET)

        for index in range(MAX_TX_DEPTH):
            status = await self.csr_read(f"FILL_STATUS_{index}", I2C0_STATUS)
            if status & I2C_STATUS_TXFULL:
                self.depth = index
                break
            await self.csr_write(f"FILL_TXDATA_{index}", I2C0_TXDATA, _preload(index))
        else:
            raise AssertionError(f"STATUS.TXFULL never set over {MAX_TX_DEPTH} TXDATA writes")
        assert self.depth > 1, f"STATUS.TXFULL was set after {self.depth} TXDATA writes"
        await self.csr_write("TX_RESET", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_TXRST)
        preload = self.depth - 1
        for index in range(preload):
            await self.csr_write(f"LOAD_TXDATA_{index}", I2C0_TXDATA, _preload(index))
        status = await self.csr_read("LOADED_STATUS", I2C0_STATUS)
        assert not status & I2C_STATUS_TXFULL, (
            f"STATUS.TXFULL is set with {preload} of {self.depth} entries loaded (0x{status:08x})"
        )

        ctrl = I2C_CTRL_ENABLETARGET | CTRL_LLPBK | I2C_CTRL_ACQ_START_STOP_EN
        await self.csr_write("I2C0_CTRL_LOOPBACK", I2C0_CTRL, ctrl)
        await self.csr_read("I2C0_CTRL_LOOPBACK_RB", I2C0_CTRL, expected=ctrl)

        master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_loopback_master")
        await Timer(1, unit="us")
        await master.write(TARGET_ADDR, ECHO)
        await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        waiting = await self._acq_level("ACQ_BLOCKED")
        status = await self.csr_read("STATUS_BLOCKED", I2C0_STATUS)
        assert waiting == 2 and status & I2C_STATUS_TXFULL, (
            f"with one free transmit entry, a two-byte write left {waiting} acquisition entries "
            f"(STATUS=0x{status:08x}); the second byte and the STOP behind it must wait, and "
            f"the START entry must not"
        )
        word = await self.csr_read("ACQDATA_BLOCKED", I2C0_ACQDATA)
        signal = (word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP
        assert signal == I2C_ACQ_SIGNAL_NONE and word & 0xFF == ECHO[1], (
            f"ACQDATA returned 0x{word:08x}; the waiting entry is the data byte 0x{ECHO[1]:02x}"
        )
        await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        status = await self.csr_read("STATUS_UNBLOCKED", I2C0_STATUS)
        assert status & I2C_STATUS_ACQEMPTY, (
            f"the STOP entry did not leave after the data byte was read (STATUS=0x{status:08x})"
        )
        cocotb.log.info(
            "CHK-I2C-TGT-LOOPBACK-BLOCKED: with CTRL.LLPBK set and one free entry in a "
            "transmit FIFO of %d, a two-byte write left the second byte and its STOP waiting "
            "in the acquisition FIFO; ACQDATA returned that byte, 0x%02x, as data, and the "
            "STOP entry then left on its own",
            self.depth,
            ECHO[1],
        )

        got = await master.read(TARGET_ADDR, self.depth)
        want = bytes(_preload(i) for i in range(preload)) + ECHO[:1]
        assert got == want, (
            f"the read returned {got.hex()}, not the {preload} bytes loaded through TXDATA "
            f"followed by the first byte written ({want.hex()})"
        )
        await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        status = await self.csr_read("STATUS_END", I2C0_STATUS)
        assert status & I2C_STATUS_ACQEMPTY, (
            f"the acquisition FIFO is not empty after the read (STATUS=0x{status:08x}); in "
            f"loopback nothing in it is left for software"
        )
        await self.csr_write("I2C0_CTRL_OFF", I2C0_CTRL, 0)
        cocotb.log.info(
            "CHK-I2C-TGT-LOOPBACK-ECHO: a %d-byte read returned the %d TXDATA bytes in order "
            "and then the first written byte 0x%02x, looped back, and left the acquisition "
            "FIFO empty",
            len(got),
            preload,
            ECHO[0],
        )
