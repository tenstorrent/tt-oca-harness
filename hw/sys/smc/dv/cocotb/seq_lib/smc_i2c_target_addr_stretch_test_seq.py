# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target holds SCL through the address phase of a repeated START.

`smc_i2c_target_acq_stretch_test` fills the acquisition FIFO part-way through
a transfer, so the target stretches at a *data* byte. The address phase is a
different path: the target has to hold the start or repeated-start entry as
well, and it can only do that with room for it.

The bench arranges the harder case. It writes until `STATUS.ACQFULL` reports
that the FIFO no longer has the room the target needs, and then, instead of a
STOP, issues a **repeated START** and the address again. Nothing has drained
the FIFO, so the address phase cannot be recorded and the target holds SCL
through it. Software then drains, which is the only thing that can release it,
and the transfer finishes.

`CTRL.NACK_ADDR_AFTER_TIMEOUT` selects which path the target takes to that
hold -- `i2c.rdl` gives it as ACK the address byte even if a stretch timeout
occurs (`0`, for SMBus) or NACK it (`1`) -- so both settings are driven, and
in both the transfer has to complete once the FIFO is drained. No stretch
timeout is enabled in either, so software is the only way out of the hold.

`CTRL.ACQ_START_STOP_EN` is set, so the acquired stream carries its own
framing: the repeated START arrives as an `ACQDATA.SIGNAL` of
`I2C_ACQ_SIGNAL_RESTART`, after every byte written before it. That entry is
what proves the held address phase was recorded after the drain rather than
lost.

The hold itself is measured the same way as the data-byte case, by
`SclStretchMonitor`: only samples where the bus is low while the bench has
released its own pull are counted, and nothing but the DUT can cause those.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_RESTART,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_CTRL_NACK_ADDR_AFTER_TIMEOUT,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_ACQFULL,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_target_acq_stretch_test_seq import SclStretchMonitor
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

I2C0 = 0
TARGET_ADDR = 0x23

# Bit-bang half-period, matching the other target-stretch leaves: the VIP
# clocks one bus period per two of these.
VIP_SPEED = 2_000_000
# More bytes than any acquisition FIFO in this configuration holds. The fill
# stops as soon as STATUS.ACQFULL reports the target is out of room, so this
# is only a bound on how long the bench will keep trying.
MAX_FILL_BYTES = 128
# Payload sent after the repeated START, once the hold has been released.
TAIL = bytes((0xA0 + i) & 0xFF for i in range(3))

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

_ABYTE_BM = 0xFF

# Bounds on the DUT-side observations. Expiry is a failure, never a pass.
POLL_CYCLES = 200
STRETCH_WINDOWS = 64
DRAIN_ROUNDS = 4096
MIN_STRETCH_SAMPLES = 16


class smc_i2c_target_addr_stretch_test_seq(SmcCsrSeq):
    """A repeated START against a full acquisition FIFO must hold the bus."""

    def __init__(self, name: str = "smc_i2c_target_addr_stretch_test_seq") -> None:
        super().__init__(name)
        self.legs: list[tuple[str, int, int]] = []

    async def _acqlvl(self, label: str) -> int:
        fifo = await self.csr_read(label, I2C0_TARGET_FIFO_STATUS)
        return (fifo & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP

    async def _pop_all(self, into: list[tuple[int, int]]) -> int:
        """Read out every entry the acquisition FIFO currently holds."""
        level = await self._acqlvl("I2C0_ACQLVL_DRAIN")
        for _ in range(level):
            word = await self.csr_read("I2C0_ACQDATA", I2C0_ACQDATA)
            signal = (word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP
            into.append((signal, word & _ABYTE_BM))
        return level

    async def _bring_up(self, ctrl: int, label: str) -> None:
        await self.csr_write(f"I2C0_DISABLE_{label}", I2C0_CTRL, 0)
        await self.csr_write("I2C0_WRAP_TARGET", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready(f"I2C0_ADDR_STRETCH_{label}")
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
        await self.csr_write(f"I2C0_CTRL_{label}", I2C0_CTRL, ctrl)
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        status = await self.csr_read(f"I2C0_STATUS_{label}_ENTRY", I2C0_STATUS)
        assert status & I2C_STATUS_ACQEMPTY, (
            f"{label}: the acquisition FIFO is not empty before the leg starts "
            f"(STATUS=0x{status:08x}); the fill below could not then be attributed to it"
        )
        assert not status & I2C_STATUS_ACQFULL, (
            f"{label}: STATUS.ACQFULL is already set before the leg starts (STATUS=0x{status:08x})"
        )

    async def _fill_until_full(self, master: SmcI2cMasterVip, label: str) -> list[int]:
        """Write bytes one at a time until the target reports it is out of room."""
        await master.send_start()
        nack = await master.send_byte((TARGET_ADDR & 0x7F) << 1)
        assert nack == 0, f"{label}: the target NACKed its own address at the first START"
        sent: list[int] = []
        for i in range(MAX_FILL_BYTES):
            status = await self.csr_read(f"I2C0_STATUS_FILL_{label}", I2C0_STATUS)
            if status & I2C_STATUS_ACQFULL:
                return sent
            value = (0x40 + i) & 0xFF
            nack = await master.send_byte(value)
            assert nack == 0, f"{label}: the target NACKed data byte {i} before it was full"
            sent.append(value)
        raise AssertionError(
            f"{label}: STATUS.ACQFULL never set while the bench wrote {MAX_FILL_BYTES} bytes "
            f"with nothing draining ACQDATA"
        )

    @staticmethod
    async def _restart_tail(master: SmcI2cMasterVip, acks: list[int]) -> None:
        """Repeated START, the address again, a short payload, then STOP."""
        await master.send_start()
        acks.append(await master.send_byte((TARGET_ADDR & 0x7F) << 1))
        for value in TAIL:
            acks.append(await master.send_byte(value))
        await master.send_stop()

    async def _leg(self, nack_addr_after_timeout: bool) -> None:
        label = "NACKADDR" if nack_addr_after_timeout else "ACKADDR"
        ctrl = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
        if nack_addr_after_timeout:
            ctrl |= I2C_CTRL_NACK_ADDR_AFTER_TIMEOUT
        await self._bring_up(ctrl, label)

        master = SmcI2cMasterVip(speed=VIP_SPEED, name=f"smc_i2c0_addr_stretch_{label.lower()}")
        sent = await self._fill_until_full(master, label)
        filled = await self._acqlvl(f"I2C0_ACQLVL_FULL_{label}")
        assert filled > 0, f"{label}: STATUS.ACQFULL is set but ACQLVL reads 0"

        # The repeated START goes out while nothing has drained, so the target
        # has to hold the bus through the address phase.
        acks: list[int] = []
        monitor = SclStretchMonitor()
        monitor.start()
        task = cocotb.start_soon(self._restart_tail(master, acks))
        for _ in range(STRETCH_WINDOWS):
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            if monitor.held >= MIN_STRETCH_SAMPLES or task.done():
                break
        held = monitor.held
        samples = monitor.samples
        assert not task.done(), (
            f"{label}: the repeated START and its payload completed with the acquisition FIFO "
            f"still full ({filled} entries) and nothing drained, so the target never held the "
            f"bus through the address phase"
        )
        assert held >= MIN_STRETCH_SAMPLES, (
            f"{label}: with the acquisition FIFO full at a repeated START the bus was low while "
            f"the bench had released SCL on only {held} of {samples} samples, below the "
            f"{MIN_STRETCH_SAMPLES} that distinguish a hold from a sampling artifact"
        )

        acquired: list[tuple[int, int]] = []
        for _ in range(DRAIN_ROUNDS):
            popped = await self._pop_all(acquired)
            if task.done() and popped == 0:
                break
            if popped == 0:
                await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{label}: the repeated START never completed after {DRAIN_ROUNDS} drain rounds "
                f"released the hold"
            )
        task.result()
        monitor.stop()

        assert acks and all(a == 0 for a in acks), (
            f"{label}: the target NACKed after the hold was released (ACK bits {acks}); the "
            f"address and every payload byte must be acknowledged once there is room again"
        )
        wanted = (
            [(I2C_ACQ_SIGNAL_START, (TARGET_ADDR & 0x7F) << 1)]
            + [(I2C_ACQ_SIGNAL_NONE, v) for v in sent]
            + [(I2C_ACQ_SIGNAL_RESTART, (TARGET_ADDR & 0x7F) << 1)]
            + [(I2C_ACQ_SIGNAL_NONE, v) for v in TAIL]
        )
        assert acquired[: len(wanted)] == wanted, (
            f"{label}: the acquired stream does not match the bench's traffic; first difference "
            f"at index "
            f"{next((i for i, (a, b) in enumerate(zip(acquired, wanted)) if a != b), len(wanted))} "
            f"(acquired {acquired[:8]}..., wanted {wanted[:8]}...)"
        )
        tail = acquired[len(wanted) :]
        # The STOP entry carries no byte of its own; the RDL defines only its
        # signal, so the data half is not compared.
        assert len(tail) == 1 and tail[0][0] == I2C_ACQ_SIGNAL_STOP, (
            f"{label}: the transfer did not end with a single STOP entry (tail {tail})"
        )
        status = await self.csr_read(f"I2C0_STATUS_{label}_DONE", I2C0_STATUS)
        assert status & I2C_STATUS_ACQEMPTY, (
            f"{label}: the acquisition FIFO is not empty after every entry was read "
            f"(STATUS=0x{status:08x})"
        )
        self.legs.append((label, held, len(acquired)))
        cocotb.log.info(
            "%s: the target held SCL on %d of %d samples through the address phase of a "
            "repeated START issued against a full acquisition FIFO, and the drain released it: "
            "%d entries acquired, ending in a STOP",
            label,
            held,
            samples,
            len(acquired),
        )

    async def body(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)

        await self._leg(nack_addr_after_timeout=False)
        cocotb.log.info(
            "CHK-I2C-TGT-ADDR-STRETCH: with CTRL.NACK_ADDR_AFTER_TIMEOUT clear, a repeated "
            "START against a full acquisition FIFO was held on the bus for %d of the samples "
            "taken while the bench had released SCL, and draining ACQDATA released it: the "
            "address was acknowledged, the restart entry was recorded after every byte written "
            "before it, and the transfer ended in a STOP (%d entries)",
            self.legs[0][1],
            self.legs[0][2],
        )

        await self._leg(nack_addr_after_timeout=True)
        cocotb.log.info(
            "CHK-I2C-TGT-ADDR-STRETCH-NACK-MODE: the same repeated START with "
            "CTRL.NACK_ADDR_AFTER_TIMEOUT set took the target's other address-phase path and "
            "reached the same result once drained: held on %d samples, %d entries acquired, "
            "ending in a STOP. No stretch timeout is enabled in either leg, so software is the "
            "only thing that can release the hold",
            self.legs[1][1],
            self.legs[1][2],
        )
