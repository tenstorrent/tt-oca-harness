# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An I2C target read ended by something other than the controller.

While a target transmits, two things can end the transfer that the
controller did not ask for, and `i2c.rdl` gives each its own flag in
`TARGET_EVENTS`:

* **Arbitration lost.** "A controller has lost arbitration, causing a READ" to
  end: the target releases SDA to send a one and finds it low, so another
  device is driving the bus. `i2c_core.sv` detects it as the target
  transmitting while the line it released reads low with SCL high, and the
  target then refuses the rest of the transaction.
* **Bus timeout.** The target "has halted due a Bus Timeout terminating a
  READ": SCL is held low past `TIMEOUT_CTRL` in bus mode while the target has
  a read to answer.

Both are driven on I2C0 against the bench controller. For the arbitration
leg a second bench driver pulls SDA low inside the SCL high window of a data
bit the target is sending as a one -- the transmit FIFO holds all ones, so
every bit it sends is released. The pull is placed on an SCL rise counted from
the START, so it lands in the same bit every run. `TIMING3.THD_DAT` is raised
for that leg: the same pull is also an SDA edge with SCL high, which the bus
monitor would take for a START after `THD_DAT`, and the target gives a START
priority over arbitration loss. A hold of twenty core clocks is still well
inside the START the bench itself issues.

Each flag is then checked as a register: a word of zeros and a word of ones
that strobes only the top byte lane of `TARGET_EVENTS`, so the lane carrying
the bit is disabled while carrying a one, must both leave it set, and only a
written one clears it.
`TARGET_NACK_COUNT` is the second witness for arbitration loss, since the
target refuses the transaction on the same edge.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import ALL_ONES_WORD, TOP_BYTE_LANE, SmcCsrSeq
from .smc_i2c_field_masks import (
    _I2C_H,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_TIMEOUT_CTRL_EN,
    I2C_TIMEOUT_MODE_BUS,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_slot_utils import park_scl_low, release_bus
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

I2C0 = 0
TARGET_ADDR = 0x2C
VIP_SPEED = 2_000_000

EVENTS_BUS_TIMEOUT = _field_mask(_I2C_H, "I2C__TARGET_EVENTS__BUS_TIMEOUT_bm")
EVENTS_ARBITRATION_LOST = _field_mask(_I2C_H, "I2C__TARGET_EVENTS__ARBITRATION_LOST_bm")
NACK_COUNT_BM = 0xFF

#: Every bit the target sends is a one, so every bit is a released SDA.
TX_BYTE = 0xFF
#: SCL rises from the START: eight for the address, the ninth its acknowledge,
#: then the target's data bits. This is its second.
ARB_RISE = 11
#: Delay into the SCL high window before the pull, and the pull's length. Both
#: sit inside the bench controller's high period at this rate, and the delay is
#: longer than the bus monitor's settling window after an SCL edge.
ARB_DELAY_NS = 100
ARB_HOLD_NS = 200
#: Data hold time for the arbitration leg, in core clocks, which is also how
#: long an SDA edge with SCL high must last before the monitor takes it for a
#: START. See the module docstring.
ARB_THD_DAT = 20
NORMAL_THD_DAT = 5
#: Bus timeout for the timeout leg, in core clocks (10 ns), and how long the
#: bench holds SCL low: several times the limit.
BUS_TIMEOUT_CYCLES = 200
BUS_TIMEOUT_HOLD_NS = 10_000

EDGE_WAIT_CYCLES = 200_000
POLL_CYCLES = 100
POLL_LIMIT = 2000

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
_REGS = {
    "wrap": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR",
    "ovrd": "SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR",
    "ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR",
    "status": "SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR",
    "fifo_ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR",
    "target_id": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR",
    "txdata": "SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR",
    "timeout_ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMEOUT_CTRL_BASE_ADDR",
    "target_events": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_EVENTS_BASE_ADDR",
    "nack_count": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_NACK_COUNT_BASE_ADDR",
    "timing0": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR",
    "timing1": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR",
    "timing2": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR",
    "timing3": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR",
    "timing4": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR",
}
R = {key: smc_indexed_addr(sym, I2C0) for key, sym in _REGS.items()}


class smc_i2c_target_read_abort_test_seq(SmcCsrSeq):
    """A target read ended by arbitration loss, and by a bus timeout."""

    def __init__(self, name: str = "smc_i2c_target_read_abort_test_seq") -> None:
        super().__init__(name)
        self.arb_bits: bytes = b""
        self.retained: list[str] = []

    @staticmethod
    def _scl() -> int:
        raw = cocotb.top.tb_i2c0_scl.value
        assert raw.is_resolvable, f"tb_i2c0_scl is not resolvable: {raw}"
        return int(raw)

    async def _bring_up(self, label: str, thd_dat: int, bus_timeout: bool) -> None:
        await self.csr_write(f"{label}_OFF", R["ctrl"], 0)
        await self.csr_write(f"{label}_WRAP", R["wrap"], I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready(f"I2C0_READ_ABORT_{label}")
        await self.csr_write(f"{label}_OVRD", R["ovrd"], 0)
        await self.csr_write(f"{label}_TIMING0", R["timing0"], _pack_timing0(0x1A, 0x32))
        await self.csr_write(f"{label}_TIMING1", R["timing1"], _pack_timing1(2, 2))
        await self.csr_write(f"{label}_TIMING2", R["timing2"], _pack_timing2(5, 4))
        timing3 = _pack_timing3(2, thd_dat)
        await self.csr_write(f"{label}_TIMING3", R["timing3"], timing3)
        await self.csr_read(f"{label}_TIMING3_RB", R["timing3"], expected=timing3)
        await self.csr_write(f"{label}_TIMING4", R["timing4"], _pack_timing4(4, 5))
        await self.csr_write(
            f"{label}_FIFO_RST", R["fifo_ctrl"], I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST
        )
        await self.csr_write(
            f"{label}_TARGET_ID", R["target_id"], _pack_target_id(TARGET_ADDR, 0x7F, 0, 0)
        )
        timeout = (
            (I2C_TIMEOUT_CTRL_EN | I2C_TIMEOUT_MODE_BUS | BUS_TIMEOUT_CYCLES) if bus_timeout else 0
        )
        await self.csr_write(f"{label}_TIMEOUT", R["timeout_ctrl"], timeout)
        await self.csr_read(f"{label}_TIMEOUT_RB", R["timeout_ctrl"], expected=timeout)
        await self.csr_write(
            f"{label}_EVENTS_CLR", R["target_events"], EVENTS_BUS_TIMEOUT | EVENTS_ARBITRATION_LOST
        )
        events = await self.csr_read(f"{label}_EVENTS_ENTRY", R["target_events"])
        assert events & (EVENTS_BUS_TIMEOUT | EVENTS_ARBITRATION_LOST) == 0, (
            f"{label}: TARGET_EVENTS reads 0x{events:08x} before the leg starts"
        )
        await self.csr_read(f"{label}_NACK_CLR", R["nack_count"])
        await self.csr_write(
            f"{label}_CTRL", R["ctrl"], I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
        )
        await ClockCycles(cocotb.top.clk_smc_i, 20)

    async def _wait_start(self, label: str) -> None:
        sda = cocotb.top.tb_i2c0_sda
        prev = int(sda.value)
        for _ in range(EDGE_WAIT_CYCLES):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            now = int(sda.value)
            if self._scl() and prev and not now:
                return
            prev = now
        raise AssertionError(f"{label}: no START appeared on the bus")

    async def _pull_during_rise(self, puller: SmcI2cMasterVip, label: str) -> int:
        """Pull SDA low inside the high window of ARB_RISE; return SDA just before."""
        await self._wait_start(label)
        seen = 0
        prev = self._scl()
        for _ in range(EDGE_WAIT_CYCLES):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            now = self._scl()
            if now and not prev:
                seen += 1
                if seen == ARB_RISE:
                    await Timer(ARB_DELAY_NS, unit="ns")
                    before = int(cocotb.top.tb_i2c0_sda.value)
                    puller._pull_sda(True)
                    await Timer(ARB_HOLD_NS, unit="ns")
                    puller._pull_sda(False)
                    return before
            prev = now
        raise AssertionError(f"{label}: only {seen} of {ARB_RISE} SCL rises appeared")

    async def _retain(self, bit: int, name: str) -> None:
        """A set TARGET_EVENTS bit survives zeros and a one on a disabled lane; a one clears it."""
        before = await self.csr_read(f"{name}_BEFORE", R["target_events"])
        assert before & bit, f"{name}: not set before the retain checks (0x{before:08x})"
        await self.csr_write(f"{name}_ZERO", R["target_events"], 0)
        after_zero = await self.csr_read(f"{name}_AFTER_ZERO", R["target_events"])
        assert after_zero & bit, (
            f"{name}: cleared on a word of zeros (0x{after_zero:08x}); the field clears on a "
            f"written one"
        )
        await self.csr_write_strobed(
            f"{name}_LANE", R["target_events"], ALL_ONES_WORD, wstrb=TOP_BYTE_LANE
        )
        after_lane = await self.csr_read(f"{name}_AFTER_LANE", R["target_events"])
        assert after_lane & bit, (
            f"{name}: cleared on a word of ones that strobed only the top byte lane "
            f"(0x{after_lane:08x}); its own lane was disabled, so the one it carried must "
            f"not land"
        )
        await self.csr_write(f"{name}_CLEAR", R["target_events"], bit)
        cleared = await self.csr_read(f"{name}_CLEARED", R["target_events"])
        assert cleared & bit == 0, f"{name}: survived a written one (0x{cleared:08x})"
        self.retained.append(name)

    async def _arbitration_leg(self) -> None:
        label = "ARB"
        await self._bring_up(label, ARB_THD_DAT, bus_timeout=False)
        await self.csr_write(f"{label}_TXDATA", R["txdata"], TX_BYTE)
        master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_read_abort_master")
        puller = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_read_abort_puller")
        injector = cocotb.start_soon(self._pull_during_rise(puller, label))
        self.arb_bits = await master.read(TARGET_ADDR, 1)
        driven = await injector
        assert driven == 1, (
            f"{label}: SDA read {driven} just before the pull, so the target was not "
            f"releasing it there and the pull is not a conflict"
        )
        events = 0
        for _ in range(POLL_LIMIT):
            events = await self.csr_read(f"{label}_EVENTS", R["target_events"])
            if events & EVENTS_ARBITRATION_LOST:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{label}: TARGET_EVENTS.ARBITRATION_LOST never set after SDA was pulled low "
                f"under a one the target was sending (0x{events:08x})"
            )
        count = (await self.csr_read(f"{label}_NACK", R["nack_count"])) & NACK_COUNT_BM
        assert count == 1, (
            f"{label}: TARGET_NACK_COUNT reads {count}; losing arbitration makes the target "
            f"refuse the rest of the transaction, which it counts once"
        )
        await self._retain(EVENTS_ARBITRATION_LOST, "ARBITRATION_LOST")

    async def _bus_timeout_leg(self) -> None:
        label = "BUSTO"
        await self._bring_up(label, NORMAL_THD_DAT, bus_timeout=True)
        await self.csr_write(f"{label}_TXDATA", R["txdata"], TX_BYTE)
        master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_read_timeout_master")
        await master.send_start()
        ack = await master.send_byte(((TARGET_ADDR & 0x7F) << 1) | 1)
        assert ack == 0, f"{label}: the target did not acknowledge its read address"
        await park_scl_low(master, BUS_TIMEOUT_HOLD_NS)
        await release_bus(master)
        events = 0
        for _ in range(POLL_LIMIT):
            events = await self.csr_read(f"{label}_EVENTS", R["target_events"])
            if events & EVENTS_BUS_TIMEOUT:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{label}: TARGET_EVENTS.BUS_TIMEOUT never set after SCL was held low for "
                f"{BUS_TIMEOUT_HOLD_NS} ns during a read, against a limit of "
                f"{BUS_TIMEOUT_CYCLES} core clocks (0x{events:08x})"
            )
        await self._retain(EVENTS_BUS_TIMEOUT, "BUS_TIMEOUT")
        await self.csr_write(f"{label}_TIMEOUT_OFF", R["timeout_ctrl"], 0)

    async def body(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)

        await self._arbitration_leg()
        cocotb.log.info(
            "CHK-I2C-TGT-ARBITRATION-LOST: SDA pulled low inside the SCL high window of a one "
            "the target was sending raised TARGET_EVENTS.ARBITRATION_LOST, and the target "
            "refused the rest of the transaction, counting it once (bench read 0x%s)",
            self.arb_bits.hex(),
        )
        await self._bus_timeout_leg()
        cocotb.log.info(
            "CHK-I2C-TGT-READ-BUS-TIMEOUT: SCL held low past the bus timeout while the target "
            "had a read to answer raised TARGET_EVENTS.BUS_TIMEOUT"
        )
        cocotb.log.info(
            "CHK-I2C-TGT-EVENTS-RETAIN-ABORT: %s, each set by the target itself, survived a "
            "word of zeros written over it and a word of ones that strobed only the top byte "
            "lane, so its own lane carried a one it was not enabled to take, and cleared only "
            "on a written one",
            " and ".join(self.retained),
        )
