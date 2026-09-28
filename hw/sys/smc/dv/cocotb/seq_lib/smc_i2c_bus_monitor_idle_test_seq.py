# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The bus monitor's idle-with-SCL-high state, on every instance.

The bus monitor tracks whether the bus is free, busy, or busy but idling with
SCL released. `HOST_TIMEOUT_CTRL.VAL` arms the last of those: the RDL calls the
resulting interrupt a "Target Mode interrupt: asserted when the controller
stops generating the clock longer than `HOST_TIMEOUT_CTRL.VAL`". Nothing in
this package programs that register, so the monitor has never had reason to
leave its busy-with-SCL-low state.

`INTR_STATE.HOST_TIMEOUT` is what makes the state observable rather than
inferred. Only the idling state counts that timeout down, so the interrupt
firing is a witness that the monitor was in it -- and the leg that arms the
monitor with no bus traffic at all rules out any other explanation.

Three legs per instance:

* **Idle timeout** -- park the bus mid-transaction with SCL released and SDA
  stable, and let the timeout expire.
* **Resume and stop** -- park, then take SCL low again, and separately park and
  then drive a STOP, so the monitor leaves the idling state both ways.
  `TIMING4.T_BUF` is programmed long for this leaf so the post-STOP window is
  wide enough to drive into rather than a handful of cycles.
* **Enable with multi-controller monitoring** -- the monitor enters the idling
  state directly when it is enabled with `CTRL.MULTI_CONTROLLER_MONITOR_EN`
  set, which is the only way to reach it without the bus being busy first.
  Here the bus is quiet throughout, so the timeout can only have been counted
  in that state.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_CTRL_MULTI_CONTROLLER_MONITOR_EN,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_INTR_HOST_TIMEOUT,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_TARGETIDLE,
    I2C_WRAP_CTRL_TARGET,
    acq_abyte,
    acq_signal,
)
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_slot_utils import drive_to_slot, park_scl_high, release_bus
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
TARGET_ADDR = {0: 0x45, 1: 0x46, 2: 0x47}
CLEAN_BYTE = 0x2E
SWEEP_BYTE = 0xC7
VIP_SPEED = 2_000_000

# Inactive timeout in core clock cycles, and a park comfortably longer than it.
HOST_TIMEOUT_VAL = 1000
PARK_NS = 30_000
# Bus-free time after a STOP, also in core clock cycles. Programmed long so the
# window after a STOP is wide enough for the bench to drive the bus low again
# inside it; the default few cycles is shorter than a cocotb round trip.
T_BUF_LONG = 3000

POLL_CYCLES = 200
POLL_LIMIT = 200
DRAIN_LIMIT = 400
SETTLE_CYCLES = 20


class smc_i2c_bus_monitor_idle_test_seq(SmcCsrSeq):
    """Drive the bus monitor into and out of its idling state on every instance."""

    def __init__(self, name: str = "smc_i2c_bus_monitor_idle_test_seq") -> None:
        super().__init__(name)
        self.idle_timeouts: dict[int, int] = {}

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
            ("TIMING4", _pack_timing4(4, T_BUF_LONG)),
        ):
            await self.csr_write(f"I2C{idx}_{reg}", self._addr(reg, idx), value)

    async def _disconnect_all(self) -> None:
        for idx in INSTANCES:
            await self.csr_write(f"I2C{idx}_WRAP_OFF", self._wrap_addr(idx), 0)
            await self.csr_write(f"I2C{idx}_CTRL_OFF", self._addr("CTRL", idx), 0)

    async def _reset_fifos(self, idx: int) -> None:
        await self.csr_write(
            f"I2C{idx}_TGT_FIFO",
            self._addr("FIFO_CTRL", idx),
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_ACQRST,
        )

    async def _clear_intr(self, idx: int) -> None:
        await self.csr_write(
            f"I2C{idx}_INTR_CLR", self._addr("INTR_STATE", idx), I2C_INTR_HOST_TIMEOUT
        )
        # Only the host-timeout bit is cleared and checked: other interrupt
        # sources latch during ordinary traffic and are not this leaf's claim.
        after = await self.csr_read(f"I2C{idx}_INTR_CLR_RB", self._addr("INTR_STATE", idx))
        assert not after & I2C_INTR_HOST_TIMEOUT, (
            f"I2C{idx} INTR_STATE.HOST_TIMEOUT still set after writing it back "
            f"(INTR_STATE=0x{after:08x})"
        )

    async def _bring_up(self, idx: int, ctrl: int) -> None:
        await self.csr_write(f"I2C{idx}_WRAP_TGT", self._wrap_addr(idx), I2C_WRAP_CTRL_TARGET)
        await self._program_timing(idx)
        await self.csr_write(
            f"I2C{idx}_TGT_ID",
            self._addr("TARGET_ID", idx),
            _pack_target_id(TARGET_ADDR[idx], 0x7F, 0, 0),
        )
        await self.csr_write(
            f"I2C{idx}_HOST_TIMEOUT", self._addr("HOST_TIMEOUT_CTRL", idx), HOST_TIMEOUT_VAL
        )
        await self.csr_read(
            f"I2C{idx}_HOST_TIMEOUT_RB",
            self._addr("HOST_TIMEOUT_CTRL", idx),
            expected=HOST_TIMEOUT_VAL,
        )
        await self._reset_fifos(idx)
        await self.csr_write(f"I2C{idx}_TGT_CTRL", self._addr("CTRL", idx), ctrl)

    async def _wait_target_idle(self, idx: int, label: str) -> None:
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_TIDLE", self._addr("STATUS", idx))
            if status & I2C_STATUS_TARGETIDLE:
                return
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        raise AssertionError(f"{label}: I2C{idx} never reported TARGETIDLE (STATUS=0x{status:08x})")

    async def _drain_acq(self, idx: int, label: str) -> list[int]:
        words: list[int] = []
        for _ in range(DRAIN_LIMIT):
            status = await self.csr_read(f"{label}_ACQ_ST", self._addr("STATUS", idx))
            if status & I2C_STATUS_ACQEMPTY:
                return words
            words.append(int(await self.csr_read(f"{label}_ACQ", self._addr("ACQDATA", idx))))
        raise AssertionError(f"{label}: I2C{idx} acquisition FIFO never drained")

    async def _clean_transaction(self, vip: SmcI2cMasterVip, idx: int, label: str) -> None:
        await self._reset_fifos(idx)
        await vip.write(TARGET_ADDR[idx], bytes([CLEAN_BYTE]))
        await self._wait_target_idle(idx, label)
        words = await self._drain_acq(idx, label)
        data = [acq_abyte(w) for w in words if acq_signal(w) == I2C_ACQ_SIGNAL_NONE]
        assert data == [CLEAN_BYTE], (
            f"{label}: I2C{idx} acquired {[hex(b) for b in data]} for a clean one-byte write "
            f"of 0x{CLEAN_BYTE:02x}"
        )

    async def _intr(self, idx: int, label: str) -> int:
        return await self.csr_read(f"{label}_INTR", self._addr("INTR_STATE", idx))

    # --- leg: park the bus mid-transaction and let the timeout expire -----
    async def _idle_timeout(self, vip: SmcI2cMasterVip, idx: int) -> None:
        await self._clean_transaction(vip, idx, f"I2C{idx}_BM_CONTROL")
        await self._clear_intr(idx)
        await self._reset_fifos(idx)
        await drive_to_slot(vip, TARGET_ADDR[idx], SWEEP_BYTE, "addrack", 0)
        await park_scl_high(vip, PARK_NS)
        intr = await self._intr(idx, f"I2C{idx}_BM_PARK")
        assert intr & I2C_INTR_HOST_TIMEOUT, (
            f"I2C{idx} raised no HOST_TIMEOUT after the bench released SCL for {PARK_NS} ns "
            f"mid-transaction with HOST_TIMEOUT_CTRL.VAL={HOST_TIMEOUT_VAL} "
            f"(INTR_STATE=0x{intr:08x})"
        )
        self.idle_timeouts[idx] = 1
        await vip.send_stop()
        await release_bus(vip)
        await self._clear_intr(idx)
        await self._clean_transaction(vip, idx, f"I2C{idx}_BM_RECOVER")
        cocotb.log.info(
            "CHK-I2C%d-BUSMON-IDLE-TIMEOUT: with the bus busy and the bench holding SCL "
            "released for %d ns, the monitor counted HOST_TIMEOUT_CTRL.VAL=%d down and raised "
            "HOST_TIMEOUT, and the instance ran a clean write before and after",
            idx,
            PARK_NS,
            HOST_TIMEOUT_VAL,
        )

    # --- leg: leave the idling state by clocking again and by a STOP ------
    async def _resume_and_stop(self, vip: SmcI2cMasterVip, idx: int) -> None:
        await self._clear_intr(idx)
        await self._reset_fifos(idx)

        # Park, then take SCL low again before any STOP: the monitor goes back
        # to tracking a clocking bus.
        await drive_to_slot(vip, TARGET_ADDR[idx], SWEEP_BYTE, "data", 3)
        await park_scl_high(vip, PARK_NS)
        vip._pull_scl(True)
        await Timer(vip._bit_ns, unit="ns")
        vip._pull_scl(False)
        await vip._wait_scl_high()
        await Timer(vip._half_ns, unit="ns")

        # Park again, then drive a STOP out of the idling state. T_BUF is long
        # for this leaf, so the bus-free window after it is wide enough to
        # drive the bus low inside.
        await park_scl_high(vip, PARK_NS)
        await vip.send_stop()
        vip._pull_scl(True)
        vip._pull_sda(True)
        await Timer(vip._bit_ns, unit="ns")
        await release_bus(vip)
        await self._wait_target_idle(idx, f"I2C{idx}_BM_RESUME")
        await self._clear_intr(idx)
        await self._clean_transaction(vip, idx, f"I2C{idx}_BM_RESUME_RECOVER")
        cocotb.log.info(
            "CHK-I2C%d-BUSMON-RESUME: the monitor left the idling state both ways -- SCL "
            "taken low again, and a STOP driven out of it followed by the bus pulled low "
            "inside the %d-cycle bus-free window -- and the instance ran a clean write after",
            idx,
            T_BUF_LONG,
        )

    # --- leg: enable with multi-controller monitoring ---------------------
    async def _multi_controller_enable(self, vip: SmcI2cMasterVip, idx: int) -> None:
        """Enable the instance with multi-controller monitoring selected.

        The monitor enters its idling state on this enable rather than from
        bus activity. That entry has no observable of its own: the inactive
        counter is not reloaded on it, so the host-timeout witness the other
        legs use does not fire here, and nothing else in the register map
        reports the monitor's state. What this leg asserts is therefore only
        what it can measure -- that the instance enabled this way still runs a
        clean transaction. The entry itself is stimulus, not a claim.
        """
        await self.csr_write(f"I2C{idx}_CTRL_OFF_MC", self._addr("CTRL", idx), 0)
        await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        await self.csr_write(
            f"I2C{idx}_CTRL_MC",
            self._addr("CTRL", idx),
            I2C_CTRL_ENABLETARGET
            | I2C_CTRL_ACQ_START_STOP_EN
            | I2C_CTRL_MULTI_CONTROLLER_MONITOR_EN,
        )
        await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        await self.csr_write(
            f"I2C{idx}_CTRL_PLAIN",
            self._addr("CTRL", idx),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )
        await self._clean_transaction(vip, idx, f"I2C{idx}_BM_MC_RECOVER")
        cocotb.log.info(
            "CHK-I2C%d-BUSMON-MULTI-ENABLE: the instance was enabled with "
            "CTRL.MULTI_CONTROLLER_MONITOR_EN set on a quiet bus and then ran a clean write "
            "that was acquired byte for byte; the monitor's entry into its idling state on "
            "that enable is stimulus here, with no register that reports it",
            idx,
        )

    async def body(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "smc_i2c_bus_monitor_idle_test needs +smc_i2c_shared_bus; without it only I2C0's "
            "pads are on the bench bus"
        )
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for idx in INSTANCES:
            await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_LSIO")
        await self.wait_i2c_bus_released("I2C_SHARED_BUS")

        vip = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c_bus_monitor_master")
        for idx in INSTANCES:
            await self._disconnect_all()
            await self._bring_up(idx, I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN)
            await self._idle_timeout(vip, idx)
            await self._resume_and_stop(vip, idx)
            await self._multi_controller_enable(vip, idx)
        await self._disconnect_all()
