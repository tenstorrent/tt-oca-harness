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

#: Every instance is driven. `+smc_i2c_shared_bus` puts all three on one
#: open-drain bus, so the bench controller on I2C0's pads reaches each of them
#: by address, and only the instance under test is enabled while a leg runs.
INSTANCES = (0, 1, 2)
TARGET_ADDR = {0: 0x23, 1: 0x28, 2: 0x29}

# Bit-bang half-period, matching the other target-stretch leaves: the VIP
# clocks one bus period per two of these.
VIP_SPEED = 2_000_000
# More bytes than any acquisition FIFO in this configuration holds. The fill
# stops as soon as STATUS.ACQFULL reports the target is out of room, so this
# is only a bound on how long the bench will keep trying.
MAX_FILL_BYTES = 128
# Payload sent after the repeated START, once the hold has been released.
TAIL = bytes((0xA0 + i) & 0xFF for i in range(3))
#: Byte the target sources on the read leg, supplied only after the hold.
READ_BYTE = 0xB7

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_REGS = {
    "wrap": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR",
    "ovrd": "SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR",
    "ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR",
    "status": "SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR",
    "fifo_ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR",
    "target_id": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR",
    "fifo_status": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR",
    "acqdata": "SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR",
    "txdata": "SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR",
    "timing0": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR",
    "timing1": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR",
    "timing2": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR",
    "timing3": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR",
    "timing4": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR",
}


def _regs(idx: int) -> dict[str, int]:
    return {key: smc_indexed_addr(sym, idx) for key, sym in _REGS.items()}


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
        self.reads: list[tuple[str, int]] = []

    async def _acqlvl(self, r: dict[str, int], label: str) -> int:
        fifo = await self.csr_read(label, r["fifo_status"])
        return (fifo & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP

    async def _pop_all(self, r: dict[str, int], into: list[tuple[int, int]]) -> int:
        """Read out every entry the acquisition FIFO currently holds."""
        level = await self._acqlvl(r, "I2C_ACQLVL_DRAIN")
        for _ in range(level):
            word = await self.csr_read("I2C_ACQDATA", r["acqdata"])
            signal = (word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP
            into.append((signal, word & _ABYTE_BM))
        return level

    async def _disable_others(self, idx: int) -> None:
        for other in INSTANCES:
            if other != idx:
                await self.csr_write(f"I2C{other}_OFF", _regs(other)["ctrl"], 0)

    async def _bring_up(self, idx: int, ctrl: int, label: str) -> dict[str, int]:
        r = _regs(idx)
        await self.csr_write(f"I2C{idx}_DISABLE_{label}", r["ctrl"], 0)
        await self.csr_write(f"I2C{idx}_WRAP_TARGET", r["wrap"], I2C_WRAP_CTRL_TARGET)
        await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_ADDR_STRETCH_{label}")
        await self.csr_write(f"I2C{idx}_OVRD_OFF", r["ovrd"], 0)
        await self.csr_write(f"I2C{idx}_TIMING0", r["timing0"], _pack_timing0(0x1A, 0x32))
        await self.csr_write(f"I2C{idx}_TIMING1", r["timing1"], _pack_timing1(2, 2))
        await self.csr_write(f"I2C{idx}_TIMING2", r["timing2"], _pack_timing2(5, 4))
        await self.csr_write(f"I2C{idx}_TIMING3", r["timing3"], _pack_timing3(2, 5))
        await self.csr_write(f"I2C{idx}_TIMING4", r["timing4"], _pack_timing4(4, 5))
        await self.csr_write(
            f"I2C{idx}_FIFO_RST",
            r["fifo_ctrl"],
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST,
        )
        await self.csr_write(
            f"I2C{idx}_TARGET_ID", r["target_id"], _pack_target_id(TARGET_ADDR[idx], 0x7F, 0, 0)
        )
        await self.csr_write(f"I2C{idx}_CTRL_{label}", r["ctrl"], ctrl)
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        status = await self.csr_read(f"I2C{idx}_STATUS_{label}_ENTRY", r["status"])
        assert status & I2C_STATUS_ACQEMPTY, (
            f"I2C{idx} {label}: the acquisition FIFO is not empty before the leg starts "
            f"(STATUS=0x{status:08x}); the fill below could not then be attributed to it"
        )
        assert not status & I2C_STATUS_ACQFULL, (
            f"I2C{idx} {label}: STATUS.ACQFULL is already set before the leg starts "
            f"(STATUS=0x{status:08x})"
        )
        return r

    async def _fill_until_full(
        self, r: dict[str, int], master: SmcI2cMasterVip, idx: int, label: str
    ) -> list[int]:
        """Write bytes one at a time until the target reports it is out of room."""
        await master.send_start()
        nack = await master.send_byte((TARGET_ADDR[idx] & 0x7F) << 1)
        assert nack == 0, f"{label}: the target NACKed its own address at the first START"
        sent: list[int] = []
        for i in range(MAX_FILL_BYTES):
            status = await self.csr_read(f"I2C{idx}_STATUS_FILL_{label}", r["status"])
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
    async def _restart_tail(master: SmcI2cMasterVip, idx: int, acks: list[int]) -> None:
        """Repeated START, the address again, a short payload, then STOP."""
        await master.send_start()
        acks.append(await master.send_byte((TARGET_ADDR[idx] & 0x7F) << 1))
        for value in TAIL:
            acks.append(await master.send_byte(value))
        await master.send_stop()

    @staticmethod
    async def _restart_read(master: SmcI2cMasterVip, idx: int, acks: list[int], out: bytearray):
        """Repeated START with the read bit, one byte read back, then STOP."""
        await master.send_start()
        acks.append(await master.send_byte(((TARGET_ADDR[idx] & 0x7F) << 1) | 1))
        out.append(await master.recv_byte(ack=False))
        await master.send_stop()

    async def _measure_hold(self, label: str, task, filled: int) -> tuple[int, int]:
        monitor = SclStretchMonitor()
        monitor.start()
        for _ in range(STRETCH_WINDOWS):
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            if monitor.held >= MIN_STRETCH_SAMPLES or task.done():
                break
        held, samples = monitor.held, monitor.samples
        monitor.stop()
        assert not task.done(), (
            f"{label}: the repeated START completed with the acquisition FIFO still full "
            f"({filled} entries) and nothing drained, so the target never held the bus "
            f"through the address phase"
        )
        assert held >= MIN_STRETCH_SAMPLES, (
            f"{label}: with the acquisition FIFO full at a repeated START the bus was low "
            f"while the bench had released SCL on only {held} of {samples} samples, below the "
            f"{MIN_STRETCH_SAMPLES} that distinguish a hold from a sampling artifact"
        )
        return held, samples

    async def _leg(self, idx: int, nack_addr_after_timeout: bool) -> None:
        label = f"I2C{idx}_" + ("NACKADDR" if nack_addr_after_timeout else "ACKADDR")
        ctrl = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
        if nack_addr_after_timeout:
            ctrl |= I2C_CTRL_NACK_ADDR_AFTER_TIMEOUT
        r = await self._bring_up(idx, ctrl, label)

        master = SmcI2cMasterVip(speed=VIP_SPEED, name=f"smc_i2c{idx}_addr_stretch")
        sent = await self._fill_until_full(r, master, idx, label)
        filled = await self._acqlvl(r, f"I2C{idx}_ACQLVL_FULL_{label}")
        assert filled > 0, f"{label}: STATUS.ACQFULL is set but ACQLVL reads 0"

        acks: list[int] = []
        task = cocotb.start_soon(self._restart_tail(master, idx, acks))
        held, samples = await self._measure_hold(label, task, filled)

        acquired: list[tuple[int, int]] = []
        for _ in range(DRAIN_ROUNDS):
            popped = await self._pop_all(r, acquired)
            if task.done() and popped == 0:
                break
            if popped == 0:
                await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{label}: the repeated START never completed after {DRAIN_ROUNDS} drain "
                f"rounds released the hold"
            )
        task.result()

        assert acks and all(a == 0 for a in acks), (
            f"{label}: the target NACKed after the hold was released (ACK bits {acks}); the "
            f"address and every payload byte must be acknowledged once there is room again"
        )
        wanted = (
            [(I2C_ACQ_SIGNAL_START, (TARGET_ADDR[idx] & 0x7F) << 1)]
            + [(I2C_ACQ_SIGNAL_NONE, v) for v in sent]
            + [(I2C_ACQ_SIGNAL_RESTART, (TARGET_ADDR[idx] & 0x7F) << 1)]
            + [(I2C_ACQ_SIGNAL_NONE, v) for v in TAIL]
        )
        assert acquired[: len(wanted)] == wanted, (
            f"{label}: the acquired stream does not match the bench's traffic; first "
            f"difference at index "
            f"{next((i for i, (a, b) in enumerate(zip(acquired, wanted)) if a != b), len(wanted))}"
        )
        tail = acquired[len(wanted) :]
        # The STOP entry carries no byte of its own; the RDL defines only its
        # signal, so the data half is not compared.
        assert len(tail) == 1 and tail[0][0] == I2C_ACQ_SIGNAL_STOP, (
            f"{label}: the transfer did not end with a single STOP entry (tail {tail})"
        )
        status = await self.csr_read(f"I2C{idx}_STATUS_{label}_DONE", r["status"])
        assert status & I2C_STATUS_ACQEMPTY, (
            f"{label}: the acquisition FIFO is not empty after every entry was read "
            f"(STATUS=0x{status:08x})"
        )
        self.legs.append((label, held, len(acquired)))
        cocotb.log.info(
            "%s: the target held SCL on %d of %d samples through the address phase of a "
            "repeated START issued against a full acquisition FIFO, and the drain released "
            "it: %d entries acquired, ending in a STOP",
            label,
            held,
            samples,
            len(acquired),
        )

    async def _read_leg(self, idx: int) -> None:
        """The same hold, but the repeated START asks the target to transmit.

        The target leaves the address-phase stretch into the transmit stretch
        rather than into byte acquisition, and stays there until software
        supplies a byte -- so the drain alone does not release this one.
        """
        label = f"I2C{idx}_READADDR"
        ctrl = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
        r = await self._bring_up(idx, ctrl, label)

        master = SmcI2cMasterVip(speed=VIP_SPEED, name=f"smc_i2c{idx}_addr_stretch_read")
        await self._fill_until_full(r, master, idx, label)
        filled = await self._acqlvl(r, f"I2C{idx}_ACQLVL_FULL_{label}")

        acks: list[int] = []
        got = bytearray()
        task = cocotb.start_soon(self._restart_read(master, idx, acks, got))
        held, samples = await self._measure_hold(label, task, filled)

        acquired: list[tuple[int, int]] = []
        await self._pop_all(r, acquired)
        assert not task.done(), (
            f"{label}: the read completed on a drain alone; a target with nothing in its "
            f"transmit FIFO has to hold the bus until software supplies a byte"
        )
        await self.csr_write(f"I2C{idx}_TXDATA_{label}", r["txdata"], READ_BYTE)
        for _ in range(DRAIN_ROUNDS):
            if task.done():
                break
            await self._pop_all(r, acquired)
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{label}: the read never completed after the drain and a byte written into TXDATA"
            )
        task.result()
        await self._pop_all(r, acquired)

        assert acks and acks[0] == 0, (
            f"{label}: the target NACKed the read address after the hold (ACK bits {acks})"
        )
        assert bytes(got) == bytes([READ_BYTE]), (
            f"{label}: the bench read {bytes(got).hex()} where the byte written into TXDATA "
            f"after the hold was 0x{READ_BYTE:02x}"
        )
        signals = [s for s, _ in acquired]
        assert I2C_ACQ_SIGNAL_RESTART in signals, (
            f"{label}: no restart entry reached the acquisition FIFO, so the held address "
            f"phase was not recorded (acquired {acquired})"
        )
        self.reads.append((label, held))
        cocotb.log.info(
            "%s: the held address phase belonged to a read, so the target went on holding for "
            "a byte to send; it was released by a drain and a write into TXDATA, and the bench "
            "read back 0x%02x (held on %d of %d samples)",
            label,
            READ_BYTE,
            held,
            samples,
        )

    async def body(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "smc_i2c_target_addr_stretch_test needs +smc_i2c_shared_bus; without it only "
            "I2C0's pads are on the bench bus and the other two instances cannot be reached"
        )
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)

        for idx in INSTANCES:
            await self._disable_others(idx)
            await self._leg(idx, nack_addr_after_timeout=False)
            await self._leg(idx, nack_addr_after_timeout=True)
            await self._read_leg(idx)

        cocotb.log.info(
            "CHK-I2C-TGT-ADDR-STRETCH: with CTRL.NACK_ADDR_AFTER_TIMEOUT clear, a repeated "
            "START against a full acquisition FIFO was held on the bus and draining ACQDATA "
            "released it, on every instance: the address was acknowledged, the restart entry "
            "was recorded after every byte written before it, and the transfer ended in a "
            "STOP (%s)",
            ", ".join(
                f"{n} held {h} samples, {e} entries"
                for n, h, e in self.legs
                if "ACKADDR" in n and "NACK" not in n
            ),
        )
        cocotb.log.info(
            "CHK-I2C-TGT-ADDR-STRETCH-NACK-MODE: the same repeated START with "
            "CTRL.NACK_ADDR_AFTER_TIMEOUT set took the target's other address-phase path to "
            "the same result once drained, on every instance (%s). No stretch timeout is "
            "enabled in either leg, so software is the only thing that can release the hold",
            ", ".join(f"{n} held {h} samples" for n, h, _ in self.legs if "NACKADDR" in n),
        )
        cocotb.log.info(
            "CHK-I2C-TGT-ADDR-STRETCH-READ: when the held address phase belonged to a read, "
            "every instance went on holding for a byte to send and was released only by a "
            "drain and a write into TXDATA, after which the bench read back the byte (%s)",
            ", ".join(f"{n} held {h} samples" for n, h in self.reads),
        )
