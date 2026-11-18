# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The bus monitor's idle-with-SCL-high state, on every instance.

The bus monitor tracks whether the bus is free, busy, or busy but idling with
SCL released. `HOST_TIMEOUT_CTRL.VAL` arms the last of those: the RDL calls the
resulting interrupt a "Target Mode interrupt: asserted when the controller
stops generating the clock longer than `HOST_TIMEOUT_CTRL.VAL`".

`INTR_STATE.HOST_TIMEOUT` is what makes the state observable rather than
inferred. Only the idling state counts that timeout down, so the interrupt
firing is a witness that the monitor was in it -- and the leg that arms the
monitor with no bus traffic at all rules out any other explanation.

Three legs per instance:

* **Idle timeout** -- park the bus mid-transaction with SCL released and SDA
  stable, and let the timeout expire.
* **Resume and stop** -- park, then take SCL low again, and separately park and
  then drive a STOP, so the monitor leaves the idling state both ways. Each
  exit is witnessed twice: with the cleared interrupt staying clear through a
  hold as long as the park that raised it (SCL held low, or the bus released
  after the STOP), and with a further park raising it again, which a counter
  that never left the idling state cannot do once cleared.
* **Enable with multi-controller monitoring** -- the monitor enters the idling
  state directly when it is enabled with `CTRL.MULTI_CONTROLLER_MONITOR_EN`
  set, which is the only way to reach it without the bus being busy first.
  Here the bus is quiet throughout, so the timeout can only have been counted
  in that state.
* **Initial Bus Busy** -- `i2c.rdl` states that a `0`->`1` of
  `MULTI_CONTROLLER_MONITOR_EN` with both roles clear starts the monitor in
  the Bus Busy state, and that `HOST_TIMEOUT_CTRL` must be nonzero for it to
  reach Bus Free. The instance is enabled that way with `HOST_TIMEOUT_CTRL` at
  0, then given the controller role and a queued write: no START may appear
  on the quiet bus within twice the value the control uses. Enabled again
  with `HOST_TIMEOUT_CTRL.VAL` nonzero, the same queued write starts no
  earlier than `VAL` peripheral clocks after the enable and within a bound
  past it.
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
    I2C_CTRL_MULTI_CONTROLLER_MONITOR_EN,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_HOST_FIFO_STATUS_FMTLVL,
    I2C_INTR_HOST_TIMEOUT,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_HOSTIDLE,
    I2C_STATUS_TARGETIDLE,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
    acq_abyte,
    acq_signal,
)
from .smc_i2c_master_target_test_seq import _fdata, _i2c_u32
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
from .smc_i2c_wire_timing_test_seq import WireRecorder

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

INSTANCES = (0, 1, 2)
TARGET_ADDR = {0: 0x45, 1: 0x46, 2: 0x47}
CLEAN_BYTE = 0x2E
SWEEP_BYTE = 0xC7
VIP_SPEED = 2_000_000

# Inactive timeout in core clock cycles, and a park comfortably longer than it.
HOST_TIMEOUT_VAL = 1000
PARK_NS = 30_000

POLL_CYCLES = 200
POLL_LIMIT = 200
DRAIN_LIMIT = 400
SETTLE_CYCLES = 20

#: Idle count the initial-busy control programs, in core clock cycles; the
#: zero-value leg waits twice that for a START that must not come, and the
#: control's START is bounded past the count by the two register writes that
#: follow the enable and the controller's own START setup.
INIT_BUSY_VAL = 6000
NO_START_CYCLES = 2 * INIT_BUSY_VAL
START_BOUND_CYCLES = 3000
START_POLL_CYCLES = 64
FDATA_NAKOK = _i2c_u32("I2C__FDATA__NAKOK_bm")


class smc_i2c_bus_monitor_idle_test_seq(SmcCsrSeq):
    """Drive the bus monitor into and out of its idling state on every instance."""

    def __init__(self, name: str = "smc_i2c_bus_monitor_idle_test_seq") -> None:
        super().__init__(name)
        self.idle_timeouts: dict[int, int] = {}
        self.init_busy: dict[int, tuple[int, int, int]] = {}

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

    async def _expect_timeout(self, idx: int, label: str, how: str) -> None:
        intr = await self._intr(idx, label)
        assert intr & I2C_INTR_HOST_TIMEOUT, (
            f"I2C{idx} raised no HOST_TIMEOUT {how} with HOST_TIMEOUT_CTRL.VAL="
            f"{HOST_TIMEOUT_VAL} (INTR_STATE=0x{intr:08x})"
        )

    async def _expect_no_timeout(self, idx: int, label: str, how: str) -> None:
        intr = await self._intr(idx, label)
        assert not intr & I2C_INTR_HOST_TIMEOUT, (
            f"I2C{idx} raised HOST_TIMEOUT {how}, so the monitor was still counting the "
            f"idle timeout there (INTR_STATE=0x{intr:08x})"
        )

    # --- leg: leave the idling state by clocking again and by a STOP ------
    async def _resume_and_stop(self, vip: SmcI2cMasterVip, idx: int) -> None:
        await self._clear_intr(idx)
        await self._reset_fifos(idx)

        # Park, then take SCL low again before any STOP: the monitor goes back
        # to tracking a clocking bus. The park raises HOST_TIMEOUT; with SCL
        # held low for the same hold the cleared interrupt stays clear.
        await drive_to_slot(vip, TARGET_ADDR[idx], SWEEP_BYTE, "data", 3)
        await park_scl_high(vip, PARK_NS)
        await self._expect_timeout(
            idx, f"I2C{idx}_BM_RESUME_PARK", f"after the bench released SCL for {PARK_NS} ns"
        )
        vip._pull_scl(True)
        await self._clear_intr(idx)
        await Timer(PARK_NS, unit="ns")
        await self._expect_no_timeout(
            idx,
            f"I2C{idx}_BM_RESUME_SCL_LOW",
            f"while the bench held SCL low for {PARK_NS} ns after the park",
        )
        vip._pull_scl(False)
        await vip._wait_scl_high()
        await Timer(vip._half_ns, unit="ns")

        # Park again: the monitor is back in the idling state and the timeout
        # fires a second time. Then drive a STOP out of it and release the
        # bus; the same hold on the free bus leaves the cleared interrupt
        # clear.
        await park_scl_high(vip, PARK_NS)
        await self._expect_timeout(
            idx, f"I2C{idx}_BM_RESUME_REPARK", "on a second park after SCL had been taken low"
        )
        await vip.send_stop()
        await release_bus(vip)
        await self._clear_intr(idx)
        await Timer(PARK_NS, unit="ns")
        await self._expect_no_timeout(
            idx,
            f"I2C{idx}_BM_STOP_FREE",
            f"while the bus stayed free for {PARK_NS} ns after a STOP",
        )

        # A further park raises it once more.
        await self._reset_fifos(idx)
        await drive_to_slot(vip, TARGET_ADDR[idx], SWEEP_BYTE, "data", 3)
        await park_scl_high(vip, PARK_NS)
        await self._expect_timeout(idx, f"I2C{idx}_BM_STOP_REPARK", "on a park following the STOP")
        await vip.send_stop()
        await release_bus(vip)
        await self._wait_target_idle(idx, f"I2C{idx}_BM_RESUME")
        await self._clear_intr(idx)
        await self._clean_transaction(vip, idx, f"I2C{idx}_BM_RESUME_RECOVER")
        cocotb.log.info(
            "CHK-I2C%d-BUSMON-RESUME: the monitor left the idling state both ways -- after a "
            "park raised HOST_TIMEOUT, SCL held low for %d ns kept the cleared interrupt "
            "clear and a second park raised it again; after a STOP, the released bus held for "
            "%d ns kept it clear and a further park raised it again -- and the instance ran a "
            "clean write after",
            idx,
            PARK_NS,
            PARK_NS,
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
        ctrl_mc = (
            I2C_CTRL_ENABLETARGET
            | I2C_CTRL_ACQ_START_STOP_EN
            | I2C_CTRL_MULTI_CONTROLLER_MONITOR_EN
        )
        await self.csr_write(f"I2C{idx}_CTRL_MC", self._addr("CTRL", idx), ctrl_mc)
        await self.csr_read(f"I2C{idx}_CTRL_MC_RB", self._addr("CTRL", idx), expected=ctrl_mc)
        await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        await self._clean_transaction(vip, idx, f"I2C{idx}_BM_MC_RECOVER")
        await self.csr_write(
            f"I2C{idx}_CTRL_PLAIN",
            self._addr("CTRL", idx),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )
        cocotb.log.info(
            "CHK-I2C%d-BUSMON-MULTI-ENABLE: the instance was enabled with "
            "CTRL.MULTI_CONTROLLER_MONITOR_EN set on a quiet bus (CTRL read back 0x%08x) and, "
            "with the bit still set, ran a clean write that was acquired byte for byte; the "
            "monitor's entry into its idling state on that enable is stimulus here, with no "
            "register that reports it",
            idx,
            ctrl_mc,
        )

    # --- leg: the monitor starts busy, and stays busy with VAL at 0 --------
    async def _controller_monitor_enable(
        self, idx: int, label: str, val: int, rec: WireRecorder
    ) -> tuple[int, int]:
        """Enable the monitor with both roles clear, then the controller role and one write.

        Returns the recorder cycle before and after the enabling write, which
        bracket the instant the monitor started counting.
        """
        await self.csr_write(f"{label}_CTRL_OFF", self._addr("CTRL", idx), 0)
        await self.csr_write(f"{label}_HOST_TIMEOUT", self._addr("HOST_TIMEOUT_CTRL", idx), val)
        await self.csr_read(
            f"{label}_HOST_TIMEOUT_RB", self._addr("HOST_TIMEOUT_CTRL", idx), expected=val
        )
        await self.csr_write(
            f"{label}_FIFO_RST", self._addr("FIFO_CTRL", idx), I2C_FIFO_CTRL_RXRST_FMTRST
        )
        await self.csr_write(
            f"{label}_EVENTS_CLR", self._addr("CONTROLLER_EVENTS", idx), I2C_CONTROLLER_EVENTS_ALL
        )
        before = rec.cycle
        await self.csr_write(
            f"{label}_CTRL_MONITOR", self._addr("CTRL", idx), I2C_CTRL_MULTI_CONTROLLER_MONITOR_EN
        )
        after = rec.cycle
        await self.csr_write(
            f"{label}_CTRL_HOST",
            self._addr("CTRL", idx),
            I2C_CTRL_MULTI_CONTROLLER_MONITOR_EN | I2C_CTRL_ENABLEHOST,
        )
        await self.csr_write(
            f"{label}_FDATA",
            self._addr("FDATA", idx),
            _fdata(TARGET_ADDR[idx] << 1, I2C_FDATA_START | I2C_FDATA_STOP | FDATA_NAKOK),
        )
        return before, after

    async def _fmt_level(self, idx: int, label: str) -> int:
        fifo = await self.csr_read(f"{label}_HOST_FIFO_STATUS", self._addr("HOST_FIFO_STATUS", idx))
        return fifo & I2C_HOST_FIFO_STATUS_FMTLVL

    async def _init_busy(self, idx: int) -> None:
        label = f"I2C{idx}_BM_INIT"
        await self.csr_write(f"{label}_WRAP_HOST", self._wrap_addr(idx), I2C_WRAP_CTRL_HOST)
        await self._program_timing(idx)
        rec = WireRecorder()
        rec.start()

        # VAL 0: the monitor starts busy and never counts out to free, so the
        # queued write stays in the FMT FIFO and the bus sees no START.
        await self._controller_monitor_enable(idx, f"{label}_ZERO", 0, rec)
        await ClockCycles(cocotb.top.clk_periph_i, NO_START_CYCLES)
        zero_level = await self._fmt_level(idx, f"{label}_ZERO")
        assert rec.starts == 0 and rec.stops == 0, (
            f"I2C{idx}: {rec.starts} START and {rec.stops} STOP on the pads within "
            f"{NO_START_CYCLES} clk_periph_i cycles of a queued write with the monitor enabled "
            f"first and HOST_TIMEOUT_CTRL.VAL=0; i2c.rdl starts the monitor in Bus Busy and "
            f"needs a nonzero VAL to leave it"
        )
        assert zero_level == 1, (
            f"I2C{idx}: HOST_FIFO_STATUS.FMTLVL={zero_level} while the write waits on a bus the "
            f"monitor reports busy; the queued entry stays in the FMT FIFO"
        )
        await self.csr_write(f"{label}_ZERO_CTRL_OFF", self._addr("CTRL", idx), 0)
        await self.csr_write(
            f"{label}_ZERO_FIFO_RST", self._addr("FIFO_CTRL", idx), I2C_FIFO_CTRL_RXRST_FMTRST
        )
        dropped = await self._fmt_level(idx, f"{label}_ZERO_DROP")
        assert dropped == 0, f"I2C{idx}: FMTLVL={dropped} after FMTRST"

        # VAL nonzero: the same enable counts VAL idle cycles out and the
        # queued write starts no earlier than VAL after it, and soon after.
        before, after = await self._controller_monitor_enable(
            idx, f"{label}_VAL", INIT_BUSY_VAL, rec
        )
        bound = after + INIT_BUSY_VAL + START_BOUND_CYCLES
        while rec.starts == 0 and rec.cycle < bound:
            await ClockCycles(cocotb.top.clk_periph_i, START_POLL_CYCLES)
        assert rec.starts >= 1, (
            f"I2C{idx}: no START within {INIT_BUSY_VAL + START_BOUND_CYCLES} clk_periph_i cycles "
            f"of enabling the monitor with HOST_TIMEOUT_CTRL.VAL={INIT_BUSY_VAL}; {rec.state()}"
        )
        start = next(t for t, line, level in rec.events if line == "sda" and level == 0)
        assert start - before >= INIT_BUSY_VAL, (
            f"I2C{idx}: the START came {start - before} clk_periph_i cycles after the enabling "
            f"write was issued, before HOST_TIMEOUT_CTRL.VAL={INIT_BUSY_VAL} idle cycles were "
            f"counted out"
        )
        while rec.stops == 0 and rec.cycle < bound + START_BOUND_CYCLES:
            await ClockCycles(cocotb.top.clk_periph_i, START_POLL_CYCLES)
        assert rec.stops == 1 and rec.starts == 1, (
            f"I2C{idx}: {rec.starts} START and {rec.stops} STOP after the write; {rec.state()}"
        )
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_VAL_STATUS", self._addr("STATUS", idx))
            if status & I2C_STATUS_HOSTIDLE:
                break
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        assert status & I2C_STATUS_HOSTIDLE, f"I2C{idx}: HOSTIDLE never set (STATUS=0x{status:08x})"
        rec.stop()
        await self.csr_write(f"{label}_VAL_CTRL_OFF", self._addr("CTRL", idx), 0)
        await self.csr_write(
            f"{label}_VAL_EVENTS_CLR",
            self._addr("CONTROLLER_EVENTS", idx),
            I2C_CONTROLLER_EVENTS_ALL,
        )
        await self.csr_write(f"{label}_WRAP_OFF", self._wrap_addr(idx), 0)
        self.init_busy[idx] = (start - before, start - after, zero_level)

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
            await self._init_busy(idx)
        await self._disconnect_all()
        cocotb.log.info(
            "CHK-I2C-BUSMON-INIT-BUSY: on each of I2C%s, enabled with "
            "CTRL.MULTI_CONTROLLER_MONITOR_EN alone and then given the controller role and a "
            "queued write, HOST_TIMEOUT_CTRL.VAL=0 kept the bus free of any START for %d "
            "clk_periph_i cycles with the entry still in the FMT FIFO, and VAL=%d let the write "
            "start between %d and %d cycles after the enabling write (measured per instance, "
            "from before and from after that write: %s)",
            ", I2C".join(str(i) for i in sorted(self.init_busy)),
            NO_START_CYCLES,
            INIT_BUSY_VAL,
            INIT_BUSY_VAL,
            INIT_BUSY_VAL + START_BOUND_CYCLES,
            {f"I2C{i}": v[:2] for i, v in sorted(self.init_busy.items())},
        )
