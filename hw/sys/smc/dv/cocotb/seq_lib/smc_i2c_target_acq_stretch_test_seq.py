# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target holds SCL low while its acquisition FIFO has no room.

``hw/ip/i2c/doc`` describes the target's acquisition FIFO as the only place a
received transaction lands, and ``STATUS.ACQFULL`` as the flag that says it has
no room. A controller that keeps writing past that point has to be held off,
and the only mechanism an I2C target has is to hold SCL low until software
makes room.

The bench drives the transaction from the pads: ``SmcI2cMasterVip`` bit-bangs
the open-drain bus on the ``tb_i2c0_*`` nets while the DUT's own I2C0 target is
the addressed device. The stretch is measured, not inferred: a monitor samples
the resolved SCL net together with the bench's own pull, and only counts the
cycles where the bus is low while the bench has released it -- which nothing
but the DUT can cause.

Draining the acquisition FIFO afterwards both releases the stretch and yields
the byte stream the target acquired, which is compared against what the bench
put on the wire. The address phase is carried by the controller itself: the
bench VIP raises on a NACK, so a write that completes is one the target
acknowledged from the address byte onwards.

Only the mid-transaction stretch is driven here; the hold through the address
phase of a repeated START is driven by `smc_i2c_target_addr_stretch_test_seq`.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_ACQFULL,
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
TARGET_ADDR = 0x22

# More payload bytes than any acquisition FIFO in this configuration holds, so
# the target runs out of room part-way through and has to hold the bus. The
# depth itself is measured from ACQLVL rather than assumed.
PAYLOAD = bytes((0x40 + i) & 0xFF for i in range(96))
# Bit-bang half-period; the VIP clocks one bus period per two of these, so this
# is a 1 MHz bus. Chosen so a 96-byte transfer costs under a millisecond of
# simulated time, not as a claim about any specified bus rate.
VIP_SPEED = 2_000_000

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
I2C0_WRAP_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", I2C0)
I2C0_OVRD = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR", I2C0)
I2C0_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR", I2C0)
I2C0_STATUS = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", I2C0)
I2C0_FIFO_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR", I2C0)
I2C0_TARGET_ID = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", I2C0)
I2C0_TARGET_FIFO_STATUS = smc_indexed_addr(
    "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR", I2C0
)
I2C0_ACQDATA = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR", I2C0)
I2C0_TIMING0 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR", I2C0)
I2C0_TIMING1 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR", I2C0)
I2C0_TIMING2 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR", I2C0)
I2C0_TIMING3 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR", I2C0)
I2C0_TIMING4 = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR", I2C0)

_ACQLVL_BM = 0xFFF0000
_ACQLVL_BP = 16
_ABYTE_BM = 0xFF

# Bounds on the DUT-side observations. Expiry is a failure, never a pass.
FULL_POLL_LIMIT = 4000
FULL_POLL_CYCLES = 200
DRAIN_LIMIT = 4096
COMPLETION_POLL_LIMIT = 4000
# Stretch samples that must land on "bus low, bench released" before the
# measurement counts as a hold rather than a sampling artifact.
MIN_STRETCH_SAMPLES = 16
# Sampling windows allowed before the hold has to have been seen.
STRETCH_WINDOWS = 64


class SclStretchMonitor:
    """Counts the cycles the DUT holds SCL low while the bench has released it."""

    def __init__(self) -> None:
        self.held = 0
        self.samples = 0
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.kill()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await ClockCycles(dut.clk_smc_i, 1)
            bus = dut.tb_i2c0_scl.value
            pull = dut.tb_i2c0_scl_ext_low.value
            if not (bus.is_resolvable and pull.is_resolvable):
                continue
            self.samples += 1
            if int(bus) == 0 and int(pull) == 0:
                self.held += 1


class smc_i2c_target_acq_stretch_test_seq(SmcCsrSeq):
    """Fill the I2C0 target acquisition FIFO and prove the target holds SCL."""

    def __init__(self, name: str = "smc_i2c_target_acq_stretch_test_seq") -> None:
        super().__init__(name)
        self.monitor = SclStretchMonitor()
        self.measured_depth = 0
        self.acquired: list[int] = []
        self.held_at_full = 0

    async def body(self) -> None:
        await self._bring_up_target()
        await self._fill_and_stretch()
        await self._drain_and_release()

    async def _pop_available(self) -> bool:
        """Read out every entry the acquisition FIFO currently holds."""
        fifo = await self.csr_read("I2C0_TARGET_FIFO_STATUS_DRAIN", I2C0_TARGET_FIFO_STATUS)
        level = (fifo & _ACQLVL_BM) >> _ACQLVL_BP
        for _ in range(level):
            word = await self.csr_read("I2C0_ACQDATA", I2C0_ACQDATA)
            self.acquired.append(word & _ABYTE_BM)
        return level > 0

    async def _bring_up_target(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_TARGET", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready("I2C0_TARGET_ACQ_STRETCH")
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
        await self.csr_write("I2C0_ENABLETARGET", I2C0_CTRL, I2C_CTRL_ENABLETARGET)
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        status = await self.csr_read("I2C0_STATUS_ENTRY", I2C0_STATUS)
        assert status & I2C_STATUS_ACQEMPTY, (
            f"I2C0 acquisition FIFO is not empty before any transaction (STATUS=0x{status:08x})"
        )
        assert not status & I2C_STATUS_ACQFULL, (
            f"I2C0 STATUS.ACQFULL is already set before any transaction (STATUS=0x{status:08x})"
        )

    async def _fill_and_stretch(self) -> None:
        master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_acq_stretch_master")
        self._write_task = cocotb.start_soon(master.write(TARGET_ADDR, PAYLOAD))

        status = 0
        for _ in range(FULL_POLL_LIMIT):
            status = await self.csr_read("I2C0_STATUS_FILL", I2C0_STATUS)
            if status & I2C_STATUS_ACQFULL:
                break
            assert not self._write_task.done(), (
                f"the controller finished all {len(PAYLOAD)} payload bytes without the target "
                f"ever setting STATUS.ACQFULL (0x{status:08x}), so no stretch could occur"
            )
            await ClockCycles(cocotb.top.clk_smc_i, FULL_POLL_CYCLES)
        else:
            raise AssertionError(
                f"I2C0 STATUS.ACQFULL never set while the controller wrote {len(PAYLOAD)} bytes "
                f"with nothing draining ACQDATA (last STATUS=0x{status:08x})"
            )

        fifo = await self.csr_read("I2C0_TARGET_FIFO_STATUS_FULL", I2C0_TARGET_FIFO_STATUS)
        self.measured_depth = (fifo & _ACQLVL_BM) >> _ACQLVL_BP
        assert self.measured_depth > 0, (
            f"STATUS.ACQFULL is set but TARGET_FIFO_STATUS.ACQLVL reads 0 "
            f"(TARGET_FIFO_STATUS=0x{fifo:08x})"
        )

        self.monitor.start()
        for _ in range(STRETCH_WINDOWS):
            await ClockCycles(cocotb.top.clk_smc_i, FULL_POLL_CYCLES)
            if self.monitor.held >= MIN_STRETCH_SAMPLES:
                break
            if self._write_task.done():
                break
        self.held_at_full = self.monitor.held
        cocotb.log.info(
            "I2C0 stretch measurement: held=%d samples=%d write_done=%s acqlvl=%d",
            self.monitor.held,
            self.monitor.samples,
            self._write_task.done(),
            self.measured_depth,
        )
        assert self.held_at_full >= MIN_STRETCH_SAMPLES, (
            f"with the acquisition FIFO full the bus was low while the bench had released SCL "
            f"on only {self.held_at_full} of {self.monitor.samples} samples, below the "
            f"{MIN_STRETCH_SAMPLES} that distinguish a hold from a sampling artifact; nothing "
            f"but the target can pull SCL low here "
            f"(controller write finished: {self._write_task.done()})"
        )
        cocotb.log.info(
            "CHK-I2C-TGT-ACQ-STRETCH: I2C0 STATUS.ACQFULL set with ACQLVL=%d entries, and the "
            "target held SCL low on %d of %d clk_smc_i samples taken while the bench had "
            "released its own pull",
            self.measured_depth,
            self.held_at_full,
            self.monitor.samples,
        )

    async def _drain_and_release(self) -> None:
        for _ in range(DRAIN_LIMIT):
            if self._write_task.done() and not await self._pop_available():
                break
            if not await self._pop_available():
                await ClockCycles(cocotb.top.clk_smc_i, FULL_POLL_CYCLES)
        else:
            raise AssertionError(
                f"the controller's {len(PAYLOAD)}-byte write never completed after "
                f"{DRAIN_LIMIT} acquisition-FIFO drain rounds released the stretch"
            )
        self._write_task.result()

        # CTRL.ACQ_START_STOP_EN is left at its reset, so the acquisition FIFO
        # carries the payload bytes without a start or stop entry around them.
        wanted = list(PAYLOAD)
        assert len(self.acquired) == len(wanted), (
            f"the target acquired {len(self.acquired)} entries for the {len(PAYLOAD)} payload "
            f"bytes the controller wrote"
        )
        assert self.acquired == wanted, (
            f"the acquired byte stream does not match what the bench put on the wire; "
            f"first difference at index "
            f"{next(i for i, (a, b) in enumerate(zip(self.acquired, wanted)) if a != b)}"
        )
        self.monitor.stop()
        status = await self.csr_read("I2C0_STATUS_RELEASED", I2C0_STATUS)
        assert not status & I2C_STATUS_ACQFULL, (
            f"I2C0 STATUS.ACQFULL still set after the acquisition FIFO drained to empty "
            f"(STATUS=0x{status:08x})"
        )
        assert status & I2C_STATUS_ACQEMPTY, (
            f"I2C0 STATUS.ACQEMPTY clear after every acquired entry was read "
            f"(STATUS=0x{status:08x})"
        )
        cocotb.log.info(
            "CHK-I2C-TGT-ACQ-DRAIN: draining ACQDATA released the hold and let the %d-byte "
            "write finish with every byte acknowledged -- the bench controller raises on a "
            "NACK of the address or of any data byte -- and the target acquired every payload "
            "byte in order (%d entries); STATUS.ACQFULL is clear",
            len(PAYLOAD),
            len(self.acquired),
        )
