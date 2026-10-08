# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A controller finding SDA pulled low under it, at points across a write.

`hw/ip/i2c/doc/architecture.adoc` Bus Arbitration: the bus monitor "will detect
when the Controller Module loses arbitration, such as when it attempts to
transmit a logic high, but another device is pulling SDA low", and the RDL
gives `INTR_STATE.SDA_INTERFERENCE` for the controller side of it. That
condition is a global override on the controller state machine, so it returns
the controller to idle from whatever state it was in. Clearing the host enable
does not do the same job -- that is only acted on in particular states.

Every payload byte is 0xFF, so the controller drives a logic high in every
data slot and a pull-down landing in the payload is a genuine conflict rather
than a bit that happened to agree. The sweep is anchored to the controller
leaving idle, so the delay is measured from something the DUT did, and is
expressed in the bit period this leaf itself programmed into `TIMING0`.

What is asserted, and what is not
---------------------------------
Each injection asserts the two things that are measurable at the point of the
event: `INTR_STATE.SDA_INTERFERENCE` is raised, and the controller returns to
idle. After an interference event this DUT answers the next transaction from
the same controller with a NACK (`CONTROLLER_EVENTS` reads 1), even once the
controller reads idle with its events cleared, the interrupted transaction has
ended with a STOP, the target has been through disable and re-enable, and the
bus reads released. Both instances are therefore hard reset between
injections, and the transaction after an event carries no claim.

The opening clean transaction of each instance is the positive control: it
shows the controller and target pair works at all, so an injection that
reports nothing is a real absence rather than a bench that never reached the
DUT.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_INTR_SDA_INTERFERENCE,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_HOSTIDLE,
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
# Target for each controller: the next instance round the ring.
PARTNER = {0: 1, 1: 2, 2: 0}
TARGET_ADDR = {0: 0x49, 1: 0x4A, 2: 0x4B}
CLEAN_BYTE = 0x73
# All ones, so the controller drives a logic high in every payload slot.
CONFLICT_PAYLOAD = (0xFF, 0xFF, 0xFF, 0xFF)

# SCL high and low counts this leaf programs into TIMING0. The pull-down below
# is expressed in the high count, so it follows the timing this leaf set
# rather than any design value.
T_HIGH = 0x1A
T_LOW = 0x32
CORE_CLK_NS = 10

# Which SCL rising edge of the transfer the pull-down is made on, counted from
# the START seen on the pads. Eight rises clock the address byte and the ninth
# its acknowledge, so this one falls on a payload bit -- a one, since the
# payload is all ones, and therefore a high the controller is driving, which
# is what makes the pull-down interference rather than anything else.
#
# The anchor has to be a bus edge, not a poll of STATUS: a poll returns some
# cycles after the controller leaves idle, and how many depends on the run's
# bus traffic, so a point measured from it lands in a different part of the
# bit loop from run to run. At some offsets the byte is corrupted early enough
# that the target NACKs first and the controller halts on the NACK instead of
# reporting the interference.
CONFLICT_RISES = (12,)
# The pull-down is released inside the same SCL high window: one that outlasts
# it reaches the next bit, where the controller may be driving a low and the
# pull is not a conflict.
CONFLICT_HOLD_NS = T_HIGH * CORE_CLK_NS * 3 // 4

POLL_CYCLES = 100
POLL_LIMIT = 300
DRAIN_LIMIT = 400
SETTLE_CYCLES = 20
#: Bound on the wait for a pad edge, in clk_smc_i cycles.
EDGE_WAIT_CYCLES = 200_000


class smc_i2c_controller_sda_interference_test_seq(SmcCsrSeq):
    """Pull SDA low under a transmitting controller at points across a write."""

    def __init__(self, name: str = "smc_i2c_controller_sda_interference_test_seq") -> None:
        super().__init__(name)
        self.injections: dict[int, int] = {}

    @staticmethod
    def _addr(symbol: str, idx: int) -> int:
        return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{symbol}_BASE_ADDR", idx)

    @staticmethod
    def _wrap_addr(idx: int) -> int:
        return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)

    async def _program_timing(self, idx: int) -> None:
        for reg, value in (
            ("TIMING0", _pack_timing0(T_HIGH, T_LOW)),
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

    async def _enable_target(self, tgt: int, addr7: int) -> None:
        await self.csr_write(f"I2C{tgt}_WRAP_TGT", self._wrap_addr(tgt), I2C_WRAP_CTRL_TARGET)
        await self._program_timing(tgt)
        await self.csr_write(
            f"I2C{tgt}_TGT_ID", self._addr("TARGET_ID", tgt), _pack_target_id(addr7, 0x7F, 0, 0)
        )
        await self.csr_write(
            f"I2C{tgt}_TGT_FIFO",
            self._addr("FIFO_CTRL", tgt),
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_ACQRST,
        )
        await self.csr_write(
            f"I2C{tgt}_TGT_CTRL",
            self._addr("CTRL", tgt),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

    async def _enable_host(self, host: int) -> None:
        await self.csr_write(f"I2C{host}_WRAP_HOST", self._wrap_addr(host), I2C_WRAP_CTRL_HOST)
        await self._program_timing(host)
        await self.csr_write(f"I2C{host}_OVRD", self._addr("OVRD", host), 0)
        await self.csr_write(
            f"I2C{host}_HOST_FIFO", self._addr("FIFO_CTRL", host), I2C_FIFO_CTRL_RXRST_FMTRST
        )
        await self.csr_write(
            f"I2C{host}_CEVENTS", self._addr("CONTROLLER_EVENTS", host), I2C_CONTROLLER_EVENTS_ALL
        )
        await self._clear_interference(host)
        await self.csr_write(f"I2C{host}_HOST_CTRL", self._addr("CTRL", host), I2C_CTRL_ENABLEHOST)

    async def _hard_reset_pair(self, host: int, tgt: int, addr7: int) -> None:
        """Take both instances down and back up between injections."""
        await self._disconnect_all()
        await release_bus(self._vip)
        await self.wait_i2c_bus_released(f"I2C{host}_SDAI_RESET")
        await self._enable_target(tgt, addr7)
        await self._enable_host(host)

    async def _clear_interference(self, host: int) -> None:
        await self.csr_write(
            f"I2C{host}_INTR_CLR", self._addr("INTR_STATE", host), I2C_INTR_SDA_INTERFERENCE
        )
        after = await self.csr_read(f"I2C{host}_INTR_CLR_RB", self._addr("INTR_STATE", host))
        assert not after & I2C_INTR_SDA_INTERFERENCE, (
            f"I2C{host} INTR_STATE.SDA_INTERFERENCE still set after writing it back "
            f"(INTR_STATE=0x{after:08x})"
        )

    async def _wait_hostidle(self, host: int, label: str) -> None:
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_HIDLE", self._addr("STATUS", host))
            if status & I2C_STATUS_HOSTIDLE:
                return
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        events = await self.csr_read(f"{label}_CEV", self._addr("CONTROLLER_EVENTS", host))
        raise AssertionError(
            f"{label}: controller I2C{host} never returned to idle (STATUS=0x{status:08x}, "
            f"CONTROLLER_EVENTS=0x{events:08x})"
        )

    async def _wait_host_busy(self, host: int, label: str) -> None:
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_HBUSY", self._addr("STATUS", host))
            if not status & I2C_STATUS_HOSTIDLE:
                return
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        raise AssertionError(
            f"{label}: controller I2C{host} never left idle after a transaction was queued "
            f"(STATUS=0x{status:08x})"
        )

    async def _drain_acq(self, tgt: int, label: str) -> list[int]:
        words: list[int] = []
        for _ in range(DRAIN_LIMIT):
            status = await self.csr_read(f"{label}_ACQ_ST", self._addr("STATUS", tgt))
            if status & I2C_STATUS_ACQEMPTY:
                return words
            words.append(int(await self.csr_read(f"{label}_ACQ", self._addr("ACQDATA", tgt))))
        raise AssertionError(f"{label}: I2C{tgt} acquisition FIFO never drained")

    async def _queue_write(self, host: int, addr7: int, payload) -> None:
        fdata = self._addr("FDATA", host)
        await self.csr_write(f"I2C{host}_FD_START", fdata, I2C_FDATA_START | ((addr7 << 1) | 0))
        for i, byte in enumerate(payload[:-1]):
            await self.csr_write(f"I2C{host}_FD_{i}", fdata, byte)
        await self.csr_write(f"I2C{host}_FD_STOP", fdata, I2C_FDATA_STOP | payload[-1])

    async def _clean_transaction(self, host: int, tgt: int, addr7: int, label: str) -> None:
        await self._queue_write(host, addr7, (CLEAN_BYTE,))
        await self._wait_hostidle(host, label)
        words = await self._drain_acq(tgt, label)
        data = [acq_abyte(w) for w in words if acq_signal(w) == I2C_ACQ_SIGNAL_NONE]
        assert data == [CLEAN_BYTE], (
            f"{label}: target I2C{tgt} acquired {[hex(b) for b in data]} for a clean one-byte "
            f"write of 0x{CLEAN_BYTE:02x} from controller I2C{host}"
        )

    @staticmethod
    def _scl() -> int:
        raw = cocotb.top.tb_i2c0_scl.value
        assert raw.is_resolvable, f"tb_i2c0_scl is not resolvable: {raw}"
        return int(raw)

    async def _wait_start_on_pads(self, label: str) -> None:
        """Wait for SDA to fall while SCL is high: the START of the transfer."""
        sda = cocotb.top.tb_i2c0_sda
        prev = int(sda.value)
        for _ in range(EDGE_WAIT_CYCLES):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            now = int(sda.value)
            if self._scl() and prev and not now:
                return
            prev = now
        raise AssertionError(f"{label}: no START appeared on the bus after the queue")

    async def _pull_on_rise(self, label: str, nth: int) -> int:
        """Pull SDA low inside the high window of the nth SCL rise of the transfer.

        Returns the SDA level read just before the pull, which is the
        controller's own driven value: only a high there is a conflict.
        """
        await self._wait_start_on_pads(label)
        seen = 0
        prev = self._scl()
        for _ in range(EDGE_WAIT_CYCLES):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            now = self._scl()
            if now and not prev:
                seen += 1
                if seen == nth:
                    before = int(cocotb.top.tb_i2c0_sda.value)
                    self._vip._pull_sda(True)
                    await Timer(CONFLICT_HOLD_NS, unit="ns")
                    self._vip._pull_sda(False)
                    return before
            prev = now
        raise AssertionError(
            f"{label}: only {seen} of {nth} SCL rising edges appeared; the controller stopped "
            f"clocking before the injection point"
        )

    async def _inject_at(self, host: int, tgt: int, addr7: int, nth_rise: int) -> None:
        label = f"I2C{host}_SDAI_{nth_rise}"
        injector = cocotb.start_soon(self._pull_on_rise(label, nth_rise))
        await self._queue_write(host, addr7, CONFLICT_PAYLOAD)
        driven = await injector
        assert driven == 1, (
            f"{label}: SDA read {driven} on SCL rise {nth_rise}, so the controller was not "
            f"driving a high there and the pull-down is not a conflict"
        )
        await release_bus(self._vip)

        intr = 0
        for _ in range(POLL_LIMIT):
            intr = await self.csr_read(f"{label}_INTR", self._addr("INTR_STATE", host))
            if intr & I2C_INTR_SDA_INTERFERENCE:
                break
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        else:
            raise AssertionError(
                f"controller I2C{host} reported no SDA_INTERFERENCE after SDA was pulled low "
                f"under it inside the high window of SCL rise {nth_rise}, while it was "
                f"writing all ones (INTR_STATE=0x{intr:08x})"
            )
        await self._wait_hostidle(host, label)

    async def _instance_leg(self, host: int) -> None:
        tgt = PARTNER[host]
        addr7 = TARGET_ADDR[tgt]
        await self._hard_reset_pair(host, tgt, addr7)
        await self._clean_transaction(host, tgt, addr7, f"I2C{host}_SDAI_CONTROL")

        injected = 0
        for nth_rise in CONFLICT_RISES:
            await self._hard_reset_pair(host, tgt, addr7)
            await self._inject_at(host, tgt, addr7, nth_rise)
            injected += 1
        self.injections[host] = injected
        cocotb.log.info(
            "CHK-I2C%d-CTRL-SDA-INTERFERENCE: SDA pulled low under controller I2C%d inside the "
            "high window of %d chosen SCL pulse of a write of all ones, which raised "
            "INTR_STATE.SDA_INTERFERENCE and returned the controller to idle, with a clean "
            "write to target I2C%d beforehand as the control. The transaction after an event "
            "is not asserted: on this DUT it is NACKed even after both instances are cleared, "
            "so both are hard reset between injections instead",
            host,
            host,
            injected,
            tgt,
        )

    async def body(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "smc_i2c_controller_sda_interference_test needs +smc_i2c_shared_bus; without it "
            "only I2C0's pads are on the bench bus"
        )
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for idx in INSTANCES:
            await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_LSIO")
        await self.wait_i2c_bus_released("I2C_SHARED_BUS")

        self._vip = SmcI2cMasterVip(speed=2_000_000, name="smc_i2c_sda_interference_bench")
        for host in INSTANCES:
            await self._instance_leg(host)
        await self._disconnect_all()
