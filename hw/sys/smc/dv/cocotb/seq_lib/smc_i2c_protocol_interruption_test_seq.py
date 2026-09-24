# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transactions cut short at every phase, on all three I2C instances.

Most of what an I2C target state machine can be asked to do is leave the
transaction it is in. A STOP or a repeated START can arrive in any state, and
software can clear the target enable at any moment, so nearly every state has
an edge back to `Idle`, to `WaitForStop` and to `AcquireStart`. Reaching those
edges needs the interruption to land in a chosen state, which means driving it
at a chosen bit slot -- something only the bench controller can do, since a DUT
controller has no way to be told "stop in the middle of this byte".

`SmcI2cMasterVip` bit-bangs the open-drain bus, so each leg drives a partial
transaction and then injects the interruption from whatever slot it stopped at:

* **Address phase** -- the interruption lands before the target has matched the
  address, so nothing is acquired. What must hold is that the instance is left
  able to run a clean transaction immediately afterwards.
* **Data phase** -- the target has matched by then, so each interrupted
  transaction leaves a START marker in the acquisition FIFO, and the count of
  those markers is compared against the number of transactions driven.
* **Target enable cleared from a held state** -- the bench stops clocking at a
  chosen payload bit, or the target is left stretching for software, so the
  disable lands in the same state every run rather than wherever a delay
  happened to reach. The instance must go idle and then recover.
* **Controller enable cleared mid-transaction** -- the same on the controller
  side, with I2C0 driving a queued format-FIFO transaction.

Each leg opens and closes with a clean transaction against the same instance.
The opening one is the positive control: a sweep against an instance the bench
cannot reach at all would otherwise pass every "nothing was acquired" check
vacuously. The closing one is the recovery proof.

Bit slots come from the VIP's own bit timing, not from any RTL constant: a slot
is a call to its `send_bit`, and the interruption is its own `send_stop` or
`send_start` issued from the slot the loop stopped at.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_START,
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_CTRL_ACK_CTRL_EN,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACK_CTRL_STRETCH,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_HOSTIDLE,
    I2C_STATUS_TARGETIDLE,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
    acq_abyte,
    acq_signal,
)
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_slot_utils import release_bus
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
# One address per instance so a transfer cannot be answered by the wrong one.
TARGET_ADDR = {0: 0x38, 1: 0x39, 2: 0x3A}
CLEAN_BYTE = 0x6D
SWEEP_BYTE = 0xB4
# Bit-bang half-period; the VIP clocks one bus period per two of these.
VIP_SPEED = 2_000_000

# Where the interruption lands. "addr" k is after k bits of the address byte;
# "addrack" is after the address acknowledge has been clocked; "data" k is
# after k bits of the payload byte; "dataack" is after the payload
# acknowledge. The acknowledge slots are injected after rather than during:
# the target owns SDA while it acknowledges, so a controller physically cannot
# release SDA for a STOP in the middle of one.
ADDR_POINTS = [("addr", k) for k in range(1, 8)]
DATA_POINTS = [("addrack", 0)] + [("data", k) for k in range(1, 8)] + [("dataack", 0)]
KINDS = ("stop", "restart")

# Delays, in VIP bit periods, at which the target enable is cleared while a
# byte is on the wire. Spread across the address byte, the acknowledge slot and
# the payload byte so the write lands in different states.
#: Where the bench stops clocking before it clears the target enable. A slot
#: is a number of payload bits driven after the address acknowledge, so the
#: target is parked waiting for the next bit and the disable lands in the same
#: state every run. Delays measured from a poll of STATUS were used before,
#: which put the disable in a different state from seed to seed.
DISABLE_PARK_SLOTS = (("EARLY", 1), ("MID", 4), ("LATE", 7))

# Bounds on the DUT-side observations, in clk_smc_i cycles so they scale with
# the randomised clock. Expiry is a failure, never a pass.
POLL_CYCLES = 200
POLL_LIMIT = 400
DRAIN_LIMIT = 600
BIT_SETTLE_CYCLES = 40


class smc_i2c_protocol_interruption_test_seq(SmcCsrSeq):
    """Cut transactions short at every phase and prove each instance recovers."""

    def __init__(self, name: str = "smc_i2c_protocol_interruption_test_seq") -> None:
        super().__init__(name)
        self.addr_phase_injections: dict[int, int] = {}
        self.data_phase_injections: dict[int, int] = {}
        self.data_phase_starts: dict[int, int] = {}
        self.disable_recoveries: dict[int, int] = {}
        self.host_disable_ok = False

    # --- addressing ------------------------------------------------------
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

    async def _enable_target(self, idx: int, extra_ctrl: int = 0) -> None:
        await self.csr_write(f"I2C{idx}_WRAP_TGT", self._wrap_addr(idx), I2C_WRAP_CTRL_TARGET)
        await self._program_timing(idx)
        await self.csr_write(
            f"I2C{idx}_TGT_ID",
            self._addr("TARGET_ID", idx),
            _pack_target_id(TARGET_ADDR[idx], 0x7F, 0, 0),
        )
        await self._reset_target_fifos(idx)
        await self.csr_write(
            f"I2C{idx}_TGT_CTRL",
            self._addr("CTRL", idx),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN | extra_ctrl,
        )

    async def _reset_target_fifos(self, idx: int) -> None:
        await self.csr_write(
            f"I2C{idx}_TGT_FIFO",
            self._addr("FIFO_CTRL", idx),
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_ACQRST,
        )

    async def _wait_target_idle(self, idx: int, label: str) -> None:
        """Block until the target reports itself between transactions.

        Each interrupted transaction has to be finished with before the next
        one starts, otherwise its tail lands in the next one's acquisition
        window and the address of the next is acquired as payload.
        """
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_TGT_IDLE", self._addr("STATUS", idx))
            if status & I2C_STATUS_TARGETIDLE:
                return
            await ClockCycles(cocotb.top.clk_smc_i, BIT_SETTLE_CYCLES)
        raise AssertionError(
            f"{label}: I2C{idx} never reported TARGETIDLE after the transaction was cut short "
            f"(STATUS=0x{status:08x})"
        )

    async def _drain_acq(self, idx: int, label: str) -> list[int]:
        status_addr = self._addr("STATUS", idx)
        acq_addr = self._addr("ACQDATA", idx)
        words: list[int] = []
        for _ in range(DRAIN_LIMIT):
            status = await self.csr_read(f"{label}_ACQ_ST", status_addr)
            if status & I2C_STATUS_ACQEMPTY:
                return words
            words.append(int(await self.csr_read(f"{label}_ACQ", acq_addr)) & 0xFFFF)
        raise AssertionError(f"{label}: I2C{idx} acquisition FIFO never drained")

    # --- bus traffic ------------------------------------------------------
    async def _clean_transaction(self, vip: SmcI2cMasterVip, idx: int, label: str) -> None:
        """One complete write the target must acquire, byte for byte."""
        await self._reset_target_fifos(idx)
        await vip.write(TARGET_ADDR[idx], bytes([CLEAN_BYTE]))
        await self._wait_target_idle(idx, label)
        words = await self._drain_acq(idx, label)
        data = [acq_abyte(w) for w in words if acq_signal(w) == I2C_ACQ_SIGNAL_NONE]
        assert data == [CLEAN_BYTE], (
            f"{label}: I2C{idx} acquired {[hex(b) for b in data]} for a clean one-byte write "
            f"of 0x{CLEAN_BYTE:02x}"
        )

    async def _drive_to_point(
        self, vip: SmcI2cMasterVip, idx: int, phase: str, k: int, read: bool = False
    ) -> None:
        """Drive a transaction up to the chosen slot and stop clocking there."""
        addr_byte = (TARGET_ADDR[idx] << 1) | int(read)
        await vip.send_start()
        for i in range(k if phase == "addr" else 8):
            await vip.send_bit((addr_byte >> (7 - i)) & 1)
        if phase == "addr":
            return
        await vip.recv_bit()
        if phase == "addrack":
            return
        for i in range(k if phase == "data" else 8):
            await vip.send_bit((SWEEP_BYTE >> (7 - i)) & 1)
        if phase == "data":
            return
        await vip.recv_bit()

    async def _raw_write(self, vip: SmcI2cMasterVip, idx: int, count: int) -> None:
        """Drive a write with the acknowledge levels ignored.

        ``SmcI2cMasterVip.write`` raises on a NACK, and a target disabled
        part-way through this transfer will not acknowledge. What is under test
        is the target, so the levels are read and discarded rather than turned
        into a verdict about the controller.
        """
        addr_byte = (TARGET_ADDR[idx] << 1) | 0
        await vip.send_start()
        for i in range(8):
            await vip.send_bit((addr_byte >> (7 - i)) & 1)
        await vip.recv_bit()
        for _ in range(count):
            for i in range(8):
                await vip.send_bit((SWEEP_BYTE >> (7 - i)) & 1)
            await vip.recv_bit()
        await vip.send_stop()

    async def _inject(self, vip: SmcI2cMasterVip, kind: str) -> None:
        if kind == "stop":
            await vip.send_stop()
            return
        await vip.send_start()
        await vip.send_stop()

    async def _phase_sweep(
        self, vip: SmcI2cMasterVip, idx: int, points: list[tuple[str, int]], label: str
    ) -> list[tuple[str, str, int, list[int]]]:
        """Run one interrupted transaction per slot and kind, draining after each.

        Draining per injection rather than once at the end is what lets a
        failure name the slot it came from instead of an aggregate count.
        """
        results: list[tuple[str, str, int, list[int]]] = []
        for kind in KINDS:
            for phase, k in points:
                slot = f"{label}_{kind}_{phase}{k}"
                await self._reset_target_fifos(idx)
                await self._drive_to_point(vip, idx, phase, k)
                await self._inject(vip, kind)
                await self._wait_target_idle(idx, slot)
                words = await self._drain_acq(idx, slot)
                results.append((kind, phase, k, words))
        return results

    # --- legs -------------------------------------------------------------
    async def _interruption_legs(self, vip: SmcI2cMasterVip, idx: int) -> None:
        await self._clean_transaction(vip, idx, f"I2C{idx}_CONTROL")

        results = await self._phase_sweep(vip, idx, ADDR_POINTS, f"I2C{idx}_ADDR")
        injections = len(results)
        self.addr_phase_injections[idx] = injections
        for kind, phase, k, words in results:
            data = [acq_abyte(w) for w in words if acq_signal(w) == I2C_ACQ_SIGNAL_NONE]
            assert not data, (
                f"I2C{idx} acquired payload bytes {[hex(b) for b in data]} from a transaction "
                f"cut short by {kind} at {phase}{k}, before its address byte completed"
            )
        await self._clean_transaction(vip, idx, f"I2C{idx}_ADDR_RECOVER")
        cocotb.log.info(
            "CHK-I2C%d-INTR-ADDR-PHASE: %d transactions cut short at every address-byte slot, "
            "by STOP and by repeated START, left no payload byte "
            "acquired, and the instance ran a clean write before and after the sweep",
            idx,
            injections,
        )

        results = await self._phase_sweep(vip, idx, DATA_POINTS, f"I2C{idx}_DATA")
        injections = len(results)
        self.data_phase_injections[idx] = injections
        starts = 0
        for kind, phase, k, words in results:
            seen = sum(1 for w in words if acq_signal(w) == I2C_ACQ_SIGNAL_START)
            starts += seen
            assert seen >= 1, (
                f"I2C{idx} recorded no START entry for a transaction cut short by {kind} at "
                f"{phase}{k}, though its address byte completed and was acknowledged "
                f"(acquisition FIFO held {[hex(w) for w in words]})"
            )
        self.data_phase_starts[idx] = starts
        await self._clean_transaction(vip, idx, f"I2C{idx}_DATA_RECOVER")
        cocotb.log.info(
            "CHK-I2C%d-INTR-DATA-PHASE: %d transactions cut short after the address acknowledge, "
            "at every payload-byte slot and after the payload acknowledge, by STOP and by "
            "repeated START, each left at least one "
            "START entry in the acquisition FIFO (%d recorded in total), and the instance "
            "ran a clean write "
            "before and after the sweep",
            idx,
            injections,
            starts,
        )

    async def _disable_from_state(
        self, vip: SmcI2cMasterVip, idx: int, name: str, park_bits: int
    ) -> None:
        """Clear the target enable while the target is parked in a named state.

        ``park_bits`` bits of a payload byte are clocked and then the bench
        stops clocking, so the target is left waiting for the next bit for as
        long as the bench chooses. Where the disable lands is then a property
        of the bus, not of when a poll happened to return.
        """
        label = f"I2C{idx}_TGT_OFF_{name}"
        await self._reset_target_fifos(idx)
        addr_byte = (TARGET_ADDR[idx] << 1) | 0
        await vip.send_start()
        for i in range(8):
            await vip.send_bit((addr_byte >> (7 - i)) & 1)
        ack = await vip.recv_bit()
        assert ack == 0, f"{label}: the target did not acknowledge its address (ACK bit {ack})"
        for i in range(park_bits):
            await vip.send_bit((SWEEP_BYTE >> (7 - i)) & 1)
        await self.csr_write(label, self._addr("CTRL", idx), 0)
        await self._wait_target_idle(idx, label)
        await release_bus(vip)
        await self._enable_target(idx)
        await self._clean_transaction(vip, idx, f"{label}_REC")

    async def _disable_while_stretching(self, vip: SmcI2cMasterVip, idx: int) -> None:
        """Clear the target enable while the target is stretching for software.

        ACK Control Mode with its count at reset stops the target at the first
        data byte and holds it there until software answers, so the disable
        lands in the stretch state every run rather than wherever a delay
        happened to reach.
        """
        label = f"I2C{idx}_TGT_OFF_STRETCH"
        await self.csr_write(f"{label}_OFF", self._addr("CTRL", idx), 0)
        await self._enable_target(idx, extra_ctrl=I2C_CTRL_ACK_CTRL_EN)
        task = cocotb.start_soon(self._raw_write(vip, idx, 1))
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_ST", self._addr("STATUS", idx))
            if status & I2C_STATUS_ACK_CTRL_STRETCH:
                break
            assert not task.done(), (
                f"{label}: the write finished without the target ever stretching for the ACK "
                f"count (STATUS=0x{status:08x})"
            )
            await ClockCycles(cocotb.top.clk_smc_i, BIT_SETTLE_CYCLES)
        else:
            raise AssertionError(
                f"{label}: STATUS.ACK_CTRL_STRETCH never set (last 0x{status:08x})"
            )
        await self.csr_write(label, self._addr("CTRL", idx), 0)
        await self._wait_target_idle(idx, label)
        for _ in range(POLL_LIMIT):
            if task.done():
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        if not task.done():
            task.kill()
        await release_bus(vip)
        await self._enable_target(idx)
        await self._clean_transaction(vip, idx, f"{label}_REC")

    async def _target_disable_leg(self, vip: SmcI2cMasterVip, idx: int) -> None:
        for name, park_bits in DISABLE_PARK_SLOTS:
            await self._disable_from_state(vip, idx, name, park_bits)
        await self._disable_while_stretching(vip, idx)
        self.disable_recoveries[idx] = len(DISABLE_PARK_SLOTS) + 1
        cocotb.log.info(
            "CHK-I2C%d-INTR-TARGET-DISABLE: clearing CTRL target enable from each of %d states "
            "the bus itself holds the target in -- %s, and the stretch it takes when ACK "
            "Control Mode is enabled with its count at reset -- left I2C%d reporting "
            "TARGETIDLE, and a clean transaction ran against it afterwards each time",
            idx,
            self.disable_recoveries[idx],
            ", ".join(f"{n} ({b} payload bits clocked)" for n, b in DISABLE_PARK_SLOTS),
            idx,
        )

    async def _host_disable_leg(self, idx: int) -> None:
        """Clear the controller enable while its queued transaction is on the wire."""
        await self._disconnect_all()
        tgt = 1 if idx == 0 else 0
        await self._enable_target(tgt)
        await self.csr_write(f"I2C{idx}_HOST_WRAP", self._wrap_addr(idx), I2C_WRAP_CTRL_HOST)
        await self._program_timing(idx)
        await self.csr_write(f"I2C{idx}_HOST_OVRD", self._addr("OVRD", idx), 0)
        await self.csr_write(
            f"I2C{idx}_HOST_FIFO", self._addr("FIFO_CTRL", idx), I2C_FIFO_CTRL_RXRST_FMTRST
        )
        await self.csr_write(
            f"I2C{idx}_HOST_CEV",
            self._addr("CONTROLLER_EVENTS", idx),
            I2C_CONTROLLER_EVENTS_ALL,
        )
        ctrl_addr = self._addr("CTRL", idx)
        await self.csr_write(f"I2C{idx}_HOST_ON", ctrl_addr, I2C_CTRL_ENABLEHOST)

        fdata = self._addr("FDATA", idx)
        addr_w = (TARGET_ADDR[tgt] << 1) | 0
        await self.csr_write(f"I2C{idx}_HD_START", fdata, I2C_FDATA_START | addr_w)
        for byte in (SWEEP_BYTE, SWEEP_BYTE, SWEEP_BYTE):
            await self.csr_write(f"I2C{idx}_HD_DATA", fdata, byte)
        await self.csr_write(f"I2C{idx}_HD_STOP", fdata, I2C_FDATA_STOP | SWEEP_BYTE)

        status_addr = self._addr("STATUS", idx)
        left_idle = False
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"I2C{idx}_HD_BUSY", status_addr)
            if not status & I2C_STATUS_HOSTIDLE:
                left_idle = True
                break
            await ClockCycles(cocotb.top.clk_smc_i, BIT_SETTLE_CYCLES)
        assert left_idle, (
            f"controller I2C{idx} never left idle after a transaction was queued, so clearing "
            f"its enable would interrupt nothing"
        )
        await self.csr_write(f"I2C{idx}_HOST_OFF", ctrl_addr, 0)
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"I2C{idx}_HD_OFF_ST", status_addr)
            if status & I2C_STATUS_HOSTIDLE:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"controller I2C{idx} never returned to idle after its enable was cleared "
                f"mid-transaction (STATUS=0x{status:08x})"
            )

        # Recovery: the same controller runs a clean transaction the target acquires.
        await self.csr_write(
            f"I2C{idx}_HOST_FIFO_REC", self._addr("FIFO_CTRL", idx), I2C_FIFO_CTRL_RXRST_FMTRST
        )
        await self.csr_write(f"I2C{idx}_HOST_ON_REC", ctrl_addr, I2C_CTRL_ENABLEHOST)
        await self._reset_target_fifos(tgt)
        await self.csr_write(f"I2C{idx}_REC_START", fdata, I2C_FDATA_START | addr_w)
        await self.csr_write(f"I2C{idx}_REC_STOP", fdata, I2C_FDATA_STOP | CLEAN_BYTE)
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"I2C{idx}_REC_ST", status_addr)
            if status & I2C_STATUS_HOSTIDLE:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        words = await self._drain_acq(tgt, f"I2C{idx}_REC")
        data = [acq_abyte(w) for w in words if acq_signal(w) == I2C_ACQ_SIGNAL_NONE]
        assert data == [CLEAN_BYTE], (
            f"after recovering from a mid-transaction disable, controller I2C{idx} wrote "
            f"{[hex(b) for b in data]} instead of [0x{CLEAN_BYTE:02x}] to target I2C{tgt}"
        )
        self.host_disable_ok = True
        cocotb.log.info(
            "CHK-I2C%d-INTR-HOST-DISABLE: clearing CTRL host enable while a queued format-FIFO "
            "transaction was on the wire returned the controller to idle, and it then drove a "
            "clean write that target I2C%d acquired",
            idx,
            tgt,
        )

    async def body(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "smc_i2c_protocol_interruption_test needs +smc_i2c_shared_bus; without it only "
            "I2C0's pads are on the bench bus"
        )
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for idx in INSTANCES:
            await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_LSIO")
        await self.wait_i2c_bus_released("I2C_SHARED_BUS")

        vip = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c_interruption_master")
        for idx in INSTANCES:
            await self._disconnect_all()
            await self._enable_target(idx)
            await self._interruption_legs(vip, idx)
            await self._target_disable_leg(vip, idx)

        await self._host_disable_leg(0)
        await self._disconnect_all()
